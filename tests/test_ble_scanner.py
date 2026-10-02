import sys
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "bps_plus"
    / "ble_scanner.py"
)
_SPEC = spec_from_file_location("bps_plus_ble_scanner", _MODULE_PATH)
_MODULE = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

mac_to_token = _MODULE.mac_to_token
normalize_mac = _MODULE.normalize_mac
rssi_to_distance = _MODULE.rssi_to_distance


def test_normalize_mac_accepts_common_formats():
    assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"


def test_normalize_mac_rejects_invalid_values():
    assert normalize_mac(None) is None
    assert normalize_mac("invalid") is None
    assert normalize_mac("AA:BB:CC") is None


def test_mac_to_token():
    assert mac_to_token("AA:BB:CC:DD:EE:FF") == "aa_bb_cc_dd_ee_ff"
    assert mac_to_token("") == ""
    assert mac_to_token(None) == ""


def test_rssi_to_distance_handles_invalid_inputs():
    assert rssi_to_distance(rssi=0, tx_power=-59, n=2.5) == float("inf")
    assert rssi_to_distance(rssi=-70, tx_power=-59, n=0) == float("inf")


def _scanner():
    return _MODULE.BleScanner(hass=None)


def test_known_scanners_hides_sources_older_than_stale_after():
    scanner = _scanner()
    now = time.monotonic()
    live = "AA:BB:CC:DD:EE:01"
    quiet = "AA:BB:CC:DD:EE:02"
    attic = "AA:BB:CC:DD:EE:03"
    scanner.scanners[live] = _MODULE.ScannerMeta(
        source=live, name="Kitchen", last_seen=now,
    )
    scanner.scanners[quiet] = _MODULE.ScannerMeta(
        source=quiet, name="Garage", last_seen=now - _MODULE.STALE_AFTER - 1,
    )
    scanner.scanners[attic] = _MODULE.ScannerMeta(
        source=attic, name="Attic", last_seen=now,
    )

    # Live proxies only, sorted by friendly name. Garage is remembered
    # until the 30 min prune but is not "currently seen".
    assert [s.source for s in scanner.known_scanners()] == [attic, live]
    assert quiet in scanner.scanners
    aged = {
        s.source for s in scanner.known_scanners(max_age=_MODULE.DEVICE_PRUNE_AFTER)
    }
    assert aged == {live, quiet, attic}


def test_advertisement_registers_a_live_scanner():
    scanner = _scanner()

    class _Adv:
        address = "11:22:33:44:55:66"
        source = "aa:bb:cc:dd:ee:01"
        rssi = -60
        name = "phone"
        tx_power = None

    scanner._on_adv(_Adv(), None)

    seen = scanner.known_scanners()
    assert [s.source for s in seen] == ["AA:BB:CC:DD:EE:01"]
    assert seen[0].last_seen > 0


def test_prune_stale_drops_scanners_without_dropping_live_devices():
    scanner = _scanner()
    now = 50_000.0
    live = "AA:BB:CC:DD:EE:01"
    dead = "AA:BB:CC:DD:EE:02"
    phone = "AA:BB:CC:DD:EE:10"
    scanner.devices[phone] = _MODULE.DeviceMeta(identity=phone, last_seen=now)
    scanner.scanners[live] = _MODULE.ScannerMeta(
        source=live, name="Kitchen Proxy", last_seen=now - 5,
    )
    scanner.scanners[dead] = _MODULE.ScannerMeta(
        source=dead,
        name="Garage Proxy",
        last_seen=now - _MODULE.DEVICE_PRUNE_AFTER - 1,
    )
    scanner._name_cache[live] = "Kitchen Proxy"
    scanner._name_cache[dead] = "Garage Proxy"
    scanner._receiver_resolution["kitchen_proxy"] = live
    scanner._receiver_resolution["garage_proxy"] = dead
    # Path-loss samples stay with the link so the proxy can resume its fit.
    scanner.links[(phone, dead)] = _MODULE.LinkState(
        last_seen=now - _MODULE.DEVICE_PRUNE_AFTER - 1,
        samples=[(-70.0, 2.0)],
    )

    dropped = scanner.prune_stale(now)

    assert dropped == 0
    assert phone in scanner.devices
    assert dead not in scanner.scanners
    assert live in scanner.scanners
    assert dead not in scanner._name_cache
    assert scanner._name_cache[live] == "Kitchen Proxy"
    assert "garage_proxy" not in scanner._receiver_resolution
    assert scanner._receiver_resolution["kitchen_proxy"] == live
    assert scanner.links[(phone, dead)].samples == [(-70.0, 2.0)]
    assert scanner.resolve_receiver("kitchen_proxy") == live
    assert scanner.resolve_receiver("garage_proxy") is None


def test_pruned_scanner_does_not_keep_winning_resolve_receiver():
    scanner = _scanner()
    now = 80_000.0
    dead = "AA:BB:CC:DD:EE:02"
    replacement = "AA:BB:CC:DD:EE:03"
    scanner.scanners[dead] = _MODULE.ScannerMeta(
        source=dead,
        name="Garage Proxy",
        last_seen=now - _MODULE.DEVICE_PRUNE_AFTER - 5,
    )
    scanner._name_cache[dead] = "Garage Proxy"
    scanner._receiver_resolution["garage_proxy"] = dead

    scanner.prune_stale(now)
    scanner.scanners[replacement] = _MODULE.ScannerMeta(
        source=replacement, name="Garage Proxy", last_seen=now,
    )

    assert scanner.resolve_receiver("garage_proxy") == replacement


def test_prune_stale_still_drops_devices_links_and_aliases():
    scanner = _scanner()
    now = 100_000.0
    ident = "AA:BB:CC:DD:EE:10"
    rotating = "AA:BB:CC:DD:EE:11"
    source = "AA:BB:CC:DD:EE:01"
    scanner.devices[ident] = _MODULE.DeviceMeta(
        identity=ident, last_seen=now - _MODULE.DEVICE_PRUNE_AFTER - 1,
    )
    scanner.links[(ident, source)] = _MODULE.LinkState(last_seen=now)
    scanner._aliases[rotating] = ident
    scanner.scanners[source] = _MODULE.ScannerMeta(
        source=source, name="Kitchen", last_seen=now,
    )

    assert scanner.prune_stale(now) == 1
    assert ident not in scanner.devices
    assert (ident, source) not in scanner.links
    assert rotating not in scanner._aliases
    assert source in scanner.scanners
