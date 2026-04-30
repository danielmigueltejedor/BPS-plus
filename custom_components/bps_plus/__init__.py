from __future__ import annotations

import logging
import asyncio
import math
import os
import json
import re
import time
from pathlib import Path
from asyncio import Lock, Queue, wait_for, TimeoutError

import aiofiles
import aiofiles.os
import numpy as np
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.websocket_api import (
    async_register_command,
    ActiveConnection,
    websocket_command,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from shapely.geometry import Point, Polygon
import voluptuous as vol

from .positioning import (
    AutoCalibrator,
    DistanceSample,
    DistanceSmoother,
    PositionKalman,
    StationarityDetector,
    apply_calibration,
    trilaterate_robust,
)
from .ble_scanner import (
    BleScanner,
    mac_to_token,
    normalize_mac as scanner_normalize_mac,
    slugify as scanner_slugify,
)
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:  # pragma: no cover - depends on HA runtime env
    Observer = None
    FileSystemEventHandler = object

from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    CONF_BASE_URL,
    CONF_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

FRONTEND_PATH = Path(__file__).parent / "frontend"

# Global data
global_data = []
state_change_lock = Lock()
state_change_counter = {}
update_queue = Queue()
tracked_listeners = {}
tracked_entities = []
new_global_data = {}
secToUpdate = 1
apitricords = []


def cache_discovery_data(
    hass: HomeAssistant,
    canonical_map: dict[str, dict[str, str]],
    entity_options: list[dict[str, str]],
    target_metadata: dict[str, dict[str, str]],
) -> None:
    """Cache BLE discovery data so other platforms (sensor) can consume it."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["distance_entity_map"] = canonical_map
    hass.data[DOMAIN]["entity_options"] = entity_options
    hass.data[DOMAIN]["target_metadata"] = target_metadata


def normalize_mac(value: str | None) -> str | None:
    """Normalize MAC-like value to AA:BB:CC:DD:EE:FF."""
    if not value:
        return None
    candidate = value.strip().upper().replace("-", ":").replace("_", ":")
    if re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", candidate):
        return candidate
    compact = re.sub(r"[^0-9A-F]", "", candidate)
    if re.fullmatch(r"[0-9A-F]{12}", compact):
        return ":".join(compact[i : i + 2] for i in range(0, 12, 2))
    return None


def mac_to_entity_token(mac: str) -> str:
    """Convert AA:BB:CC:DD:EE:FF -> aa_bb_cc_dd_ee_ff for entity-safe ids."""
    return mac.lower().replace(":", "_")


def build_bluetooth_alias_maps(hass: HomeAssistant):
    """Build maps for private BLE addresses -> stable address/friendly name."""
    current_to_source: dict[str, str] = {}
    target_metadata: dict[str, dict[str, str]] = {}

    for state in hass.states.async_all():
        attrs = state.attributes
        if attrs.get("source_type") != "bluetooth_le":
            continue

        current_address = normalize_mac(attrs.get("current_address"))
        source_address = normalize_mac(attrs.get("source"))
        friendly_name = attrs.get("friendly_name") or state.name or state.entity_id

        if not current_address:
            continue

        stable_address = source_address or current_address
        current_to_source[current_address] = stable_address

        stable_token = mac_to_entity_token(stable_address)
        target_metadata[stable_token] = {
            "friendly_name": str(friendly_name),
            "stable_address": stable_address,
            "current_address": current_address,
        }

    return current_to_source, target_metadata


def canonical_target_token(raw_target: str, current_to_source: dict[str, str]) -> str:
    """Convert raw _distance_to_ target token to stable token when possible."""
    maybe_mac = normalize_mac(raw_target)
    if maybe_mac:
        stable = current_to_source.get(maybe_mac, maybe_mac)
        return mac_to_entity_token(stable)
    return raw_target


def collapse_repeated_target(target: str) -> str:
    """Collapse recursively repeated targets: a_b_a_b -> a_b."""
    current = target
    while True:
        parts = current.split("_")
        if len(parts) < 2 or len(parts) % 2 != 0:
            return current
        half = len(parts) // 2
        if parts[:half] != parts[half:]:
            return current
        current = "_".join(parts[:half])


def extract_distance_entity_parts(entity_id: str) -> tuple[str, str] | None:
    """Return (target, receiver) from sensor.target_distance_to_receiver."""
    cleaned = entity_id.replace("sensor.", "", 1)
    if "_distance_to_" not in cleaned:
        return None
    target, receiver = cleaned.split("_distance_to_", 1)
    if not target or not receiver:
        return None
    return target, receiver


def get_scanner(hass: HomeAssistant) -> BleScanner | None:
    return hass.data.get(DOMAIN, {}).get("scanner")


_MAC_TOKEN_RE = re.compile(r"^[0-9a-f]{2}(_[0-9a-f]{2}){5}$")


def _resolve_target_identity(hass: HomeAssistant, entity_token: str) -> str | None:
    """Map a target token to the identity used inside the BLE scanner.

    Stable tokens (private_ble_device-style) are returned verbatim — the
    scanner stores their links under the alias. Raw MAC slugs are
    converted back to canonical `AA:BB:CC:..` form.
    """
    if not entity_token:
        return None
    meta = hass.data.get(DOMAIN, {}).get("target_metadata", {}).get(entity_token)
    if meta and meta.get("is_alias"):
        return entity_token
    if _MAC_TOKEN_RE.match(entity_token):
        return scanner_normalize_mac(entity_token.replace("_", ":"))
    # Last resort: assume alias.
    return entity_token


def _collect_stable_ble_targets(hass: HomeAssistant) -> dict[str, dict]:
    """Read IRK-resolved identities exposed by `private_ble_device` (etc).

    Any HA entity reporting `source_type: bluetooth_le` plus a
    `current_address` attribute counts. We dedupe by current MAC and
    prefer `device_tracker.*` entities so the chosen token survives even
    when sibling sensors come and go.
    """
    candidates: list = []
    for state in hass.states.async_all():
        attrs = state.attributes
        if attrs.get("source_type") != "bluetooth_le":
            continue
        current = scanner_normalize_mac(attrs.get("current_address"))
        if current is None:
            continue
        candidates.append((state, current))

    by_mac: dict[str, object] = {}
    for state, mac in candidates:
        existing = by_mac.get(mac)
        if existing is None:
            by_mac[mac] = state
            continue
        existing_pref = existing.entity_id.startswith("device_tracker.")
        new_pref = state.entity_id.startswith("device_tracker.")
        if new_pref and not existing_pref:
            by_mac[mac] = state

    targets: dict[str, dict] = {}
    for mac, state in by_mac.items():
        attrs = state.attributes
        token_raw = state.entity_id.split(".", 1)[-1]
        token = re.sub(r"[^a-z0-9]+", "_", token_raw.lower()).strip("_")
        if not token:
            continue
        friendly = attrs.get("friendly_name") or state.name or token
        targets[token] = {
            "friendly_name": str(friendly),
            "current_address": mac,
        }
    return targets


def discover_distance_entities(hass: HomeAssistant):
    """Native discovery from the BLE scanner + private_ble_device.

    Returns `(canonical_map, entity_options, target_metadata)`. Stable
    targets (IRK-resolved by `private_ble_device`) take precedence so
    iPhones and Apple Watches remain trackable across MAC rotations.
    Anything else seen by the scanner shows up as a raw MAC entry.
    """
    scanner = get_scanner(hass)
    canonical_map: dict[str, dict[str, str]] = {}
    target_metadata: dict[str, dict[str, str]] = {}
    entity_options: list[dict[str, str]] = []

    if scanner is None:
        return canonical_map, entity_options, target_metadata

    scanners_list = scanner.known_scanners()

    # Receiver-id table built once per discovery. Prefers the friendly
    # slug from the proxy's device-registry name (e.g. `bluetooth_proxy_cocina`)
    # over the bare MAC slug so user-facing entity names read
    # "Distance to bluetooth_proxy_cocina" instead of "Distance to b4_e6_2d_..".
    # Keep a parallel friendly-name map for the sensor display layer.
    receiver_id_table: list[tuple[str, str]] = []
    receiver_friendly: dict[str, str] = {}
    for sc in scanners_list:
        friendly_slug = scanner_slugify(sc.name) if sc.name else ""
        receiver_id = (
            friendly_slug
            or mac_to_token(sc.source)
            or sc.source.lower().replace(":", "_")
        )
        receiver_id_table.append((receiver_id, sc.source))
        receiver_friendly[receiver_id] = sc.name or sc.source

    hass.data.setdefault(DOMAIN, {})["receiver_friendly_names"] = receiver_friendly

    def _build_receiver_map(token: str) -> dict[str, str]:
        return {
            receiver_id: f"sensor.bps_{token}_distance_to_{receiver_id}"
            for receiver_id, _src in receiver_id_table
        }

    # Stable / IRK-resolved targets first. Push the alias into the
    # scanner so calibration survives MAC rotations.
    stable_targets = _collect_stable_ble_targets(hass)
    used_macs: set[str] = set()
    for token, meta in stable_targets.items():
        scanner.set_alias(meta["current_address"], token)
        target_metadata[token] = {
            "friendly_name": meta["friendly_name"],
            "stable_address": token,
            "current_address": meta["current_address"],
            "is_alias": True,
        }
        canonical_map[token] = _build_receiver_map(token)
        used_macs.add(meta["current_address"])

    # Raw devices the scanner sees that aren't already covered above.
    # Be picky on purpose: BLE is a noisy sea (random Apple chaff,
    # rotating beacons, neighbours' devices...). Only surface raw devices
    # that broadcast a useful name AND are visible to >=3 proxies right
    # now. Stable targets above are exempt — the user has explicitly
    # paired them via private_ble_device.
    candidate_macs = set(scanner.candidate_targets(min_scanners=3))
    for dev in scanner.known_devices():
        if dev.identity in canonical_map:
            continue
        if dev.current_mac and dev.current_mac in used_macs:
            continue
        normalised = scanner_normalize_mac(dev.identity)
        if normalised is None:
            # Aliased identity that wasn't registered as a stable target
            # this tick — skip; it will reappear once private_ble_device
            # publishes its current_address again.
            continue
        if normalised not in candidate_macs:
            continue
        adv_name = (dev.name or "").strip()
        if not adv_name or adv_name == dev.address or scanner_normalize_mac(adv_name) is not None:
            # No real advertising name — drop. We do not want to spam
            # HA's entity registry with `Distance to aa_bb_cc_..` rows.
            continue
        token = mac_to_token(normalised)
        target_metadata[token] = {
            "friendly_name": adv_name,
            "stable_address": normalised,
            "current_address": normalised,
            "is_alias": False,
        }
        canonical_map[token] = _build_receiver_map(token)

    for target_id in sorted(canonical_map):
        meta = target_metadata.get(target_id, {})
        entity_options.append({
            "id": target_id,
            "name": meta.get("friendly_name", target_id),
        })

    return canonical_map, entity_options, target_metadata


def find_managed_distance_state(
    hass: HomeAssistant, target_id: str, receiver_id: str
):
    """Find BPS-managed distance sensor state for target/receiver pair."""
    for state in hass.states.async_all():
        if not state.entity_id.startswith("sensor."):
            continue
        attrs = state.attributes
        if attrs.get("managed_by") != DOMAIN:
            continue
        if (
            attrs.get("target_id") == target_id
            and attrs.get("receiver_id") == receiver_id
        ):
            return state
    return None


class FileWatcher(FileSystemEventHandler):
    """A class to handle file changes"""

    def __init__(self, file_path, callback, hass: HomeAssistant):
        self.file_path = file_path
        self.callback = callback
        self.hass = hass  # Reference to the Home Assistant instance

    def on_modified(self, event):
        """Called when the file changes"""
        if event.src_path == self.file_path:
            asyncio.run_coroutine_threadsafe(self.callback(), self.hass.loop)


async def read_file(file_path):
    """Read data asynchronously from the file"""
    try:
        async with aiofiles.open(file_path, mode="r") as file:
            content = await file.read()
        return content
    except FileNotFoundError:
        _LOGGER.warning("File not found: %s", file_path)
        return ""
    except Exception as e:
        _LOGGER.error("Error reading file %s: %s", file_path, e)
        return ""


def setup_file_watcher(file_path, update_callback, hass: HomeAssistant):
    """Set up a file watcher to monitor changes"""
    if Observer is None:
        _LOGGER.warning(
            "watchdog is not available. File watcher disabled for %s",
            file_path,
        )
        return None
    event_handler = FileWatcher(file_path, update_callback, hass)
    observer = Observer()
    observer.schedule(event_handler, os.path.dirname(file_path), recursive=False)
    observer.start()
    return observer


async def update_global_data(file_path):
    """Update global_data with the contents of the file"""
    global global_data
    new_data = await read_file(file_path)
    try:
        global_data = json.loads(new_data) if new_data else []
        _LOGGER.info("Updated global_data: %s", global_data)
    except json.JSONDecodeError as e:
        _LOGGER.error("Error parsing JSON data: %s", e)


async def update_tracked_entities(hass, _unused=None):
    """Drive the positioning loop using the native BLE scanner."""
    global tracked_entities, new_global_data, secToUpdate
    while True:
        try:
            scanner = get_scanner(hass)
            if scanner is None:
                _LOGGER.warning("BLE scanner not initialised yet, retry in 5 s")
                await asyncio.sleep(5)
                continue

            # Discovery + alias setup MUST run every tick before checking
            # candidates. Otherwise rotating-MAC devices (Apple Watch,
            # iPhones via private_ble_device) never get aliased to a
            # stable identity, their advertisements stay scattered across
            # short-lived MACs and they never accumulate >=3 scanner
            # sightings — chicken-and-egg.
            canonical_map, entity_options, target_metadata = discover_distance_entities(hass)
            cache_discovery_data(hass, canonical_map, entity_options, target_metadata)

            candidates = scanner.candidate_targets(min_scanners=3)
            tracked_entities = candidates

            if len(candidates) < 1:
                _LOGGER.debug(
                    "No BLE devices currently visible to >=3 proxies "
                    "(known devices=%d, scanners=%d, stable aliases=%d)",
                    len(scanner.devices),
                    len(scanner.scanners),
                    sum(1 for k in target_metadata.values() if k.get("is_alias")),
                )
                await asyncio.sleep(5)
                continue

            candidate_set = set(candidates)
            new_global_data = [
                {
                    "entity": ent,
                    "data": global_data,
                    "receiver_state_map": receiver_map,
                }
                for ent, receiver_map in canonical_map.items()
                # Only run the engine for devices we can actually trilaterate.
                if _resolve_target_identity(hass, ent) in candidate_set
            ]

            await process_entities(hass, new_global_data)

        except Exception as e:
            _LOGGER.exception("Positioning loop iteration failed: %s", e)

        await asyncio.sleep(secToUpdate)


# Per-entity engine state: smoothers, Kalman, stationarity, autocal.
_engine_state: dict[str, dict] = {}


def _get_engine_state(entity: str) -> dict:
    state = _engine_state.get(entity)
    if state is None:
        state = {
            "smoothers": {},          # smoother_key -> DistanceSmoother
            "kalman": PositionKalman(),
            "stationary": StationarityDetector(),
            "autocal": {},            # receiver_id -> AutoCalibrator
            "last_fits": {},          # receiver_id -> latest fit dict
            "quality": {},            # latest position quality summary
        }
        _engine_state[entity] = state
    return state


def _build_floor_buckets(hass, eids, engine):
    """Per-floor buckets fed by the native BLE scanner.

    Distances now come straight from RSSI via the log-distance model
    inside `BleScanner.get_distance()`. Each receiver in the saved map is
    resolved to a live scanner source (proxy MAC) by friendly-name slug
    or MAC, so existing maps with `bluetooth_proxy_cocina`-style ids keep
    working.
    """
    scanner = get_scanner(hass)
    if scanner is None:
        return {}

    target_identity = _resolve_target_identity(hass, eids["entity"])
    if not target_identity:
        return {}

    smoothers = engine["smoothers"]
    receiver_sources: dict[str, str] = engine.setdefault("receiver_sources", {})
    buckets: dict[str, dict] = {}

    for floor in eids["data"].get("floor", []):
        scale_raw = floor.get("scale")
        if scale_raw is None:
            continue
        try:
            scale = float(scale_raw)
        except (TypeError, ValueError):
            continue
        if scale <= 0:
            continue

        try:
            wall_penalty_m = float(floor.get("wall_penalty", 2.5))
        except (TypeError, ValueError):
            wall_penalty_m = 2.5
        wall_penalty_px = max(0.0, wall_penalty_m * scale)

        floor_name = floor.get("name") or "_"
        samples: list[DistanceSample] = []
        sample_sources: dict[str, str] = {}

        for receiver in floor.get("receivers", []):
            cords = receiver.get("cords") or {}
            try:
                rx = float(cords.get("x"))
                ry = float(cords.get("y"))
            except (TypeError, ValueError):
                continue

            receiver_id = receiver["entity_id"]
            source = receiver_sources.get(receiver_id)
            if source is None:
                source = scanner.resolve_receiver(receiver_id)
                if source is not None:
                    receiver_sources[receiver_id] = source
            if source is None:
                continue

            reading = scanner.get_distance(target_identity, source)
            if reading is None:
                continue
            raw_m = float(reading["distance_m"])
            if not math.isfinite(raw_m) or raw_m <= 0:
                continue

            corrected_m = apply_calibration(raw_m, receiver.get("calibration"))
            smoother_key = f"{floor_name}::{receiver_id}"
            smoother = smoothers.setdefault(smoother_key, DistanceSmoother())
            smoothed_m, sigma_m, _accepted = smoother.push(corrected_m)
            if smoothed_m is None or smoothed_m <= 0:
                continue

            radius_px = smoothed_m * scale
            sigma_px = max(2.0, sigma_m * scale)
            samples.append(
                DistanceSample(
                    receiver_id=receiver_id,
                    x=rx,
                    y=ry,
                    raw_distance_m=raw_m,
                    distance_m=smoothed_m,
                    radius_px=radius_px,
                    sigma_px=sigma_px,
                )
            )
            cords["r"] = radius_px
            sample_sources[receiver_id] = source

        if samples:
            buckets[floor_name] = {
                "samples": samples,
                "sources": sample_sources,
                "walls": floor.get("walls", []),
                "wall_penalty_px": wall_penalty_px,
                "scale": scale,
                "target_identity": target_identity,
            }

    return buckets


def _select_active_floor(buckets: dict[str, dict]) -> str | None:
    best_name = None
    best_min_r = float("inf")
    for name, bucket in buckets.items():
        min_r = min(s.radius_px for s in bucket["samples"])
        if min_r < best_min_r:
            best_min_r = min_r
            best_name = name
    return best_name


def _hdop_to_quality(hdop: float) -> str:
    if not math.isfinite(hdop):
        return "poor"
    if hdop < 1.5:
        return "good"
    if hdop < 3.0:
        return "fair"
    return "poor"


async def update_trilateration_and_zone(hass, new_global_data, entity, eids):
    """Robust trilateration + Kalman smoothing + opportunistic auto-calibration."""
    global apitricords

    engine = _get_engine_state(entity)
    buckets = _build_floor_buckets(hass, eids, engine)
    if not buckets:
        return

    floor_name = _select_active_floor(buckets)
    if floor_name is None:
        return
    bucket = buckets[floor_name]
    samples = bucket["samples"]
    if len(samples) < 3:
        return

    fit = trilaterate_robust(
        samples,
        walls=bucket["walls"],
        wall_penalty_px=bucket["wall_penalty_px"],
    )
    if fit is None or not fit["converged"]:
        return

    now = time.monotonic()
    median_sigma_px = float(np.median([s.sigma_px for s in samples]))
    meas_var = max(1.0, (fit["hdop"] * median_sigma_px) ** 2)
    kalman: PositionKalman = engine["kalman"]
    smoothed = kalman.update(np.array([fit["x"], fit["y"]]), now, meas_var)
    avg_x, avg_y = float(smoothed[0]), float(smoothed[1])

    # Stationarity-driven self-calibration: if we've been still long enough,
    # the true distance to each receiver is just |position - receiver|.
    # Feeds two parallel models:
    #   1. Per-receiver linear correction (factor + offset) on top of the
    #      log-distance distance estimate.
    #   2. Per-link RSSI path-loss fit (tx_power, n) inside the BLE scanner
    #      itself — the *root* of the distance estimate.
    stationary = engine["stationary"].push(now, avg_x, avg_y)
    if stationary is not None:
        cx, cy, _dur = stationary
        scale = bucket["scale"] or 1.0
        scanner = get_scanner(hass)
        target_identity = bucket.get("target_identity")
        sources = bucket.get("sources", {})
        for s in samples:
            true_m = math.hypot(s.x - cx, s.y - cy) / scale
            calib = engine["autocal"].setdefault(
                s.receiver_id, AutoCalibrator()
            )
            calib.add(s.raw_distance_m, true_m)
            fit_cal = calib.fit()
            if fit_cal is not None:
                engine["last_fits"][s.receiver_id] = fit_cal
            if scanner is not None and target_identity:
                source = sources.get(s.receiver_id)
                if source:
                    scanner.add_calibration_sample(
                        target_identity, source, true_m,
                    )

    point = Point(avg_x, avg_y)
    zone = find_zone_for_point(new_global_data, entity, floor_name, point)

    quality = {
        "hdop": round(fit["hdop"], 3),
        "rms_residual_px": round(fit["rms_residual_px"], 2),
        "n_used": fit["n_used"],
        "speed_px_per_s": round(kalman.speed, 2),
        "stationary": stationary is not None,
        "label": _hdop_to_quality(fit["hdop"]),
    }
    engine["quality"] = quality

    apitricords = update_or_add_entry(
        apitricords,
        {
            "ent": entity,
            "cords": [avg_x, avg_y],
            "zone": zone,
            "floor": floor_name,
            "quality": quality,
        },
    )
    await update_apitricords(hass, apitricords)
    hass.states.async_set(f"sensor.{entity}_bps_zone", zone)
    hass.states.async_set(f"sensor.{entity}_bps_floor", floor_name)
    hass.states.async_set(
        f"sensor.{entity}_bps_quality",
        quality["label"],
        {
            "hdop": quality["hdop"],
            "n_used": quality["n_used"],
            "rms_residual_px": quality["rms_residual_px"],
            "speed_px_per_s": quality["speed_px_per_s"],
            "stationary": quality["stationary"],
        },
    )


def update_or_add_entry(data, new_entry):
    for item in data:
        if item["ent"] == new_entry["ent"]:  # Check if "ent" already exists
            item["cords"] = new_entry["cords"]  # Update "cords"
            item["zone"] = new_entry["zone"]  # Update "zone"
            return data

    # If "ent" was not found, add as new post
    data.append(new_entry)
    return data


async def update_apitricords(hass, new_data):
    """Update apitricords in hass.data"""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["apitricords"] = new_data


async def process_single_entity(hass, new_global_data, eids):
    """Drive the positioning engine for a single tracked entity."""
    await update_trilateration_and_zone(
        hass, new_global_data, eids["entity"], eids
    )


async def process_entities(hass, new_global_data):
    """Process multiple entities in parallel, but ensure the correct order for each individual entity"""
    tasks = [
        process_single_entity(hass, new_global_data, eids)
        for eids in new_global_data
    ]
    await asyncio.gather(
        *tasks
    )  # Run all entities in parallel, but maintain the correct internal order


def find_zone_for_point(data, entity, floor_name, point):
    """Find zone for point, prioritize correct polygon, select nearest buffer if no correct zone matches."""
    buffer_percent = 0.05  # set to 5%
    buffer_candidates = []
    for entity_data in data:
        if entity_data["entity"] == entity:
            for floor in entity_data["data"]["floor"]:
                if floor["name"] == floor_name:
                    for zone in floor["zones"]:
                        polygon = Polygon(
                            [(coord["x"], coord["y"]) for coord in zone["cords"]]
                        )
                        xs = [coord["x"] for coord in zone["cords"]]
                        ys = [coord["y"] for coord in zone["cords"]]
                        width = max(xs) - min(xs)
                        height = max(ys) - min(ys)
                        buffer_size = ((width + height) / 2) * buffer_percent
                        if polygon.contains(point):
                            # Prioritize correct polygon
                            return zone["entity_id"]
                        elif polygon.buffer(buffer_size).contains(point):
                            # Save candidate: (distance to edge, entity_id)
                            distance_to_edge = polygon.exterior.distance(
                                point
                            )
                            buffer_candidates.append(
                                (distance_to_edge, zone["entity_id"])
                            )
    if buffer_candidates:
        # Select zone whose edge is closest to the point
        buffer_candidates.sort()
        return buffer_candidates[0][1]
    return "unknown"


def _ensure_panel(hass: HomeAssistant) -> None:
    """Idempotently (re-)register the BPS+ sidebar panel.

    Called from `async_setup_entry` on every load — including reloads —
    because `async_unload_entry` removes the panel and the one-shot
    init flag in `async_setup` prevents the legacy register-on-init path
    from running again on the next entry setup.
    """
    panels = hass.data.get("frontend_panels", {})
    if "bps" in panels:
        try:
            async_remove_panel(hass, "bps")
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Could not remove existing BPS+ panel: %s", err)
    try:
        async_register_built_in_panel(
            hass=hass,
            component_name="iframe",
            sidebar_title="BPS+",
            sidebar_icon="mdi:map",
            frontend_url_path="bps",
            config={"url": "/bps/index.html"},
        )
        _LOGGER.info("BPS+ panel registered")
    except Exception as err:
        _LOGGER.error("Failed to register BPS+ panel: %s", err)


async def async_setup(hass: HomeAssistant, config):
    """Set up the BPS+ integration."""
    _LOGGER.info("BPS+ integration initialized.")

    # Usamos una flag con el DOMAIN para no inicializar dos veces
    init_flag_key = f"{DOMAIN}_initialized"

    if hass.data.get(init_flag_key, False):
        # Benign: async_setup is also re-invoked from async_setup_entry
        # so the heavy init runs once even on cold-boot. Use debug, not
        # warning, so the log doesn't look like a crash to users.
        _LOGGER.debug("BPS+ already initialised — skipping duplicate setup")
        return True

    hass.data[init_flag_key] = True  # Set flag

    async def initialize_bps():
        """Initialize the BPS+ component"""
        _LOGGER.info("Initializing BPS+...")

        # Registrar vistas REST solo una vez
        views_flag_key = f"{DOMAIN}_views_registered"
        if views_flag_key not in hass.data:
            hass.http.register_view(BPSFrontendView())
            hass.http.register_view(BPSSaveAPIText())
            hass.http.register_view(BPSMapsListAPI())
            hass.http.register_view(BPSReadAPIText())
            hass.http.register_view(BPSFrontendConfigAPI())
            hass.http.register_view(BPSDistanceValueAPI())
            hass.http.register_view(BPSScannersAPI())
            hass.http.register_view(BPSBleSnapshotAPI())
            hass.http.register_view(BPSDiagnosticsAPI())
            hass.http.register_view(BPSCordsAPI(hass))
            hass.data[views_flag_key] = True

        # Registrar WebSocket solo una vez
        ws_flag_key = f"{DOMAIN}_websocket"
        if ws_flag_key not in hass.data:
            websocket = BPSEntityWebSocket(hass)
            websocket.register()
            hass.data[ws_flag_key] = websocket

        config_path = hass.config.path()
        target_dir = os.path.join(config_path, "www", "bps_maps")
        target_file = os.path.join(target_dir, "bpsdata.txt")

        try:
            await aiofiles.os.makedirs(target_dir, exist_ok=True)
            _LOGGER.info(
                f"Folder {target_dir} has been created or already existed"
            )
        except Exception as e:
            _LOGGER.error(
                f"Could not create the folder {target_dir}: {e}"
            )
            return

        # Panel registration was moved out of initialize_bps so a reload
        # of the config entry can re-attach the sidebar — see _ensure_panel
        # below, called from async_setup_entry on every load.

        # Crear fichero bpsdata.txt si no existe
        try:
            if not os.path.exists(target_file):
                async with aiofiles.open(target_file, mode="w") as file:
                    await file.write("")
                _LOGGER.info(f"File {target_file} has been created.")
            else:
                _LOGGER.info(f"File {target_file} already exist.")
        except Exception as e:
            _LOGGER.error(f"Could not create file {target_file}: {e}")

        # Leer datos iniciales
        await update_global_data(target_file)

        # Watcher del fichero
        observer = setup_file_watcher(
            target_file, lambda: update_global_data(target_file), hass
        )

        # Native BLE scanner (replaces external Bermuda dependency).
        scanner = hass.data[DOMAIN].get("scanner")
        if scanner is None:
            scanner = BleScanner(hass)
            scanner.start()
            hass.data[DOMAIN]["scanner"] = scanner
            hass.bus.async_listen_once(
                "homeassistant_stop", lambda _e: scanner.stop()
            )

        hass.async_create_task(update_tracked_entities(hass))

        # Parar watcher al detener HA
        if observer is not None:
            hass.bus.async_listen_once(
                "homeassistant_stop", lambda event: observer.stop()
            )

        _LOGGER.info("The BPS+ integration is fully initialized")

    # Run initialization immediately — views, file watcher and BLE
    # scanner do not require HA to be in a fully-started state, and
    # gating on `homeassistant_started` made the BPS+ panel fail to
    # load maps when the user opened it during boot (the
    # `/api/bps/maps` endpoint had not been registered yet).
    await initialize_bps()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Remove a configuration entry"""
    _LOGGER.info("Attempting to offload platforms for entry: %s", entry.entry_id)

    entity_registry = er.async_get(hass)

    # Find and remove all entities that belong to this integration
    entities_to_remove = [
        entity.entity_id
        for entity in entity_registry.entities.values()
        if entity.platform == DOMAIN
    ]

    for entity_id in entities_to_remove:
        _LOGGER.info(f"Removes sensor: {entity_id}")
        entity_registry.async_remove(entity_id)

    try:  # Attempt to unload platforms
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, ["sensor"]
        )
    except Exception as e:
        _LOGGER.error(
            f"Error during offloading of platforms for entry {entry.entry_id}: {e}"
        )
        return False

    if not unload_ok:
        _LOGGER.error(
            "Failed to offload platforms for entry: %s", entry.entry_id
        )
        return False

    try:  # Remove the frontend panel
        async_remove_panel(hass, frontend_url_path="bps")
        _LOGGER.info("Frontend-panel removed for entry: %s", entry.entry_id)
    except Exception as e:
        _LOGGER.error(
            f"Error when removing frontend-panel for entry {entry.entry_id}: {e}"
        )
        return False

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up BPS+ from a configuration entry."""
    _LOGGER.info("async_setup_entry called for BPS+")

    # Guardamos el entry en hass.data por si hace falta en otras partes
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["config_entry"] = entry

    # Registrar la vista para servir el script.js dinámico de BPS+
    hass.http.register_view(BpsPlusScriptView(hass, entry))

    # Reutilizamos la inicialización general (APIs, watcher, scanner...).
    # MUST run before forwarding to the sensor platform — otherwise
    # sensor.py executes its discovery against an uninitialised BLE
    # scanner and creates zero entities until the next refresh tick.
    await async_setup(hass, {})

    # Configurar sensores (sensor.py)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    # Sidebar panel must be re-registered on every entry setup, even
    # when async_setup short-circuits on the init flag (after a reload
    # async_unload_entry removed the panel).
    _ensure_panel(hass)

    return True


class BPSFrontendView(HomeAssistantView):
    """Serve the frontend files."""

    url = "/bps/{file_name}"
    name = "bps:frontend"
    requires_auth = False
    # requires_auth = True

    async def get(self, request, file_name):
        """Serve static files from the frontend folder."""
        frontend_path = FRONTEND_PATH / file_name

        _LOGGER.info(f"Serving file: {frontend_path}")

        if not frontend_path.is_file():
            _LOGGER.error(f"Requested file not found: {frontend_path}")
            return web.Response(status=404, text="File not found")

        return web.FileResponse(path=str(frontend_path))


class BPSSaveAPIText(HomeAssistantView):
    """Handle saving of BPS coordinates to a text file."""

    url = "/api/bps/save_text"
    name = "api:bps:save_text"
    requires_auth = False

    async def post(self, request):
        """Handle saving coordinates to a text file."""
        hass = request.app["hass"]
        data = await request.post()

        coordinates = data.get("coordinates")

        if not coordinates:
            return web.Response(status=400, text="Missing coordinates")

        # Define the path to the bpsdata file
        maps_path = hass.config.path("www/bps_maps")
        bpsdata_file_path = Path(maps_path) / "bpsdata.txt"

        try:  # Save coordinates to the bpsdata file
            async with aiofiles.open(bpsdata_file_path, "w") as f:
                await f.write(coordinates)
                _LOGGER.warning(f"New file: {data.get('new_floor')}")
                if data.get("new_floor") == "true":  # If it is a new floor then save the file
                    map_file = data.get("file")
                    if not map_file:
                        return web.Response(status=400, text="Missing file")
                    map_file_path = Path(maps_path) / map_file.filename
                    try:
                        async with aiofiles.open(map_file_path, "wb") as f:
                            await f.write(map_file.file.read())
                    except Exception as e:
                        _LOGGER.error(f"Failed to save maps: {e}")
                        return web.Response(
                            status=500, text="Failed to save maps"
                        )

                # Check if "remove" key exists and delete the specified file
                remove_file = data.get("remove")
                if remove_file:
                    remove_file_path = Path(maps_path) / remove_file
                    if remove_file_path.exists():
                        _LOGGER.warning(
                            f"File exist: {remove_file_path}"
                        )
                        try:
                            remove_file_path.unlink()  # Delete the file
                            _LOGGER.info(
                                f"Removed file: {remove_file_path}"
                            )
                        except Exception as e:
                            _LOGGER.error(
                                f"Failed to remove file {remove_file_path}: {e}"
                            )
                            return web.Response(
                                status=500, text="Failed to remove file"
                            )

            _LOGGER.info(f"Saved coordinates to bpsdata: {coordinates}")
            return web.Response(
                status=200, text="Coordinates saved successfully"
            )

        except Exception as e:
            _LOGGER.error(f"Failed to save coordinates: {e}")
            return web.Response(
                status=500, text="Failed to save coordinates"
            )


class BPSReadAPIText(HomeAssistantView):
    """Handle reading of BPS coordinates from a text file."""

    url = "/api/bps/read_text"
    name = "api:bps:read_text"
    requires_auth = False

    async def get(self, request):
        """Handle reading coordinates from the text file."""
        hass = request.app["hass"]
        maps_path = hass.config.path("www/bps_maps")
        bpsdata_file_path = Path(maps_path) / "bpsdata.txt"
        canonical_map, entity_options, target_metadata = discover_distance_entities(hass)
        cache_discovery_data(hass, canonical_map, entity_options, target_metadata)
        entities = [item["id"] for item in entity_options]

        try:
            if not bpsdata_file_path.is_file():  # Check if the file exists
                return web.Response(
                    status=404, text="bpsdata.txt not found"
                )

            async with aiofiles.open(bpsdata_file_path, "r") as f:
                # Read the content of the file
                content = await f.read()

            _LOGGER.info(f"Read coordinates from bpsdata: {content}")
            return web.json_response(
                {
                    "coordinates": content,
                    "entities": entities,
                    "entity_options": entity_options,
                    "distance_entity_map": canonical_map,
                    "target_metadata": target_metadata,
                }
            )

        except Exception as e:
            _LOGGER.error(f"Failed to read coordinates: {e}")
            return web.Response(
                status=500, text="Failed to read coordinates"
            )


class BPSMapsListAPI(HomeAssistantView):
    """API to list map files in /www/bps_maps."""

    url = "/api/bps/maps"
    name = "api:bps:maps"
    requires_auth = False

    async def get(self, request):
        """Return a list of map files as JSON."""
        hass = request.app["hass"]
        maps_path = hass.config.path("www/bps_maps")

        try:
            def _scan_map_files(path: str) -> list[str]:
                return [
                    f.name
                    for f in os.scandir(path)
                    if f.is_file()
                    and f.name.lower().endswith((".png", ".jpg"))
                ]

            file_names = await hass.async_add_executor_job(
                _scan_map_files, maps_path
            )
            return web.json_response(file_names)
        except Exception as e:
            _LOGGER.error(f"Error listing map files: {e}")
            return web.Response(
                status=500, text="Error listing map files"
            )


class BPSFrontendConfigAPI(HomeAssistantView):
    """Expose frontend runtime config from config entry options."""

    url = "/api/bps/frontend_config"
    name = "api:bps:frontend_config"
    requires_auth = False

    async def get(self, request):
        """Return base_url/token/update_interval for the panel frontend."""
        hass = request.app["hass"]
        entry = hass.data.get(DOMAIN, {}).get("config_entry")
        if entry is None:
            return web.json_response(
                {
                    "base_url": "",
                    "token": "",
                    "update_interval": DEFAULT_UPDATE_INTERVAL,
                }
            )

        data = {**entry.data, **entry.options}
        base_url = str(data.get(CONF_BASE_URL, "")).strip()
        token = str(data.get(CONF_TOKEN, "")).strip()
        update_interval = int(
            data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        return web.json_response(
            {
                "base_url": base_url,
                "token": token,
                "update_interval": update_interval,
            }
        )


class BPSDistanceValueAPI(HomeAssistantView):
    """Read one distance entity value without calling /api/states directly."""

    url = "/api/bps/distance"
    name = "api:bps:distance"
    requires_auth = False

    async def get(self, request):
        """Return numeric value of a distance entity."""
        hass = request.app["hass"]
        entity_id = request.query.get("entity_id", "").strip()
        target_id = request.query.get("target_id", "").strip()
        receiver_id = request.query.get("receiver_id", "").strip()

        if not entity_id and target_id and receiver_id:
            canonical_map, _, _ = discover_distance_entities(hass)
            entity_id = canonical_map.get(target_id, {}).get(
                receiver_id, ""
            )

        state = hass.states.get(entity_id) if entity_id else None
        if state is None and target_id and receiver_id:
            state = find_managed_distance_state(
                hass, target_id, receiver_id
            )
            if state is not None:
                entity_id = state.entity_id

        if state is None and not entity_id and not (target_id and receiver_id):
            return web.json_response(
                {"error": "missing_entity_id_or_target_receiver"},
                status=400,
            )

        if state is None:
            return web.json_response(
                {
                    "error": "entity_not_found",
                    "entity_id": entity_id,
                    "target_id": target_id,
                    "receiver_id": receiver_id,
                },
                status=404,
            )

        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return web.json_response(
                {
                    "error": "state_not_numeric",
                    "entity_id": entity_id,
                    "state": state.state,
                },
                status=422,
            )

        return web.json_response(
            {"entity_id": entity_id, "value": value}
        )


class BPSScannersAPI(HomeAssistantView):
    """List BT proxies (scanners) the BLE engine currently sees.

    Used by the panel's map editor so placing a receiver becomes a
    dropdown of real proxies instead of a free-text field. Each entry's
    `id` is the slug the engine uses internally as the receiver key, so
    saving the map preserves the friendly slug (e.g. `bluetooth_proxy_cocina`).
    """

    url = "/api/bps/scanners"
    name = "api:bps:scanners"
    requires_auth = False

    async def get(self, request):
        hass = request.app["hass"]
        scanner = get_scanner(hass)
        if scanner is None:
            return web.json_response([])
        out = []
        for sc in scanner.known_scanners():
            friendly_slug = scanner_slugify(sc.name) if sc.name else ""
            rid = (
                friendly_slug
                or mac_to_token(sc.source)
                or (sc.source or "").lower().replace(":", "_")
            )
            out.append({
                "id": rid,
                "name": sc.name or sc.source,
                "source": sc.source,
            })
        return web.json_response(out)


class BPSBleSnapshotAPI(HomeAssistantView):
    """Live snapshot of what the native BLE scanner is seeing."""

    url = "/api/bps/ble_snapshot"
    name = "api:bps:ble_snapshot"
    requires_auth = False

    async def get(self, request):
        hass = request.app["hass"]
        scanner = get_scanner(hass)
        if scanner is None:
            return web.json_response(
                {"error": "scanner_not_initialised"}, status=503
            )
        return web.json_response(scanner.snapshot())


class BPSDiagnosticsAPI(HomeAssistantView):
    """Expose engine quality metrics + auto-calibration suggestions."""

    url = "/api/bps/diagnostics"
    name = "api:bps:diagnostics"
    requires_auth = False

    async def get(self, request):
        target = request.query.get("entity")
        out: dict[str, dict] = {}
        items = (
            [(target, _engine_state[target])]
            if target and target in _engine_state
            else _engine_state.items()
        )
        for entity, state in items:
            out[entity] = {
                "quality": state.get("quality", {}),
                "calibration_suggestions": dict(state.get("last_fits", {})),
                "samples_collected": {
                    rid: len(cal.samples)
                    for rid, cal in state.get("autocal", {}).items()
                },
            }
        return web.json_response(out)


class BPSCordsAPI(HomeAssistantView):
    """API för att skicka tillbaka apitricords"""

    url = "/api/bps/cords"
    name = "api:bps:cords"
    requires_auth = False  # Ändra till True om du vill kräva autentisering

    def __init__(self, hass: HomeAssistant):
        """Spara referens till hass"""
        self.hass = hass

    async def get(self, request):
        """Returnera apitricords från hass.data"""
        apitricords_local = self.hass.data.get(DOMAIN, {}).get(
            "apitricords", {}
        )

        if not apitricords_local:
            return web.json_response(
                {"error": "No data available"}, status=404
            )

        return web.json_response(apitricords_local)


class BpsPlusScriptView(HomeAssistantView):
    """Sirve un script.js generado dinámicamente para BPS+."""

    url = "/bps-plus/script.js"
    name = "bps_plus:script"
    requires_auth = False  # Igual que cuando metías el token en el JS a mano

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Inicializa la vista con acceso a hass y al entry."""
        self.hass = hass
        self.entry = entry

    async def get(self, request: web.Request) -> web.Response:
        """Devuelve el script con URL, token e intervalo inyectados."""

        # Mezclamos data y options (options tiene prioridad)
        data = {
            **self.entry.data,
            **self.entry.options,
        }

        base_url: str = data.get(CONF_BASE_URL, "").strip()
        token: str = data.get(CONF_TOKEN, "").strip()
        update_interval: int = int(
            data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )

        # Ruta al template JS (compartido en el propio componente)
        file_path = os.path.join(
            os.path.dirname(__file__), "script_template.js"
        )

        try:
            async with aiofiles.open(
                file_path, mode="r", encoding="utf-8"
            ) as f:
                content = await f.read()
        except FileNotFoundError:
            return web.Response(
                status=500,
                text="// BPS+ error: script_template.js no encontrado en custom_components/bps_plus/",
                content_type="application/javascript",
            )

        # Reemplazar marcadores por valores de la config
        content = (
            content.replace("__BASE_URL__", base_url)
            .replace("__TOKEN__", token)
            .replace("__UPDATE_INTERVAL__", str(update_interval * 1000))
        )

        return web.Response(
            text=content,
            content_type="application/javascript",
        )


class BPSEntityWebSocket:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self.tracked_entities = {}
        self.connections = []

    async def handle_subscribe(
        self, hass: HomeAssistant, connection: ActiveConnection, msg: dict
    ):
        """Managing subscription for entities"""
        _LOGGER.debug(f"Received subscription request: {msg}")
        entity_ids = msg["entities"]
        if not entity_ids:
            connection.send_message(
                {
                    "id": msg["id"],
                    "type": "result",
                    "success": False,
                    "error": {
                        "code": "invalid_request",
                        "message": "No entities provided.",
                    },
                }
            )
            return

        # Add connection to subscribed entities
        self.connections.append(connection)
        for entity_id in entity_ids:
            if entity_id not in self.tracked_entities:
                self.tracked_entities[entity_id] = []
            self.tracked_entities[entity_id].append(connection)

        # Send the current state for all subscribed entities
        current_states = []
        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            if state:
                current_states.append(
                    {
                        "entity_id": entity_id,
                        "state": state.state,
                        "attributes": state.attributes,
                    }
                )

        connection.send_message(
            {
                "id": msg["id"],
                "type": "result",
                "success": True,
                "message": f"Subscribed to entities: {entity_ids}",
                "current_states": current_states,
            }
        )

        # Listen for state_change
        async_track_state_change_event(
            hass, entity_ids, self.state_change_listener
        )

    async def handle_unsubscribe(
        self, hass: HomeAssistant, connection: ActiveConnection, msg: dict
    ):
        """Managing unsubscription"""
        _LOGGER.debug(f"Received unsubscribe request: {msg}")
        entity_ids = msg.get("entities", [])
        for entity_id in entity_ids:
            if entity_id in self.tracked_entities:
                if connection in self.tracked_entities[entity_id]:
                    self.tracked_entities[entity_id].remove(connection)
                if not self.tracked_entities[entity_id]:
                    del self.tracked_entities[entity_id]

        connection.send_message(
            {
                "id": msg["id"],
                "type": "result",
                "success": True,
                "message": f"Unsubscribed from entities: {entity_ids}",
            }
        )

    async def handle_known_points(
        self, hass: HomeAssistant, connection: ActiveConnection, msg: dict
    ):
        try:
            known_points = msg.get("knownPoints")  # Read knownPoints from the message
            if not known_points:
                connection.send_message(
                    {
                        "id": msg["id"],
                        "type": "tri_result",
                        "success": False,
                        "error": {
                            "code": "invalid_request",
                            "message": "No knownPoints provided.",
                        },
                    }
                )
                return

            # Perform trilateration
            result = trilaterate(known_points)

            if result is None:
                # If the result is None, return an error
                connection.send_message(
                    {
                        "id": msg["id"],
                        "type": "tri_result",
                        "success": False,
                        "error": {
                            "code": "calculation_error",
                            "message": "Trilateration failed.",
                        },
                    }
                )
                return

            # Send back the result
            connection.send_message(
                {
                    "id": msg["id"],
                    "type": "tri_result",
                    "success": True,
                    "result": {"x": result[0], "y": result[1]},
                }
            )

        except Exception as e:
            _LOGGER.error(f"Error processing knownPoints: {e}")
            connection.send_message(
                {
                    "id": msg["id"],
                    "type": "tri_result",
                    "success": False,
                    "error": {
                        "code": "server_error",
                        "message": str(e),
                    },
                }
            )

    async def state_change_listener(self, event):
        """Listens for status changes and sends them to connections."""
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        _LOGGER.debug(f"State change for {entity_id}: {old_state} -> {new_state}")

        # Create the message to send to subscribing clients
        message = {
            "type": "state_changed",
            "entity_id": entity_id,
            "old_state": old_state.state if old_state else None,
            "new_state": new_state.state if new_state else None,
        }

        # Send to all connected clients who are subscribed to this entity
        for connection in self.tracked_entities.get(entity_id, []):
            connection.send_message(message)

    def register(self):
        """Registers WebSocket commands"""
        _LOGGER.debug("Registering WebSocket commands")

        def subscribe_wrapper(hass, connection, msg):
            """Wrapper to invoke handle_subscribe."""
            hass.async_create_task(
                self.handle_subscribe(hass, connection, msg)
            )

        def unsubscribe_wrapper(hass, connection, msg):
            """Wrapper to invoke handle_unsubscribe."""
            hass.async_create_task(
                self.handle_unsubscribe(hass, connection, msg)
            )

        def known_points_wrapper(hass, connection, msg):
            """Wrapper to invoke handle_known_points."""
            hass.async_create_task(
                self.handle_known_points(hass, connection, msg)
            )

        async_register_command(
            self.hass,
            "bps/subscribe",
            subscribe_wrapper,  # The wrapper handles async
            schema=vol.Schema(
                {
                    vol.Required("type"): "bps/subscribe",  # Type for API
                    vol.Required("entities"): [str],
                    vol.Optional("id"): int,
                }
            ),
        )
        async_register_command(
            self.hass,
            "bps/unsubscribe",
            unsubscribe_wrapper,  # The wrapper handles async
            schema=vol.Schema(
                {
                    vol.Required("type"): "bps/unsubscribe",  # Type for API
                    vol.Required("entities"): [str],
                    vol.Optional("id"): int,
                }
            ),
        )
        async_register_command(
            self.hass,
            "bps/known_points",
            known_points_wrapper,  # The wrapper handles async
            schema=vol.Schema(
                {
                    vol.Required("type"): "bps/known_points",  # Type for API
                    vol.Required("knownPoints"): vol.All(
                        list, [vol.All([float, float, float])]
                    ),
                    vol.Optional("id"): int,
                }
            ),
        )

        _LOGGER.info("All WebSocket commands registered successfully.")


def trilaterate(known_points, walls=None, wall_penalty: float = 0.0):
    """Legacy adapter retained for the WebSocket `bps/known_points` API.

    Forwards to the robust engine using a flat per-point sigma so callers
    that lack noise estimates still benefit from soft-L1 outlier rejection,
    1/r² seeding and HDOP-aware fitting.
    """
    if len(known_points) < 3:
        _LOGGER.error("At least three known points are required for trilateration.")
        return None

    samples = [
        DistanceSample(
            receiver_id=str(idx),
            x=float(xi),
            y=float(yi),
            raw_distance_m=float(ri),
            distance_m=float(ri),
            radius_px=float(ri),
            sigma_px=max(2.0, 0.05 * float(ri)),
        )
        for idx, (xi, yi, ri) in enumerate(known_points)
    ]
    fit = trilaterate_robust(
        samples,
        walls=walls,
        wall_penalty_px=max(0.0, float(wall_penalty or 0.0)),
    )
    if fit is None or not fit["converged"]:
        _LOGGER.error("Robust trilateration did not converge.")
        return None
    return fit["x"], fit["y"]
