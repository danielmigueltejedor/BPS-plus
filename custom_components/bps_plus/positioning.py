"""BPS+ positioning engine.

Self-contained module that provides:
  * Per-link distance smoothing with MAD-based outlier rejection.
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
from shapely.geometry import LineString

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------

def apply_calibration(raw_distance: float, calibration: dict | None) -> float:
    """Apply a path-loss-style correction to a raw distance (meters).

    Model:  corrected = factor * raw**exponent + offset

    Exponent defaults to 1.0 so the formula degenerates to the previous
    affine correction the UI already exposes, while leaving room for
    auto-calibration to fit a non-linear path-loss curve later.
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
# Per-link distance smoother
# ---------------------------------------------------------------------------

class DistanceSmoother:
    """EWMA smoother with MAD-based outlier rejection.

    Replaces the prior ±50% gate, which was simultaneously too lax in
    stable conditions (allowing huge jumps to slip through) and too strict
    when readings legitimately changed quickly. MAD is scale-invariant and
    adapts to each link's noise floor.
    """

    __slots__ = ("alpha", "window", "mad_threshold", "_history", "_ewma", "_var")

    def __init__(
        self,
        alpha: float = 0.4,
        window: int = 8,
        mad_threshold: float = 3.5,
    ) -> None:
        self.alpha = float(alpha)
        self.window = int(window)
        self.mad_threshold = float(mad_threshold)
        self._history: list[float] = []
        self._ewma: float | None = None
        self._var: float = 0.0

    def push(self, value: float) -> tuple[float | None, float, bool]:
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
                delta = value - self._ewma
                self._ewma = self._ewma + self.alpha * delta
                self._var = (1.0 - self.alpha) * (self._var + self.alpha * delta * delta)

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


def _wall_segments(walls: Iterable[dict] | None) -> list[LineString]:
    out: list[LineString] = []
    for wall in walls or []:
        try:
            x1 = float(wall.get("x1")); y1 = float(wall.get("y1"))
            x2 = float(wall.get("x2")); y2 = float(wall.get("y2"))
        except (TypeError, ValueError, AttributeError):
            continue
        if x1 == x2 and y1 == y2:
            continue
        out.append(LineString([(x1, y1), (x2, y2)]))
    return out


def _wall_crossings(path: LineString, segments: Sequence[LineString]) -> int:
    n = 0
    for seg in segments:
        if not path.intersects(seg):
            continue
        inter = path.intersection(seg)
        if inter.is_empty:
            continue
        if inter.geom_type in ("LineString", "MultiLineString"):
            # Path collinear with a wall -> ignore to avoid over-penalizing.
            continue
        n += 1
    return n


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
) -> dict | None:
    """Robust weighted nonlinear least-squares trilateration.

    - Weights each residual by 1 / sigma_px so noisy/distant receivers
      contribute less.
    - Uses a soft-L1 loss to suppress remaining outliers (multipath spikes).
    - Adds wall_penalty_px per wall crossed along the line of sight.

    Returns None when fewer than 3 samples are supplied or the solver
    diverges. Otherwise returns a dict with the fitted position and a set
    of quality metrics.
    """
    if len(samples) < 3:
        return None

    segs = _wall_segments(walls)
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
        if segs and penalty > 0:
            extra = np.empty(len(samples))
            for i in range(len(samples)):
                path = LineString([(p[0], p[1]), (xs[i], ys[i])])
                extra[i] = _wall_crossings(path, segs)
            line = line + extra * penalty
        return weights * (line - rs)

    p0 = init if init is not None else initial_guess_centroid(xs, ys, rs)
    # f_scale is the residual magnitude considered "normal noise". Set it
    # to roughly the median per-link noise so soft_l1 compresses anything
    # several sigmas above the noise floor.
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
    # samples. This is the classic "RANSAC-lite" trick that works well
    # with weighted nonlinear least squares.
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
                if segs and penalty > 0:
                    extra = np.empty(len(xs2))
                    for i in range(len(xs2)):
                        path = LineString([(p[0], p[1]), (xs2[i], ys2[i])])
                        extra[i] = _wall_crossings(path, segs)
                    line = line + extra * penalty
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
    """2D constant-velocity Kalman filter.

    State: [x, y, vx, vy].  Measurement noise R is derived from HDOP × the
    trilateration residual scale, so the filter automatically tightens when
    geometry is good and loosens when it's bad.
    """

    def __init__(self, process_noise: float = 4.0) -> None:
        self.x: np.ndarray | None = None
        self.P: np.ndarray = np.eye(4) * 1e3
        self.q = float(process_noise)
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
        if dt > 30.0:
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
    """Returns the centroid + duration when the target has been still long enough."""

    def __init__(self, window_seconds: float = 12.0, max_jitter_px: float = 8.0) -> None:
        self.window = float(window_seconds)
        self.max_jitter = float(max_jitter_px)
        self._buffer: list[tuple[float, float, float]] = []  # (t, x, y)

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

    When the target is detected as stationary at position P, the true
    distance to a receiver R is |P - R|. Pair this with the raw distance
    reported by that receiver to build training samples. After enough
    samples, fit `true = factor * raw + offset` by weighted least squares.
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
        # Reject pathological fits to avoid corrupting good calibrations.
        if not (0.2 <= factor <= 5.0):
            return None
        if not (-5.0 <= offset <= 5.0):
            return None
        pred = factor * raw + offset
        rmse = float(np.sqrt(np.mean((pred - true) ** 2)))
        return {
            "factor": factor,
            "offset": offset,
            "samples": int(len(self.samples)),
            "rmse_m": rmse,
        }
