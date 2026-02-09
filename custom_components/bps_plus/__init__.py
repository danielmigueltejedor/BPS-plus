from __future__ import annotations

import logging
import asyncio
import os
import json
import re
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
from homeassistant.helpers.template import Template
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from shapely.geometry import Point, Polygon
from scipy.optimize import least_squares
import voluptuous as vol
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


def extract_distance_entity_parts(entity_id: str) -> tuple[str, str] | None:
    """Return (target, receiver) from sensor.target_distance_to_receiver."""
    cleaned = entity_id.replace("sensor.", "", 1)
    if "_distance_to_" not in cleaned:
        return None
    target, receiver = cleaned.split("_distance_to_", 1)
    if not target or not receiver:
        return None
    return target, receiver


def discover_distance_entities(hass: HomeAssistant):
    """Discover distance entities with canonical target mapping and metadata."""
    current_to_source, target_metadata = build_bluetooth_alias_maps(hass)

    canonical_map: dict[str, dict[str, str]] = {}
    for state in hass.states.async_all():
        if not state.entity_id.startswith("sensor.") or "_distance_to_" not in state.entity_id:
            continue
        parts = extract_distance_entity_parts(state.entity_id)
        if not parts:
            continue
        raw_target, receiver = parts
        canonical_target = canonical_target_token(raw_target, current_to_source)
        canonical_map.setdefault(canonical_target, {})[receiver] = state.entity_id

    # Include known BLE devices even if no _distance_to_ sensor is active right now.
    for target_id in target_metadata:
        canonical_map.setdefault(target_id, {})

    entity_options = []
    for target_id in sorted(canonical_map):
        metadata = target_metadata.get(target_id, {})
        name = metadata.get("friendly_name", target_id)
        entity_options.append({"id": target_id, "name": name})

    return canonical_map, entity_options, target_metadata


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


async def update_tracked_entities(hass, jinja_code):
    """Update tracked_entities with the result of the Jinja code once per second."""
    global tracked_entities, tracked_listeners, global_data, new_global_data
    global secToUpdate
    while True:
        try:
            template = Template(jinja_code, hass)
            tracked_entities = template.async_render()

            num_points = len(tracked_entities)
            if num_points < 3:  # There are no devices close enough to track, wait 10 seconds until try again
                _LOGGER.info("There are no devices present to track, sleep 10 seconds")
                await asyncio.sleep(10)
                continue  # Skip and start over

            canonical_map, entity_options, target_metadata = discover_distance_entities(hass)
            cache_discovery_data(hass, canonical_map, entity_options, target_metadata)
            new_global_data = [
                {
                    "entity": ent,
                    "data": global_data,
                    "receiver_state_map": receiver_map,
                }
                for ent, receiver_map in canonical_map.items()
            ]

            await process_entities(hass, new_global_data)

        except Exception as e:
            _LOGGER.info(f"Error executing Jinja code: {e}")

        # Run every X seconds, set timer in global variables
        await asyncio.sleep(secToUpdate)


async def update_receiver_radii(hass, eids):
    """Update receiver 'r' values for an entity"""
    for floor in (f for f in eids["data"]["floor"] if f["scale"] is not None):
        floor_scale = floor.get("scale")
        if floor_scale is None:
            continue
        receiver_state_map = eids.get("receiver_state_map", {})
        for receiver in floor["receivers"]:
            entity_id = receiver_state_map.get(receiver["entity_id"])
            if not entity_id:
                entity_id = (
                    "sensor."
                    + eids["entity"]
                    + "_distance_to_"
                    + receiver["entity_id"]
                )
            rec_value = hass.states.get(entity_id)
            if rec_value is not None:
                try:
                    raw_distance = float(rec_value.state)
                    calibration = receiver.get("calibration", {})
                    cal_factor = float(calibration.get("factor", 1.0))
                    cal_offset = float(calibration.get("offset", 0.0))

                    corrected_distance = (raw_distance * cal_factor) + cal_offset
                    corrected_distance = max(corrected_distance, 0.0)

                    radius = float(floor_scale) * corrected_distance
                    receiver["cords"]["r"] = radius
                except (TypeError, ValueError):
                    # _LOGGER.info(f"Invalid numerical value: {rec_value.state}")
                    pass
            else:
                # _LOGGER.info(f"Entity had no value: {receiver['entity_id']}")
                pass


async def update_trilateration_and_zone(hass, new_global_data, entity):
    """Trilateration with r-value filtering and moving average filtering."""
    global apitricords
    filter_percent = 0.5  # 50% change in r-value
    filter_value_high = 1 * (1 + filter_percent)
    filter_value_low = 1 * (1 - filter_percent)

    # Store last r-values per sensor and entity
    if not hasattr(update_trilateration_and_zone, "last_r_values"):
        update_trilateration_and_zone.last_r_values = {}
    # Store last positions for moving average filtering
    if not hasattr(update_trilateration_and_zone, "position_history"):
        update_trilateration_and_zone.position_history = {}

    lowest_floor_name, filtered_cords = extract_floor_and_receivers(
        new_global_data, entity
    )
    # filtered_cords: list of (x, y, r)

    # Get previous r-values for this entity
    last_r = update_trilateration_and_zone.last_r_values.get(entity, {})

    # Filter out points where r has changed too much
    filtered = []
    for idx, (x, y, r) in enumerate(filtered_cords):
        key = (x, y)  # or receiver-id if available
        prev_r = last_r.get(key)
        if prev_r is not None:
            if r > prev_r * filter_value_high or r < prev_r * filter_value_low:
                continue  # skip this point
        filtered.append((x, y, r))

    # Store current r-values for next time
    update_trilateration_and_zone.last_r_values[entity] = {
        (x, y): r for (x, y, r) in filtered_cords
    }

    if len(filtered) < 3:
        # Too few points left for trilateration
        return

    tricords = trilaterate(filtered)
    if tricords is not None:
        # Moving average filtering
        history = update_trilateration_and_zone.position_history.setdefault(
            entity, []
        )
        history.append(tricords)
        if len(history) > 3:  # Keep only the last 3 positions
            history.pop(0)
        avg_x = sum(pos[0] for pos in history) / len(history)
        avg_y = sum(pos[1] for pos in history) / len(history)

        test_point = Point(float(avg_x), float(avg_y))
        zone = find_zone_for_point(
            new_global_data, entity, lowest_floor_name, test_point
        )
        apitricords = update_or_add_entry(
            apitricords,
            {"ent": entity, "cords": [avg_x, avg_y], "zone": zone},
        )
        await update_apitricords(hass, apitricords)
        hass.states.async_set(f"sensor.{entity}_bps_zone", zone)
        hass.states.async_set(f"sensor.{entity}_bps_floor", lowest_floor_name)


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
    """Process a single entity: first receivers, then trilateration"""
    await update_receiver_radii(hass, eids)  # Wait for the receivers to update
    await update_trilateration_and_zone(
        hass, new_global_data, eids["entity"]
    )  # When it is complete → perform trilateration


async def process_entities(hass, new_global_data):
    """Process multiple entities in parallel, but ensure the correct order for each individual entity"""
    tasks = [
        process_single_entity(hass, new_global_data, eids)
        for eids in new_global_data
    ]
    await asyncio.gather(
        *tasks
    )  # Run all entities in parallel, but maintain the correct internal order


def extract_floor_and_receivers(new_global_data, tmpentity):
    """Find floor with closest receiver and return explicit (x, y, r) points."""
    floor_points = {}
    floor_min_r = {}

    for entity in new_global_data:
        if entity["entity"] != tmpentity:
            continue

        for floor in entity["data"]["floor"]:
            floor_name = floor.get("name")
            if floor_name is None:
                continue

            points = []
            min_r = float("inf")

            for receiver in floor.get("receivers", []):
                cords = receiver.get("cords", {})
                x = cords.get("x")
                y = cords.get("y")
                r = cords.get("r")
                if x is None or y is None or r is None:
                    continue
                try:
                    r_val = float(r)
                except (TypeError, ValueError):
                    continue
                if r_val <= 0:
                    continue
                points.append((float(x), float(y), r_val))
                if r_val < min_r:
                    min_r = r_val

            if points:
                floor_points[floor_name] = points
                floor_min_r[floor_name] = min_r

    if not floor_min_r:
        return None, []

    lowest_floor_name = min(floor_min_r, key=floor_min_r.get)
    return lowest_floor_name, floor_points.get(lowest_floor_name, [])


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


async def async_setup(hass: HomeAssistant, config):
    """Set up the BPS-Plus integration."""
    _LOGGER.info("BPS-Plus integration initialized.")

    # Usamos una flag con el DOMAIN para no inicializar dos veces
    init_flag_key = f"{DOMAIN}_initialized"

    if hass.data.get(init_flag_key, False):
        _LOGGER.warning("BPS-Plus has already been initialized. Aborting")
        return True  # Abort if already running

    hass.data[init_flag_key] = True  # Set flag

    async def initialize_bps():
        """Initialize the BPS-Plus component"""
        _LOGGER.info("Initializing BPS-Plus...")

        # Registrar vistas REST solo una vez
        views_flag_key = f"{DOMAIN}_views_registered"
        if views_flag_key not in hass.data:
            hass.http.register_view(BPSFrontendView())
            hass.http.register_view(BPSSaveAPIText())
            hass.http.register_view(BPSMapsListAPI())
            hass.http.register_view(BPSReadAPIText())
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

        # Panel lateral (iframe) en HA
        panels = hass.data.get("frontend_panels", {})
        if "bps" in panels:
            async_remove_panel(hass, "bps")
        try:
            _LOGGER.debug("Registering the built-in panel for BPS-Plus...")
            async_register_built_in_panel(
                hass=hass,
                component_name="iframe",
                sidebar_title="BPS-Plus",
                sidebar_icon="mdi:map",
                frontend_url_path="bps",
                config={"url": "/bps/index.html"},
            )
            _LOGGER.info("Panel registered successfully.")
        except Exception as e:
            _LOGGER.error(f"Failed to register panel: {e}")

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

        # Jinja para descubrir entidades _distance_to_
        jinja_code = """
        {{
            expand(states.sensor)
            | selectattr("entity_id", "search", "_distance_to_")
            | selectattr("state", "is_number")
            | map(attribute="entity_id")
            | unique
            | list
        }}
        """

        hass.async_create_task(update_tracked_entities(hass, jinja_code))

        # Parar watcher al detener HA
        if observer is not None:
            hass.bus.async_listen_once(
                "homeassistant_stop", lambda event: observer.stop()
            )

        _LOGGER.info("The BPS-Plus integration is fully initialized")

    async def handle_homeassistant_started(event):
        """Handles the 'homeassistant_started' event"""
        await initialize_bps()

    if hass.is_running:
        await initialize_bps()
    else:
        hass.bus.async_listen_once(
            "homeassistant_started", handle_homeassistant_started
        )

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
    """Set up BPS-Plus from a configuration entry."""
    _LOGGER.info("async_setup_entry called for BPS-Plus")

    # Guardamos el entry en hass.data por si hace falta en otras partes
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["config_entry"] = entry

    # Registrar la vista para servir el script.js dinámico de BPS-Plus
    hass.http.register_view(BpsPlusScriptView(hass, entry))

    # Configurar sensores (sensor.py)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    # Reutilizamos la inicialización general (panel, APIs, watcher…)
    await async_setup(hass, {})

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
            files = [
                f
                for f in os.scandir(maps_path)
                if f.is_file()
                and f.name.lower().endswith((".png", ".jpg"))
            ]
            file_names = [f.name for f in files]
            return web.json_response(file_names)
        except Exception as e:
            _LOGGER.error(f"Error listing map files: {e}")
            return web.Response(
                status=500, text="Error listing map files"
            )


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
    """Sirve un script.js generado dinámicamente para BPS-Plus."""

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
                text="// BPS-Plus error: script_template.js no encontrado en custom_components/bps_plus/",
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


# Trilateration function
def trilaterate(known_points):
    num_points = len(known_points)

    if num_points < 3:
        # Make sure there are enough points (min 3) to do a trilateration
        _LOGGER.error(
            "At least three known points are required for trilateration."
        )
        return None

    def objective_function(X, known_points):
        # Define the objective function loss for the least squares method.
        x, y = X
        residuals = []
        for xi, yi, ri in known_points:
            residual = np.sqrt((xi - x) ** 2 + (yi - y) ** 2) - ri
            residuals.append(residual)
        weights = 1.0 / np.array([ri**2 for _, _, ri in known_points])
        return np.sqrt(weights) * np.array(residuals)

    # Initial guess value for unknown coordinates
    x0 = np.array([0, 0])

    # Perform weighting adjustment for the least squares method.
    result = least_squares(objective_function, x0, args=(known_points,))

    if not result.success:
        # Check if the fitting was successful
        _LOGGER.error(
            "Weighted nonlinear least squares fitting did not converge."
        )
        return None
    x, y = result.x  # Extract the calculated coordinates
    return x, y  # return the result
