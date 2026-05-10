"""BPS+ positioning engine.

Self-contained module that provides:
  * Per-link distance smoothing (time-weighted EWMA + MAD outlier reject).
  * Robust weighted nonlinear-least-squares trilateration with HDOP.
  * Constant-velocity Kalman filter for position smoothing.
  * Stationarity detection for opportunistic auto-calibration.
  * Linear path-loss-style auto-calibrator (factor + offset, optional exponent).

The module operates in pixel space (the same space as the floor map). The
caller is responsible for converting raw distances (meters) into pixels
through the floor scale.

All public functions/classes are pure-Python and have no Home Assistant
dependency, which keeps them unit-testable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import least_squares

_LOGGER = logging.getLogger(__name__)


# Calibration factor/offset clamps shared by Python and JS so a fit accepted
# in the panel is also accepted by the engine. Must match the JS constants
# in frontend/script.js:computeAutoCalibrationForSamples.
CAL_FACTOR_MIN = 0.2
CAL_FACTOR_MAX = 5.0
CAL_OFFSET_MIN = -10.0
CAL_OFFSET_MAX = 10.0


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------

def apply_calibration(raw_distance: float, calibration: dict | None) -> float:
    """Apply a path-loss-style correction to a raw distance (meters).

    Model:  corrected = factor * raw**exponent + offset
    """
    if raw_distance is None:
        return float("nan")
    cal = calibration or {}
    try:
        factor = float(cal.get("factor", 1.0))
    except (TypeError, ValueError):
        factor = 1.0
    try:
        offset = float(cal.get("offset", 0.0))
    except (TypeError, ValueError):
        offset = 0.0
    try:
        exponent = float(cal.get("exponent", 1.0))
    except (TypeError, ValueError):
        exponent = 1.0

    if not math.isfinite(raw_distance) or raw_distance < 0:
        return 0.0
    if exponent != 1.0 and raw_distance > 0:
        base = math.pow(raw_distance, exponent)
    else:
        base = raw_distance
    return max(0.0, factor * base + offset)


# ---------------------------------------------------------------------------
# Per-link distance smoother (time-weighted EWMA + MAD outlier reject)
# ---------------------------------------------------------------------------

class DistanceSmoother:
    """EWMA smoother with MAD-based outlier rejection.

    Time-weighted: alpha is recomputed per sample as ``1 - exp(-Δt / tau)``
    so a burst of advertisements after a long silence does NOT collapse the
    history into the burst. Falls back to ``base_alpha`` when no timestamp
    is supplied (legacy callers).
    """

    __slots__ = (
        "base_alpha",
        "tau",
        "window",
        "mad_threshold",
        "_history",
        "_ewma",
        "_var",
        "_last_t",
    )

    def __init__(
        self,
        alpha: float = 0.4,
        window: int = 8,
        mad_threshold: float = 3.5,
        tau_seconds: float = 1.5,
    ) -> None:
        self.base_alpha = float(alpha)
        self.tau = max(0.1, float(tau_seconds))
        self.window = int(window)
        self.mad_threshold = float(mad_threshold)
        self._history: list[float] = []
        self._ewma: float | None = None
        self._var: float = 0.0
        self._last_t: float | None = None

    def push(
        self, value: float, t: float | None = None
    ) -> tuple[float | None, float, bool]:
        """Feed a new sample. Returns (smoothed_value, sigma, accepted)."""
        if value is None or not math.isfinite(value) or value < 0:
            sigma = math.sqrt(self._var) if self._var > 0 else 1.0
            return self._ewma, sigma, False

        accepted = True
        if len(self._history) >= 4:
            arr = np.asarray(self._history, dtype=float)
            median = float(np.median(arr))
            mad = float(np.median(np.abs(arr - median))) or 1e-3
            robust_sigma = 1.4826 * mad
            if abs(value - median) > self.mad_threshold * robust_sigma:
                accepted = False

        if accepted:
            self._history.append(value)
            if len(self._history) > self.window:
                self._history.pop(0)
            if self._ewma is None:
                self._ewma = value
                self._var = 0.0
            else:
                # Time-weighted alpha so a burst after a long gap does not
                # over-write the smoother. Older samples decay exponentially
                # with time constant `tau`. When no timestamp is supplied we
                # fall back to the classic constant alpha.
                if t is not None and self._last_t is not None:
                    dt = max(0.0, float(t) - float(self._last_t))
                    eff_alpha = 1.0 - math.exp(-dt / self.tau) if dt > 0 else 0.0
                    eff_alpha = max(0.0, min(self.base_alpha, eff_alpha))
                else:
                    eff_alpha = self.base_alpha
                delta = value - self._ewma
                self._ewma = self._ewma + eff_alpha * delta
                self._var = (
                    (1.0 - eff_alpha) * (self._var + eff_alpha * delta * delta)
                )
            if t is not None:
                self._last_t = float(t)

        if self._var > 0:
            sigma = math.sqrt(self._var)
        else:
            base = self._ewma if self._ewma is not None else value
            sigma = max(0.05, 0.05 * abs(base))
        return self._ewma, sigma, accepted

    @property
    def value(self) -> float | None:
        return self._ewma


# ---------------------------------------------------------------------------
# Trilateration
# ---------------------------------------------------------------------------

@dataclass
class DistanceSample:
    """A filtered distance reading expressed in pixel space."""
    receiver_id: str
    x: float
    y: float
    raw_distance_m: float
    distance_m: float
    radius_px: float
    sigma_px: float


def _walls_to_array(walls: Iterable[dict] | None) -> np.ndarray:
    """Pack wall segments into an (N, 4) numpy array [x1, y1, x2, y2].

    Replaces the previous shapely LineString implementation, which
    allocated 4-12 Python objects per residual evaluation. With 5 walls
    and 6 receivers `least_squares` evaluates residuals ~80 times → 240+
    shapely allocs per fit. The numpy version vectorises the segment-vs-
    segment intersection test and is ~30× faster on typical floors.
    """
    rows: list[list[float]] = []
    for wall in walls or []:
        try:
            x1 = float(wall.get("x1")); y1 = float(wall.get("y1"))
            x2 = float(wall.get("x2")); y2 = float(wall.get("y2"))
        except (TypeError, ValueError, AttributeError):
            continue
        if x1 == x2 and y1 == y2:
            continue
        rows.append([x1, y1, x2, y2])
    return np.asarray(rows, dtype=float) if rows else np.empty((0, 4))


def _count_crossings_vec(
    px: float, py: float, ex: np.ndarray, ey: np.ndarray, walls: np.ndarray
) -> np.ndarray:
    """Count wall crossings for paths from (px, py) to each (ex[i], ey[i]).

    Uses standard segment-segment intersection in screen coordinates.
    Collinear hits return 0 so a path running along a wall is not
    over-penalised — same convention as the previous shapely impl.

    Returns int array of length ``len(ex)``.
    """
    n_paths = len(ex)
    if walls.size == 0 or n_paths == 0:
        return np.zeros(n_paths, dtype=int)

    # Path endpoints repeated for each wall: shape (n_paths, n_walls)
    n_walls = walls.shape[0]
    p1x = np.full((n_paths, n_walls), px)
    p1y = np.full((n_paths, n_walls), py)
    p2x = np.broadcast_to(ex.reshape(-1, 1), (n_paths, n_walls))
    p2y = np.broadcast_to(ey.reshape(-1, 1), (n_paths, n_walls))
    p3x = np.broadcast_to(walls[:, 0], (n_paths, n_walls))
    p3y = np.broadcast_to(walls[:, 1], (n_paths, n_walls))
    p4x = np.broadcast_to(walls[:, 2], (n_paths, n_walls))
    p4y = np.broadcast_to(walls[:, 3], (n_paths, n_walls))

    d1x = p2x - p1x; d1y = p2y - p1y
    d2x = p4x - p3x; d2y = p4y - p3y
    denom = d1x * d2y - d1y * d2x

    # Collinear (denom == 0) → ignore. Use the parametric form for the rest.
    safe = np.where(np.abs(denom) < 1e-9, 1.0, denom)
    t = ((p3x - p1x) * d2y - (p3y - p1y) * d2x) / safe
    u = ((p3x - p1x) * d1y - (p3y - p1y) * d1x) / safe

    hits = (
        (np.abs(denom) >= 1e-9)
        & (t > 0.0) & (t < 1.0)
        & (u > 0.0) & (u < 1.0)
    )
    return hits.sum(axis=1).astype(int)


def initial_guess_centroid(
    xs: np.ndarray, ys: np.ndarray, rs: np.ndarray
) -> np.ndarray:
    """Weighted centroid (1/r²) - a far better seed than (0, 0)."""
    weights = 1.0 / np.maximum(rs, 1.0) ** 2
    w_sum = float(weights.sum()) or 1.0
    return np.array(
        [float((xs * weights).sum() / w_sum), float((ys * weights).sum() / w_sum)]
    )


def trilaterate_robust(
    samples: Sequence[DistanceSample],
    walls: Iterable[dict] | None = None,
    wall_penalty_px: float = 0.0,
    init: np.ndarray | None = None,
    f_scale_px: float | None = None,
) -> dict | None:
    """Robust weighted nonlinear least-squares trilateration."""
    if len(samples) < 3:
        return None

    walls_arr = _walls_to_array(walls)
    penalty = max(0.0, float(wall_penalty_px))

    xs = np.array([s.x for s in samples], dtype=float)
    ys = np.array([s.y for s in samples], dtype=float)
    rs = np.array([s.radius_px for s in samples], dtype=float)
    sig = np.array([max(s.sigma_px, 1.0) for s in samples], dtype=float)
    weights = 1.0 / sig

    def residuals(p: np.ndarray) -> np.ndarray:
        dx = xs - p[0]
        dy = ys - p[1]
        line = np.sqrt(dx * dx + dy * dy)
        if walls_arr.size and penalty > 0:
            crossings = _count_crossings_vec(
                float(p[0]), float(p[1]), xs, ys, walls_arr
            )
            line = line + crossings * penalty
        return weights * (line - rs)

    p0 = init if init is not None else initial_guess_centroid(xs, ys, rs)
    # f_scale is the residual magnitude considered "normal noise". When the
    # caller knows the floor scale (px/m) it should pass `f_scale_px` so
    # this stays meaningful across very dense and very sparse maps.
    if f_scale_px is not None and f_scale_px > 0:
        f_scale = float(f_scale_px)
    else:
        f_scale = max(2.0, float(np.median(sig)))
    try:
        result = least_squares(
            residuals, p0, loss="soft_l1", f_scale=f_scale, max_nfev=80,
        )
    except Exception as err:  # pragma: no cover - solver pathologies
        _LOGGER.debug("Trilateration solver failed: %s", err)
        return None

    # Second pass: drop the worst residual if it's an obvious outlier
    # (multipath spike). Refit on the cleaned set when we still have ≥3
    # samples.
    raw_residuals = result.fun / weights
    if len(samples) >= 4:
        worst = int(np.argmax(np.abs(raw_residuals)))
        worst_sigmas = abs(raw_residuals[worst]) / max(sig[worst], 1e-3)
        if worst_sigmas > 6.0:
            keep = np.ones(len(samples), dtype=bool)
            keep[worst] = False
            xs2, ys2, rs2, sig2, w2 = (
                xs[keep], ys[keep], rs[keep], sig[keep], weights[keep]
            )

            def residuals2(p: np.ndarray) -> np.ndarray:
                dx = xs2 - p[0]; dy = ys2 - p[1]
                line = np.sqrt(dx * dx + dy * dy)
                if walls_arr.size and penalty > 0:
                    crossings = _count_crossings_vec(
                        float(p[0]), float(p[1]), xs2, ys2, walls_arr
                    )
                    line = line + crossings * penalty
                return w2 * (line - rs2)

            try:
                result = least_squares(
                    residuals2, result.x, loss="soft_l1",
                    f_scale=f_scale, max_nfev=80,
                )
                xs, ys, rs, sig, weights = xs2, ys2, rs2, sig2, w2
            except Exception:  # pragma: no cover
                pass

    pos = result.x
    fun = result.fun

    # Geometric Dilution of Precision (HDOP-equivalent in 2D).
    dx = xs - pos[0]
    dy = ys - pos[1]
    d = np.sqrt(dx * dx + dy * dy)
    d[d < 1e-6] = 1e-6
    H = np.column_stack((-dx / d, -dy / d))
    try:
        cov = np.linalg.inv(H.T @ H)
        hdop = float(math.sqrt(max(float(cov.trace()), 0.0)))
    except np.linalg.LinAlgError:
        hdop = float("inf")

    rms = float(np.sqrt(np.mean(fun * fun)))
    return {
        "x": float(pos[0]),
        "y": float(pos[1]),
        "hdop": hdop,
        "rms_residual_px": rms,
        "max_residual_px": float(np.max(np.abs(fun))),
        "n_used": int(len(xs)),
        "n_rejected": int(len(samples) - len(xs)),
        "converged": bool(result.success),
    }


# ---------------------------------------------------------------------------
# Position Kalman filter (constant velocity)
# ---------------------------------------------------------------------------

class PositionKalman:
    """2D constant-velocity Kalman filter."""

    def __init__(
        self,
        process_noise: float = 4.0,
        reset_after_seconds: float = 30.0,
    ) -> None:
        self.x: np.ndarray | None = None
        self.P: np.ndarray = np.eye(4) * 1e3
        self.q = float(process_noise)
        self.reset_after = float(reset_after_seconds)
        self._last_t: float | None = None

    def reset(self, xy: np.ndarray, t: float) -> None:
        self.x = np.array([xy[0], xy[1], 0.0, 0.0], dtype=float)
        self.P = np.diag([25.0, 25.0, 100.0, 100.0]).astype(float)
        self._last_t = float(t)

    def update(self, xy: np.ndarray, t: float, meas_var: float) -> np.ndarray:
        if self.x is None or self._last_t is None:
            self.reset(xy, t)
            return self.x[:2].copy()

        dt = max(1e-3, float(t) - self._last_t)
        # Re-seed when the target reappears after a long absence — the
        # constant-velocity prior is no longer valid and would drag the
        # smoothed position towards a stale extrapolation.
        if dt > self.reset_after:
            self.reset(xy, t)
            return self.x[:2].copy()
        self._last_t = float(t)

        F = np.array(
            [[1, 0, dt, 0],
             [0, 1, 0, dt],
             [0, 0, 1, 0],
             [0, 0, 0, 1]],
            dtype=float,
        )
        q = self.q
        Q = q * np.array(
            [[dt**4 / 4, 0, dt**3 / 2, 0],
             [0, dt**4 / 4, 0, dt**3 / 2],
             [dt**3 / 2, 0, dt**2,    0],
             [0, dt**3 / 2, 0, dt**2]],
            dtype=float,
        )

        # Predict
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

        # Update
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        R = np.eye(2) * max(1.0, float(meas_var))
        z = np.array([float(xy[0]), float(xy[1])])
        innov = z - H @ self.x
        S = H @ self.P @ H.T + R
        try:
            K = self.P @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            return self.x[:2].copy()
        self.x = self.x + K @ innov
        self.P = (np.eye(4) - K @ H) @ self.P
        return self.x[:2].copy()

    @property
    def velocity(self) -> tuple[float, float]:
        if self.x is None:
            return 0.0, 0.0
        return float(self.x[2]), float(self.x[3])

    @property
    def speed(self) -> float:
        vx, vy = self.velocity
        return math.hypot(vx, vy)

    @property
    def position_variance(self) -> float:
        if self.x is None:
            return float("inf")
        return float(self.P[0, 0] + self.P[1, 1])


# ---------------------------------------------------------------------------
# Stationarity detection + auto-calibration
# ---------------------------------------------------------------------------

class StationarityDetector:
    """Returns the centroid + duration when the target has been still long enough.

    Jitter threshold is expressed in METERS via ``max_jitter_m`` so the
    detector behaves the same on dense maps (100 px/m) and sparse maps
    (1 px/m). The legacy ``max_jitter_px`` argument is still accepted for
    callers that want to override the px figure directly.
    """

    def __init__(
        self,
        window_seconds: float = 12.0,
        max_jitter_m: float = 0.4,
        scale_px_per_m: float = 1.0,
        max_jitter_px: float | None = None,
    ) -> None:
        self.window = float(window_seconds)
        self.scale = max(1e-6, float(scale_px_per_m))
        self.max_jitter_m = float(max_jitter_m)
        if max_jitter_px is not None:
            self.max_jitter = float(max_jitter_px)
        else:
            self.max_jitter = self.max_jitter_m * self.scale
        self._buffer: list[tuple[float, float, float]] = []  # (t, x, y)

    def update_scale(self, scale_px_per_m: float) -> None:
        new_scale = max(1e-6, float(scale_px_per_m))
        if abs(new_scale - self.scale) < 1e-6:
            return
        self.scale = new_scale
        self.max_jitter = self.max_jitter_m * self.scale
        self._buffer.clear()

    def push(self, t: float, x: float, y: float) -> tuple[float, float, float] | None:
        self._buffer.append((float(t), float(x), float(y)))
        cutoff = float(t) - self.window
        self._buffer = [b for b in self._buffer if b[0] >= cutoff]
        if len(self._buffer) < 6:
            return None
        xs = np.array([b[1] for b in self._buffer])
        ys = np.array([b[2] for b in self._buffer])
        if float(xs.std()) > self.max_jitter or float(ys.std()) > self.max_jitter:
            return None
        duration = self._buffer[-1][0] - self._buffer[0][0]
        if duration < self.window * 0.6:
            return None
        return float(xs.mean()), float(ys.mean()), float(duration)

    def reset(self) -> None:
        self._buffer.clear()


class AutoCalibrator:
    """Per-(target, receiver) opportunistic linear calibrator.

    Sample weighting down-weights very-far samples (more multipath, less
    informative). Clamps shared with the JS panel via the module-level
    CAL_* constants so a fit accepted in the UI is also accepted here.
    """

    def __init__(self, max_samples: int = 40, min_samples: int = 5) -> None:
        self.max_samples = int(max_samples)
        self.min_samples = int(min_samples)
        self.samples: list[tuple[float, float]] = []  # (raw_m, true_m)

    def add(self, raw_m: float, true_m: float) -> None:
        if (
            raw_m is None or true_m is None
            or not math.isfinite(raw_m) or not math.isfinite(true_m)
            or raw_m <= 0 or true_m <= 0
        ):
            return
        self.samples.append((float(raw_m), float(true_m)))
        if len(self.samples) > self.max_samples:
            self.samples.pop(0)

    def fit(self) -> dict | None:
        if len(self.samples) < self.min_samples:
            return None
        raw = np.array([s[0] for s in self.samples], dtype=float)
        true = np.array([s[1] for s in self.samples], dtype=float)
        # Down-weight far samples (more multipath, less informative).
        w = 1.0 / np.maximum(raw, 0.5)
        A = np.column_stack((raw * w, w))
        b = true * w
        try:
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            return None
        factor, offset = float(sol[0]), float(sol[1])
        if not (CAL_FACTOR_MIN <= factor <= CAL_FACTOR_MAX):
            return None
        if not (CAL_OFFSET_MIN <= offset <= CAL_OFFSET_MAX):
            return None
        pred = factor * raw + offset
        rmse = float(np.sqrt(np.mean((pred - true) ** 2)))
        return {
            "factor": factor,
            "offset": offset,
            "samples": int(len(self.samples)),
            "rmse_m": rmse,
        }
