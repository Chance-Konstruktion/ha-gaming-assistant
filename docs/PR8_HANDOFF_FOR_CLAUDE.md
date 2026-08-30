# PR #8 / #9 Implementation Handoff

## What was added

### New: Android TV Capture Agent (`worker/capture_agent_android_tv.py`)
- Captures screenshots from Android TV / Google TV via ADB `screencap`
- Supports `--game-hint` for streaming apps (Steam Link, GeForce NOW, etc.)
- Uses same MQTT topic structure as other agents (`gaming_assistant/{client_id}/image` + `/meta`)
- `client_type` in metadata: `"android_tv"`

### Improved: PC Capture Agent (`worker/capture_agent.py`)
- Added X11 window title detection via `xprop` (previously Windows-only via `win32gui`)
- Added `--game-hint` CLI flag as manual fallback (useful for Wayland)
- Metadata now includes `"detector"` field indicating detection method

### New: CI Pipeline (`.github/workflows/ci.yml`)
- Runs on push to `main` and on PRs
- Installs capture dependencies
- Python syntax check for all agent modules
- Runs unit tests via `python -m unittest discover`

### New: Unit Tests (`tests/test_capture_agents.py`)
- PC agent: game detection, X11/Windows window title dispatch
- Android agent: ADB command building, foreground app detection, screenshot capture
- Android TV agent: ADB commands, known games list, screenshot capture
- IP Webcam agent: snapshot fetching with and without auth
- Cross-agent: MQTT topic format consistency

### Other changes
- `worker/__init__.py` – package initialization
- `worker/requirements-capture.txt` – added `requests>=2.28.0`
- `.gitignore` – Python artifacts, IDE files, OS files
- `services.yaml` – added `android_tv` to `client_type` options
- `README.md` – Android TV setup instructions, `--game-hint` docs, X11 note

## Architecture notes

All agents follow the same pattern:
1. Capture screenshot (platform-specific)
2. Resize + JPEG compress via Pillow
3. Publish binary image + JSON metadata via MQTT
4. All intelligence stays in Home Assistant

The Android TV agent is structurally similar to the Android agent but targets
network-connected TV devices and includes streaming app names in its known games list.
