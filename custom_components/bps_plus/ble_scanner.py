"""BPS-Plus native BLE distance engine.

Subscribes to every BLE advertisement HA's bluetooth integration sees
(local adapters + ESPHome / Shelly bluetooth proxies) and turns each
(device, proxy) pair into a distance estimate using the log-distance
path-loss model:

    rssi(d) = tx_power - 10 * n * log10(d)

so:

    d = 10^((tx_power - rssi) / (10 * n))

Both `tx_power` (calibrated RSSI at 1 m) and `n` (path-loss exponent)
are fitted online per-link by the BPS positioning engine: when a target
is detected as stationary, its (smoothed) position is the ground truth
and the true distance to each proxy is `|pos - proxy|`. Pairing that
with the observed RSSI gives a training sample we feed back here.

Result: BPS-Plus no longer needs Bermuda or any external integration to
compute distances — it owns the full BLE → distance → trilateration
pipeline.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field

import numpy as np

_LOGGER = logging.getLogger(__name__)


DEFAULT_TX_POWER = -59.0   # typical iBeacon RSSI at 1 m
DEFAULT_PATH_LOSS = 2.5    # indoor mixed environment
STALE_AFTER = 30.0         # seconds after which a link is considered dead
MIN_FIT_SAMPLES = 5
MAX_FIT_SAMPLES = 60


def normalize_mac(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper().replace("-", ":").replace("_", ":")
    if re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", s):
        return s
    compact = re.sub(r"[^0-9A-F]", "", s)
    if re.fullmatch(r"[0-9A-F]{12}", compact):
        return ":".join(compact[i : i + 2] for i in range(0, 12, 2))
    return None


def mac_to_token(mac: str | None) -> str:
    if not mac:
        return ""
    return mac.lower().replace(":", "_")


def slugify(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def rssi_to_distance(rssi: float, tx_power: float, n: float) -> float:
    if rssi is None or not math.isfinite(rssi) or rssi >= 0:
        return float("inf")
    if n <= 0:
        return float("inf")
    return math.pow(10.0, (tx_power - rssi) / (10.0 * n))


@dataclass
class LinkState:
    """Per-(device, scanner) running state."""
    rssi_ewma: float | None = None
    last_rssi: float | None = None
    last_seen: float = 0.0
    tx_power: float = DEFAULT_TX_POWER
    path_loss: float = DEFAULT_PATH_LOSS
    samples: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class DeviceMeta:
    """One trackable BLE identity.

    `identity` is what BPS uses everywhere as the dict key — for raw
    devices that's the MAC, for IRK-resolved devices (private_ble_device)
    it's the stable token. `current_mac` is the live rotating MAC used
    only for display.
    """
    identity: str
    name: str = ""
    current_mac: str | None = None
    tx_power_adv: float | None = None
    last_seen: float = 0.0

    @property
    def address(self) -> str:
        """Backwards-compatible alias for the displayable address."""
        return self.current_mac or self.identity


@dataclass
class ScannerMeta:
    source: str
    name: str = ""
    last_seen: float = 0.0


class BleScanner:
    """Owns the live BLE picture and the per-link distance estimates."""

    def __init__(self, hass, ewma_alpha: float = 0.35) -> None:
        self.hass = hass
        self.alpha = float(ewma_alpha)
        self.devices: dict[str, DeviceMeta] = {}
        self.scanners: dict[str, ScannerMeta] = {}
        self.links: dict[tuple[str, str], LinkState] = {}
        self._unsub = None
        self._name_cache: dict[str, str] = {}
        self._receiver_resolution: dict[str, str | None] = {}
        # Maps a (rotating) device MAC to a stable identity supplied by an
        # external resolver (e.g. private_ble_device's IRK matching). When
        # set, advertisements arriving under the MAC are stored under the
        # alias instead, so calibration and link history survive rotations.
        self._aliases: dict[str, str] = {}

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        try:
            from homeassistant.components import bluetooth
        except ImportError:
            _LOGGER.warning("HA bluetooth integration unavailable - native BLE engine disabled")
            return False

        try:
            mode = bluetooth.BluetoothScanningMode.PASSIVE
        except AttributeError:
            mode = None

        try:
            if mode is not None:
                self._unsub = bluetooth.async_register_callback(
                    self.hass, self._on_adv, {"connectable": False}, mode,
                )
            else:
                self._unsub = bluetooth.async_register_callback(
                    self.hass, self._on_adv, {"connectable": False},
                )
        except Exception as err:
            _LOGGER.error("Failed to subscribe to bluetooth advertisements: %s", err)
            return False

        _LOGGER.info("BPS-Plus native BLE scanner active")
        return True

    def stop(self) -> None:
        if self._unsub:
            try:
                self._unsub()
            except Exception:
                pass
            self._unsub = None

    # -- Advertisement handling --------------------------------------------

    def _on_adv(self, service_info, _change) -> None:
        try:
            mac = normalize_mac(getattr(service_info, "address", None))
            if mac is None:
                return
            source_raw = getattr(service_info, "source", None)
            if not source_raw:
                return
            source = str(source_raw).upper()
            rssi = getattr(service_info, "rssi", None)
            if rssi is None or not math.isfinite(rssi):
                return
            now = time.monotonic()

            identity = self._aliases.get(mac, mac)

            meta = self.devices.get(identity)
            if meta is None:
                meta = DeviceMeta(identity=identity, current_mac=mac)
                self.devices[identity] = meta
            meta.current_mac = mac
            adv_name = getattr(service_info, "name", None)
            if adv_name and adv_name != mac:
                meta.name = str(adv_name)
            if not meta.name:
                meta.name = identity
            tx_adv = getattr(service_info, "tx_power", None)
            if tx_adv is not None and -127 <= tx_adv <= 20:
                meta.tx_power_adv = float(tx_adv)
            meta.last_seen = now

            scanner_meta = self.scanners.get(source)
            if scanner_meta is None:
                scanner_meta = ScannerMeta(
                    source=source, name=self._resolve_scanner_name(source),
                )
                self.scanners[source] = scanner_meta
            scanner_meta.last_seen = now

            key = (identity, source)
            link = self.links.get(key)
            if link is None:
                link = LinkState(
                    tx_power=meta.tx_power_adv if meta.tx_power_adv is not None
                    else DEFAULT_TX_POWER,
                )
                self.links[key] = link
            r = float(rssi)
            link.last_rssi = r
            if link.rssi_ewma is None:
                link.rssi_ewma = r
            else:
                link.rssi_ewma = (1 - self.alpha) * link.rssi_ewma + self.alpha * r
            link.last_seen = now
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("BLE adv handler error: %s", err)

    def set_alias(self, mac: str, alias_id: str) -> None:
        """Bind a rotating MAC to a stable identity (e.g. an IRK token).

        After this call, advertisements arriving under `mac` are stored
        under `alias_id`. Any existing per-link calibration captured under
        `mac` is migrated to the alias so a rotation doesn't reset the
        path-loss fit.
        """
        mac_norm = normalize_mac(mac)
        if not mac_norm or not alias_id:
            return
        if self._aliases.get(mac_norm) == alias_id:
            return
        self._aliases[mac_norm] = alias_id

        # Migrate link state captured under the raw MAC.
        keys_to_migrate = [k for k in list(self.links) if k[0] == mac_norm]
        for key in keys_to_migrate:
            new_key = (alias_id, key[1])
            link = self.links.pop(key)
            existing = self.links.get(new_key)
            if existing is None:
                self.links[new_key] = link
            else:
                # Aliased link already has fitted calibration; keep it but
                # pull in the latest RSSI/timestamp from the migrating one.
                if link.last_seen > existing.last_seen:
                    existing.last_rssi = link.last_rssi
                    existing.rssi_ewma = link.rssi_ewma
                    existing.last_seen = link.last_seen

        # Migrate device meta.
        if mac_norm in self.devices:
            raw_meta = self.devices.pop(mac_norm)
            existing_meta = self.devices.get(alias_id)
            if existing_meta is None:
                raw_meta.identity = alias_id
                if not raw_meta.current_mac:
                    raw_meta.current_mac = mac_norm
                self.devices[alias_id] = raw_meta
            else:
                existing_meta.current_mac = mac_norm
                if raw_meta.last_seen > existing_meta.last_seen:
                    existing_meta.last_seen = raw_meta.last_seen
                if raw_meta.tx_power_adv is not None:
                    existing_meta.tx_power_adv = raw_meta.tx_power_adv

    def _resolve_scanner_name(self, source: str) -> str:
        if source in self._name_cache:
            return self._name_cache[source]
        name = source
        # Try the bluetooth scanner registry first.
        try:
            from homeassistant.components import bluetooth
            if hasattr(bluetooth, "async_scanner_by_source"):
                scanner = bluetooth.async_scanner_by_source(self.hass, source)
                if scanner is not None and getattr(scanner, "name", None):
                    name = str(scanner.name)
        except Exception:
            pass
        # Fall back to the device registry by MAC connection.
        if name == source:
            try:
                from homeassistant.helpers import device_registry as dr
                reg = dr.async_get(self.hass)
                mac_lower = source.lower()
                for dev in reg.devices.values():
                    matched = False
                    for conn_type, conn_id in dev.connections:
                        if conn_id and conn_id.lower() == mac_lower:
                            candidate = dev.name_by_user or dev.name
                            if candidate:
                                name = str(candidate)
                                matched = True
                                break
                    if matched:
                        break
            except Exception:
                pass
        self._name_cache[source] = name
        return name

    # -- Public read API ----------------------------------------------------

    def known_devices(self, max_age: float = STALE_AFTER) -> list[DeviceMeta]:
        now = time.monotonic()
        return sorted(
            (m for m in self.devices.values() if now - m.last_seen < max_age),
            key=lambda m: (m.name or m.address).lower(),
        )

    def known_scanners(self) -> list[ScannerMeta]:
        return sorted(
            self.scanners.values(),
            key=lambda s: (s.name or s.source).lower(),
        )

    def candidate_targets(
        self, min_scanners: int = 3, max_age: float = STALE_AFTER
    ) -> list[str]:
        """MACs currently observed by at least N scanners."""
        now = time.monotonic()
        per_dev: dict[str, set[str]] = {}
        for (mac, source), link in self.links.items():
            if now - link.last_seen > max_age:
                continue
            per_dev.setdefault(mac, set()).add(source)
        return [m for m, srcs in per_dev.items() if len(srcs) >= min_scanners]

    def resolve_receiver(self, receiver_id: str) -> str | None:
        """Map a user-supplied receiver id to a known scanner source.

        Accepts MAC, MAC slug (`aa_bb_cc_..`), proxy device slug, or a
        partial match against the scanner friendly name.
        """
        if not receiver_id:
            return None
        if receiver_id in self._receiver_resolution:
            return self._receiver_resolution[receiver_id]

        candidates = list(self.scanners.keys())
        # 1. Direct MAC match
        mac = normalize_mac(receiver_id)
        if mac and mac in self.scanners:
            self._receiver_resolution[receiver_id] = mac
            return mac

        target_slug = slugify(receiver_id)
        if not target_slug:
            self._receiver_resolution[receiver_id] = None
            return None

        # 2. Slug match against scanner friendly name or source MAC slug
        for source in candidates:
            scanner = self.scanners[source]
            if slugify(scanner.name) == target_slug:
                self._receiver_resolution[receiver_id] = source
                return source
            if slugify(source) == target_slug:
                self._receiver_resolution[receiver_id] = source
                return source

        # 3. Partial match (target slug appears in scanner name slug)
        for source in candidates:
            name_slug = slugify(self.scanners[source].name)
            if name_slug and (target_slug in name_slug or name_slug in target_slug):
                self._receiver_resolution[receiver_id] = source
                return source

        self._receiver_resolution[receiver_id] = None
        return None

    def invalidate_receiver_cache(self) -> None:
        self._receiver_resolution.clear()

    @staticmethod
    def _identity_key(value: str) -> str:
        mac = normalize_mac(value)
        return mac if mac is not None else str(value)

    def get_distance(
        self, identity: str, source: str, max_age: float = STALE_AFTER
    ) -> dict | None:
        link = self.links.get((self._identity_key(identity), source.upper()))
        if link is None or link.rssi_ewma is None:
            return None
        if time.monotonic() - link.last_seen > max_age:
            return None
        d = rssi_to_distance(link.rssi_ewma, link.tx_power, link.path_loss)
        if not math.isfinite(d):
            return None
        return {
            "distance_m": d,
            "rssi": link.rssi_ewma,
            "tx_power": link.tx_power,
            "path_loss": link.path_loss,
            "samples": len(link.samples),
            "age_s": time.monotonic() - link.last_seen,
        }

    # -- Calibration --------------------------------------------------------

    def add_calibration_sample(
        self, identity: str, source: str, true_distance_m: float
    ) -> None:
        link = self.links.get((self._identity_key(identity), source.upper()))
        if link is None or link.rssi_ewma is None:
            return
        if true_distance_m <= 0.05 or not math.isfinite(true_distance_m):
            return
        link.samples.append((float(link.rssi_ewma), float(true_distance_m)))
        if len(link.samples) > MAX_FIT_SAMPLES:
            link.samples.pop(0)
        self._fit_path_loss(link)

    @staticmethod
    def _fit_path_loss(link: LinkState) -> None:
        """Refit (tx_power, n) from accumulated (rssi, true_distance) samples."""
        usable = [(r, d) for r, d in link.samples if d > 0.1]
        if len(usable) < MIN_FIT_SAMPLES:
            return
        rssi = np.array([x[0] for x in usable], dtype=float)
        log_d = np.log10(np.array([x[1] for x in usable], dtype=float))
        # Model: rssi = a + b * log10(d), with a = tx_power, b = -10*n
        A = np.column_stack((np.ones_like(rssi), log_d))
        try:
            sol, *_ = np.linalg.lstsq(A, rssi, rcond=None)
        except np.linalg.LinAlgError:
            return
        tx_power = float(sol[0])
        n = -float(sol[1]) / 10.0
        # Sanity bounds — reject pathological fits.
        if not (-95.0 <= tx_power <= -25.0):
            return
        if not (1.5 <= n <= 5.0):
            return
        link.tx_power = tx_power
        link.path_loss = n

    # -- Diagnostics --------------------------------------------------------

    def snapshot(self) -> dict:
        now = time.monotonic()
        devs = []
        for mac, meta in self.devices.items():
            n_scanners = sum(
                1 for (m, _src), l in self.links.items()
                if m == mac and now - l.last_seen < STALE_AFTER
            )
            devs.append({
                "address": mac,
                "token": mac_to_token(mac),
                "name": meta.name,
                "age_s": round(now - meta.last_seen, 1),
                "tx_power_adv": meta.tx_power_adv,
                "scanners_seen": n_scanners,
            })
        scs = []
        for src, meta in self.scanners.items():
            scs.append({
                "source": src,
                "name": meta.name,
                "age_s": round(now - meta.last_seen, 1),
            })
        links = []
        for (mac, src), link in self.links.items():
            if now - link.last_seen > STALE_AFTER:
                continue
            d = rssi_to_distance(link.rssi_ewma, link.tx_power, link.path_loss)
            links.append({
                "device": mac,
                "scanner": src,
                "rssi": round(link.rssi_ewma, 1) if link.rssi_ewma is not None else None,
                "distance_m": round(d, 2) if math.isfinite(d) else None,
                "tx_power": round(link.tx_power, 1),
                "path_loss": round(link.path_loss, 2),
                "samples": len(link.samples),
            })
        return {
            "devices": devs,
            "scanners": scs,
            "links": links,
        }
