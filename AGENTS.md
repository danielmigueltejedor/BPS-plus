# Agent instructions — BPS-plus

## Repository-specific deterministic quality contract (2026-10-26)

**Project:** Python Home Assistant Bluetooth positioning integration.

**Engineering requirements:** Preserve BLE positioning behavior, config-entry compatibility and HA API contracts. Add fixtures for detection limits and negative/invalid RSSI values.

**Verification commands:** ruff check tests && python -m pytest -q tests && python -m compileall -q custom_components/bps_plus.

Before completion, run relevant checks and report exact pass/fail results. Add regression tests for changed behavior, bounds and failure paths. Never weaken/delete/skip tests, suppress warnings, or change CI thresholds to fabricate green results. Changes to `QUALITY_GATES.md`, this contract, and workflows require human review. The `quality` status must be required in branch protection to make the gate enforceable. If native dependencies prevent a test, explicitly report the blocker rather than claiming success. Existing project instructions have precedence for build setup; this section augments them.
