import sys
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
