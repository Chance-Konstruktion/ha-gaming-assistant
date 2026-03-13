# Gaming Assistant for Home Assistant

A HACS custom integration that brings an AI-powered gaming coach into your smart home.
Uses a local Vision LLM (via [Ollama](https://ollama.com)) to analyze your game screen
and push tips directly into Home Assistant -- no cloud, no subscriptions.

---

## Architecture

v0.4 uses a **Thin Client Architecture**: the gaming device only captures and sends
screenshots. All intelligence runs in Home Assistant.

```
Gaming PC / Android / Android TV / IP Webcam (Capture Agent)
  └── Screenshot capture + JPEG compress + MQTT publish (binary image + metadata)
         │
    Home Assistant (the "Brain")
      ├── MQTT Image Listener
      ├── Image Deduplication (hash)
      ├── Game Detection (via client metadata)
      ├── History Manager (per game, JSON)
      ├── Spoiler Level System
      ├── Prompt Pack Loader (game-specific coaching)
      ├── Dynamic Prompt Builder
      ├── Ollama Vision LLM Call
      └── Sensors + Services
         │
    Automations
      ├── TTS (speak tips aloud)
      ├── RGB lights
      ├── Notifications
      └── Spoiler control
```

### Legacy Mode

The integration also supports the old v0.2/v0.3 workers that send finished tips
via MQTT. If messages arrive on `gaming_assistant/tip`, the integration works in
passthrough mode.

---

## Requirements

| Component | Details |
|-----------|---------|
| Home Assistant | 2024.1+ with MQTT integration |
| MQTT Broker | Mosquitto (built-in HA add-on) |
| Gaming Devices | PC, Steam Deck/Linux handhelds, Android phones/tablets, Android TV/Google TV |
| Ollama | Running locally or on a machine reachable from HA |

### Recommended Vision Models

| Model | VRAM | Notes |
|-------|------|-------|
| `qwen2.5vl` | ~8 GB | Best quality, recommended |
| `llava` | ~8 GB | Good general purpose |
| `bakllava` | ~6 GB | Lighter option |
| `llama3.2-vision` | ~10 GB | Excellent, needs more VRAM |

---

## Installation

### Step 1 -- HACS

1. Open HACS -> Integrations -> ... -> **Custom repositories**
2. Add this repo URL, type: **Integration**
3. Find **Gaming Assistant** in the list and click **Install**
4. Restart Home Assistant

### Step 2 -- Add Integration

Go to **Settings -> Devices & Services -> Add Integration -> Gaming Assistant**

The config flow has 3 steps:
1. **Ollama Host** -- URL of your Ollama server
2. **Model & Interval** -- Choose a vision model and capture interval
3. **Spoiler Level** -- Default spoiler level (none/low/medium/high)

> **Note:** The config flow validates the Ollama connection. If the server is
> unreachable you'll see an error and can correct the URL.

### Step 3 -- Capture Agent Setup

#### PC Capture Agent

```bash
# Install dependencies (much lighter than before -- no requests/ollama needed)
pip install -r worker/requirements-capture.txt

# Windows: optional for active-window detection
pip install pywin32

# Linux (X11): optional xprop for active-window detection
# sudo apt install x11-utils

# Start the capture agent
python worker/capture_agent.py \
  --broker 192.168.1.10 \
  --client-id gaming-pc \
  --interval 5 \
  --quality 75 \
  --game-hint "Steam Game"
```

> Linux/macOS note: window detection is best-effort. X11 can use `xprop`; Wayland is currently experimental. Use `--game-hint` as fallback when no window title is detected.

#### Android Capture Agent

```bash
pip install -r worker/requirements-capture.txt

# Verify ADB sees your device
adb devices

# Start the Android capture agent
python worker/capture_agent_android.py \
  --broker 192.168.1.10 \
  --client-id android-phone \
  --interval 5
```

#### Wi-Fi ADB (wireless)

```bash
adb tcpip 5555
adb connect 192.168.1.42:5555

python worker/capture_agent_android.py \
  --broker 192.168.1.10 \
  --device 192.168.1.42:5555
```


#### IP Webcam Capture Agent (Console / TV setup)

```bash
pip install -r worker/requirements-capture.txt

# Example with Android IP Webcam app
python worker/capture_agent_ipcam.py \
  --broker 192.168.1.10 \
  --url http://192.168.1.42:8080/shot.jpg \
  --client-id livingroom-console \
  --game-hint "Elden Ring" \
  --interval 5 \
  --quality 75 \
  --game-hint "Steam Game"
```

Tip: point your phone camera at the TV/monitor and lock focus/exposure for more stable tips.

#### Android TV / Google TV Capture Agent (ADB)

```bash
pip install -r worker/requirements-capture.txt

# Enable developer mode + network debugging on your TV/box first
# then connect once via ADB
adb connect 192.168.1.50:5555

python worker/capture_agent_android_tv.py \
  --broker 192.168.1.10 \
  --device 192.168.1.50:5555 \
  --client-id livingroom-tv \
  --interval 5 \
  --quality 75 \
  --game-hint "Steam Game"
```

Works with many Android TV / Google TV devices (e.g. Sony TVs, Chromecast with Google TV, NVIDIA Shield).

---

## Supported Capture Sources (quick overview)

- `worker/capture_agent.py` → PC / Steam Deck desktop capture
- `worker/capture_agent_android.py` → Android devices via ADB
- `worker/capture_agent_android_tv.py` → Android TV / Google TV via ADB
- `worker/capture_agent_ipcam.py` → Phone/IP camera snapshot endpoint

All sources publish to the same MQTT image/meta topics, so automations and sensors keep working unchanged.

Priority for current roadmap execution:
1. Android TV / Google TV + IP webcam (living-room first)
2. PC / Steam Deck desktop capture
3. HDMI/capture-card only as optional fallback

---

## Features

The assistant is designed as a **universal vision coach**: with the right capture source it can support not only action games, but also slower games like chess, board games, and card games via phone camera or TV capture.

It supports both:
- **Ask mode** (you ask directly for help), and
- **Proactive mode** (automation triggers regular analysis and hints).

### Spoiler Level System

Control what the AI is allowed to reveal across 7 categories:

| Category | Description |
|----------|-------------|
| story | Plot points and narrative |
| items | Equipment and collectibles |
| enemies | Enemy types and strategies |
| bosses | Boss fights and mechanics |
| locations | Area names and directions |
| lore | World lore and backstory |
| mechanics | Game mechanics |

Each category can be set to: **none**, **low**, **medium**, or **high**.

Change spoiler levels via the `gaming_assistant.set_spoiler_level` service:

```yaml
service: gaming_assistant.set_spoiler_level
data:
  category: bosses
  level: none
  game: "Elden Ring"  # optional, for game-specific settings
```

### Game-Specific Prompt Packs

The integration includes prompt packs for popular games that provide tailored
coaching. Built-in packs: Elden Ring, Dark Souls III, Baldur's Gate 3,
Minecraft, Zelda: Tears of the Kingdom.

Create custom packs by adding JSON files to
`custom_components/gaming_assistant/prompt_packs/`. See `_template.json`
for the format.

### Tip History

Tips are stored per game with image deduplication. The history sensor shows:
- Number of tips this session
- Last 5 tips
- Current game name
- Active client ID

Clear history via `gaming_assistant.clear_history`.

---

## Entities

| Entity | Description |
|--------|-------------|
| `sensor.gaming_assistant_tip` | Latest AI-generated gameplay tip |
| `sensor.gaming_assistant_status` | Status (idle / analyzing / error) |
| `sensor.gaming_assistant_history` | Tip count + recent tips as attributes |
| `binary_sensor.gaming_mode` | ON when a game is detected |

The integration supports both:
- **Ask mode**: ask directly via `gaming_assistant.ask` (optional image context).
- **Proactive mode**: periodic/triggered automations run analysis in the background and push hints.

## Services

| Service | Description |
|---------|-------------|
| `gaming_assistant.analyze` | Trigger an immediate screenshot analysis |
| `gaming_assistant.start` | Resume the capture agent |
| `gaming_assistant.stop` | Pause the capture agent |
| `gaming_assistant.process_image` | Manually analyze an image (path or base64) |
| `gaming_assistant.ask` | Ask a direct question (optional image context) |
| `gaming_assistant.set_spoiler_level` | Change spoiler settings |
| `gaming_assistant.set_spoiler_profile` | Set or clear per-game spoiler profile (all categories) |
| `gaming_assistant.clear_history` | Clear tip history |

---

## Lovelace Dashboard

Copy the card from `lovelace/dashboard.yaml` into a Manual card in your dashboard.
The dashboard includes:
- Current tip display
- Tip history (last 5)
- Spoiler level controls
- Status indicators
- Action buttons

---

## Automations

See `lovelace/automations_example.yaml` for ready-to-use automations:
- Speak tips via TTS
- Change RGB light color when gaming starts/stops
- Send tips as mobile notifications
- Change spoiler level based on game

---

## Capture Agent CLI Options

### PC Agent (`capture_agent.py`)

| Argument | Default | Description |
|----------|---------|-------------|
| `--broker` | *(required)* | MQTT broker IP |
| `--port` | 1883 | MQTT port |
| `--user` | | MQTT username |
| `--password` | | MQTT password |
| `--client-id` | hostname | Unique client ID |
| `--interval` | 5 | Seconds between captures |
| `--quality` | 75 | JPEG quality (1-100) |
| `--resize` | 960x540 | Image dimensions |
| `--monitor` | 1 | Monitor index |
| `--detect-change` | off | Skip unchanged frames |

### Android Agent (`capture_agent_android.py`)

Same as PC agent, plus:

| Argument | Default | Description |
|----------|---------|-------------|
| `--device` | | ADB device serial or IP:port |

---

## Migration from v0.2/v0.3

- **Workers:** Old workers moved to `worker/legacy/`. They still work but are
  deprecated. Switch to the new capture agents for the best experience.
- **Config:** Existing config entries remain valid. New fields get defaults
  automatically -- no need to reconfigure.
- **Topics:** Old MQTT topics (`gaming_assistant/tip`, `gaming_assistant/status`,
  `gaming_assistant/gaming_mode`) are still supported in legacy mode.

---

## Troubleshooting

**Config flow error: 500 Internal Server Error**
-> Make sure the MQTT integration (Mosquitto) is fully set up **before** adding Gaming Assistant.
-> Delete `__pycache__` inside `custom_components/gaming_assistant/` and restart HA.

**Sensor stuck on "Waiting for tips..."**
-> Check that the capture agent is running and can reach the MQTT broker.
-> Verify MQTT is set up in Home Assistant (Mosquitto add-on).
-> Check that Ollama is running and reachable from HA.

**Ollama timeout**
-> The model may be loading for the first time. Wait 60s and try again.
-> Reduce image quality/size in the capture agent.

**No game detection (Desktop)**
-> Install `pywin32` on Windows and make sure the game is in the foreground.
-> Add your game's window title to `KNOWN_GAMES` in the capture agent.

**ADB screencap fails**
-> Run `adb devices` and check the device shows as "device" (not "unauthorized").
-> On the phone, accept the USB debugging prompt if shown.

---

## Changelog

### 0.4.0 -- "Thin Client Architecture"
- **BREAKING:** New capture agent workers replace the old all-in-one workers.
  Old workers moved to `worker/legacy/` and still work but are deprecated.
- **Added:** Central image processing pipeline in Home Assistant -- all AI logic
  now runs in HA, not on the gaming device.
- **Added:** Spoiler level system with 7 categories (story, items, enemies,
  bosses, locations, lore, mechanics) and 4 levels (none/low/medium/high).
- **Added:** Game-specific prompt packs for tailored coaching.
- **Added:** Tip history with per-game tracking and image deduplication.
- **Added:** New services: `process_image`, `set_spoiler_level`, `clear_history`.
- **Added:** History sensor for Lovelace dashboards.
- **Improved:** ~33% less network traffic (binary MQTT instead of Base64).
- **Improved:** Near-zero CPU usage on the gaming device (capture only).

### 0.3.0
- **Added:** Android worker (`worker/android_worker.py`) -- capture mobile game
  screenshots via ADB and analyze them with the same Ollama + MQTT pipeline.
- **Added:** `requirements-android.txt` for Android worker dependencies.

### 0.2.0
- **Fix:** MQTT subscriptions now retry with exponential backoff (up to 5 attempts).
- **Fix:** Config flow validates the Ollama connection.
- **Added:** `translations/en.json` and `translations/de.json`.

### 0.1.3
- Initial public release.

---

## License

MIT -- do whatever you want with it.


## Windows EXE Build (PC Capture Agent)

You can build a standalone `.exe` for the PC capture agent using PyInstaller:

```powershell
# from repository root
pip install pyinstaller -r worker/requirements-capture.txt
./scripts/build_windows_capture_agent.ps1
```

The output executable will be created in `dist/capture_agent.exe`.
