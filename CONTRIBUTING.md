# Contributing to BPS+

Bug reports, positioning traces, documentation improvements and code contributions are welcome.

## Before opening an issue

1. Test the latest release and restart Home Assistant.
2. Search existing issues for the same symptom.
3. Use the matching issue form and include exact Home Assistant and BPS+ versions.
4. Remove MAC addresses, entity IDs, floor plans, coordinates and other private data from logs and screenshots.

Use Discussions for setup help that is not a reproducible bug.

## Code contributions

- Keep asynchronous Home Assistant paths non-blocking.
- Preserve config-entry and entity compatibility unless the change explicitly includes a migration.
- Add or update tests for positioning, calibration and BLE parsing changes.
- Avoid repeated full-state scans and expensive geometry work in high-frequency loops.
- Keep frontend and backend calibration limits aligned.

Run the local checks before opening a pull request:

```bash
python -m pip install pytest ruff numpy scipy shapely watchdog aiofiles
ruff check tests
pytest
python -m compileall -q custom_components/bps_plus
```

Pull requests should explain the user-visible behavior, the validation performed and any compatibility impact.
