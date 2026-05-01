import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "bps_plus"
    / "positioning.py"
)
_SPEC = spec_from_file_location("bps_plus_positioning", _MODULE_PATH)
_MODULE = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

apply_calibration = _MODULE.apply_calibration


def test_apply_calibration_defaults_to_identity():
    assert apply_calibration(3.0, None) == 3.0


def test_apply_calibration_applies_factor_offset_and_exponent():
    calibration = {"factor": 2.0, "offset": 1.0, "exponent": 1.0}
    assert apply_calibration(3.0, calibration) == 7.0


def test_apply_calibration_clamps_negative_or_invalid():
    assert apply_calibration(-1.0, {"factor": 2.0}) == 0.0
