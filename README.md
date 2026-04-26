# Gaming Assistant for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/Chance-Konstruktion/ha-gaming-assistant)](https://github.com/Chance-Konstruktion/ha-gaming-assistant/releases)
[![Tests](https://github.com/Chance-Konstruktion/ha-gaming-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/Chance-Konstruktion/ha-gaming-assistant/actions)

A HACS custom integration that brings an AI-powered gaming coach into your smart home.
Uses a local Vision LLM (via [Ollama](https://ollama.com)) or cloud AI (GPT-4o, Gemini, DeepSeek)
to analyze your game screen and push tips directly into Home Assistant.

---

## Architecture

v0.11 uses a **Thin Client Architecture**: the gaming device only captures and sends
screenshots. All intelligence runs in Home Assistant.

```
Gaming PC / Android / Android TV / Tabletop Camera (Capture Agent)
  └── Screenshot capture + JPEG compress + MQTT publish (binary image)
         │
    Home Assistant (the "Brain")
      ├── MQTT Image Listener (bounded queue, backpressure)
      ├── Image Deduplication (hash)
      ├── Game Detection (via client metadata)
      ├── Game State Engine (structured state tracking across frames)
      ├── Trend Detection (health declining, phase changes, momentum)
      ├── History Manager (per game, JSONL)
      ├── Spoiler Level System (per-game profiles, 7 categories)
      ├── Assistant Modes (coach / coplay / opponent / analyst)
      ├── Prompt Pack Loader (26 games: video + tabletop + card)
      ├── Dynamic Prompt Builder (compact mode for small models)
      ├── LLM Backend (Ollama / GPT-4o / Gemini / DeepSeek / LM Studio / Groq)
      ├── Camera Watcher (continuous HA camera monitoring)
      ├── Conversation Agent (HA Assist voice control)
      └── Sensors + Entities + Services
         │
    Optional: YOLO Worker (external, GPU/NPU)
      ├── Real-time object detection via MQTT
      ├── Supports: CUDA, NCNN (RPi), Hailo-8L, TFLite
      └── Feeds detections into Game State Engine
         │
    Automations / Voice
      ├── HA Assist ("switch mode to opponent", free-form questions)
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
| Capture Agent | Windows / Linux / macOS / Android / Android TV |
| AI Backend | Ollama (local) *or* cloud API (chatGPT, Gemini, DeepSeek, Grok) |

### Supported LLM Backends

| Backend | Type | Vision | Notes |
|---------|------|--------|-------|
| **Ollama** | Local | Yes | Default, no API key needed |
| **LM Studio** | Local | Yes | OpenAI-compatible |
| **OpenAI GPT-4o** | Cloud | Yes | Best quality, paid |
| **Google Gemini** | Cloud | Yes | Free tier available |
| **DeepSeek** | Cloud | No* |  cheap |
| **Groq** | Cloud | No* | Ultra-fast inference |

> \* Text-only backends never receive images — they get game state + context
> descriptions instead. Great for Raspberry Pi setups without GPU.

### Recommended Local Vision Models (Ollama)

| Model | VRAM | Notes |
|-------|------|-------|
| `qwen2.5vl` | ~8 GB | Best quality, recommended |
| `llava` | ~8 GB | Good general purpose |
| `bakllava` | ~6 GB | Lighter option |
| `llama3.2-vision` | ~10 GB | Excellent, needs more VRAM |
| `ministral:3b` | ~2 GB | Lightweight, good for low-VRAM setups |

> **Raspberry Pi / No GPU?** Use a cloud backend (Gemini free tier or DeepSeek)
> — the integration runs on any hardware that can run Home Assistant.

---

## Installation

### Step 1 -- HACS

1. Open HACS -> Integrations -> ... -> **Custom repositories**
2. Add this repo URL, type: **Integration**
3. Find **Gaming Assistant** in the list and click **Install**
4. Restart Home Assistant

### Step 2 -- Add Integration

Go to **Settings -> Devices & Services -> Add Integration -> Gaming Assistant**

The config flow has 6 steps:
1. **LLM Provider** -- Choose your AI backend (Ollama, chatGPT, Gemini, DeepSeek, etc.)
2. **Connection** -- Host URL + API key (if needed)
3. **Model & Interval** -- Choose a vision model, capture interval, and timeout
4. **Spoiler Level** -- Default spoiler level (none/low/medium/high)
5. **Camera** -- Optionally select a HA camera to auto-watch
6. **Voice Announcements** -- TTS engine, speaker, and auto-announce toggle

> **Note:** The config flow validates the connection to your AI backend.
> Cloud providers require an API key.

### Step 3 -- Capture Agent Setup

#### PC Capture Agent

```bash
# Install dependencies (much lighter than before -- no requests/ollama needed)
pip install -r worker/requirements-capture.txt

# Windows: also install for game detection
pip install pywin32

# Start the capture agent
python worker/capture_agent.py \
  --broker 192.168.1.10 \
  --client-id gaming-pc \
  --interval 5 \
  --quality 75
```

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


#### Android TV / Google TV Capture Agent

```bash
pip install -r worker/requirements-capture.txt

# Enable developer options on Android TV, then pair via ADB
adb pair 192.168.1.100:<pairing-port>
adb connect 192.168.1.100:5555

# Start the Android TV capture agent
python worker/capture_agent_android_tv.py \
  --broker 192.168.1.10 \
  --device 192.168.1.100:5555 \
  --client-id livingroom-tv \
  --interval 5
```

For streaming apps (Steam Link, GeForce NOW, Xbox Game Pass) use `--game-hint`:

```bash
python worker/capture_agent_android_tv.py \
  --broker 192.168.1.10 \
  --device 192.168.1.100:5555 \
  --game-hint "Elden Ring"
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
  --quality 75
```

Tip: point your phone camera at the TV/monitor and lock focus/exposure for more stable tips.

#### Windows GUI App (easiest setup)

For non-technical users: download the single `.exe` and run it -- no Python needed.

**Build from source:**

```bat
cd worker
build_exe.bat
```

The resulting `GamingAssistant.exe` includes a GUI where you enter broker IP,
select monitor, and start/stop capture with a button. Settings are saved to `config.ini`.

---

## Features

### Assistant Modes

Switch between 4 coaching styles directly from the dashboard using
`select.gaming_assistant_assistant_mode`:

| Mode | Description |
|------|-------------|
| **Coach** | Tips and strategy to help the player win (default) |
| **Co-Player** | Collaborative teammate, suggests joint moves |
| **Opponent** | Plays competitively, announces its own moves |
| **Analyst** | Neutral commentary, doesn't take sides |

Change the mode via the dropdown in your dashboard, or via automation:

```yaml
action: select.select_option
target:
  entity_id: select.gaming_assistant_assistant_mode
data:
  option: opponent
```

### Tabletop Game Support

Point a camera at your board game and get live coaching. Built-in prompt packs
for **Chess**, **Poker**, **Settlers of Catan**, and **UNO**.

Use the `watch_camera` service for continuous monitoring:

```yaml
service: gaming_assistant.watch_camera
data:
  entity_id: camera.board_game_cam
  game_hint: "Chess"
  client_type: tabletop
  interval: 10
```

Stop watching:

```yaml
service: gaming_assistant.stop_watch_camera
data:
  entity_id: camera.board_game_cam  # omit to stop all watchers
```

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

### Ask Mode

Ask the assistant a direct question -- with or without a screenshot for context:

```yaml
service: gaming_assistant.ask
data:
  question: "How do I beat this boss?"
  game_hint: "Elden Ring"
```

With a screenshot:

```yaml
service: gaming_assistant.ask
data:
  question: "What item is on the ground here?"
  image_path: /config/www/screenshot.jpg
```

### Per-Game Spoiler Profiles

Set all spoiler categories for a game at once:

```yaml
service: gaming_assistant.set_spoiler_profile
data:
  game: "Elden Ring"
  level: none
```

Profiles persist across HA restarts. Clear with:

```yaml
service: gaming_assistant.set_spoiler_profile
data:
  game: "Elden Ring"
  clear: true
```

### Camera Capture

Use any HA camera entity (IP Webcam, Generic Camera, etc.) as image source -- perfect for console gaming:

```yaml
service: gaming_assistant.capture_from_camera
data:
  entity_id: camera.ip_webcam
  game_hint: "Zelda"
  client_type: console
```

### Voice Announcements (TTS)

Have tips read aloud by your Home Assistant voice assistant (e.g. Piper):

**Manual announce:**

```yaml
service: gaming_assistant.announce
data:
  tts_entity: tts.piper
  media_player_entity_id: media_player.living_room
```

**Auto-announce:** Enable `switch.gaming_assistant_auto_announce` to have every
new tip automatically spoken. Configure the TTS engine and speaker in the
integration settings (Step 5 of the config flow or Options).

**Event-based automations:** Every new tip fires a `gaming_assistant_new_tip`
event with `tip`, `game`, `client_id`, and `assistant_mode` data. Use this in
custom automations:

```yaml
trigger:
  - platform: event
    event_type: gaming_assistant_new_tip
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Gaming Tip ({{ trigger.event.data.game }})"
      message: "{{ trigger.event.data.tip }}"
```

### Session Summaries

After a gaming session ends (5 minutes of inactivity), the integration can
automatically generate a concise summary of the session's key insights.

**Manual summary:**

```yaml
service: gaming_assistant.summarize_session
data:
  game: "Elden Ring"  # optional, uses current game if empty
```

**Auto-summary:** Enable `switch.gaming_assistant_auto_summary` to automatically
summarize every session that has 3+ tips. The summary is stored in
`sensor.gaming_assistant_session_summary`.

**Session-end event:** When a session ends, a `gaming_assistant_session_ended`
event fires with `game`, `tip_count`, and `summary` data.

### Voice Control (HA Assist)

The Gaming Assistant registers as a native **conversation agent** for Home
Assistant's Assist pipeline. This means you can talk to it through any
voice-enabled device (e.g. Home Assistant Voice PE, phone app, or browser).

**Setup:**
1. Go to **Settings → Voice assistants**
2. Create or edit a voice assistant
3. Select **Gaming Assistant** as the conversation agent

**Supported voice commands:**

| Command (EN) | Command (DE) | Action |
|-------------|-------------|--------|
| "switch mode to opponent" | "wechsel modus auf gegner" | Change assistant mode |
| "set spoiler to low" | "ändere spoiler auf niedrig" | Change spoiler level |
| "start" | "starte" | Start capture/monitoring |
| "stop" | "stoppe" | Stop capture/monitoring |
| "current tip" | "aktueller tipp" | Read back the latest tip |
| "session summary" | "zusammenfassung" | Read the session summary |
| "analyze" | "analysiere" | Trigger immediate analysis |

Any input that doesn't match a command is forwarded to Ollama as a free-form
question -- so "How do I beat this boss?" or "Was ist mein nächster Zug?"
works naturally.

### Game-Specific Prompt Packs

The integration includes prompt packs for popular games that provide tailored
coaching.

**Video games (18):** Elden Ring, Dark Souls III, Baldur's Gate 3,
Minecraft, Zelda: TotK, Zelda: BotW, Stardew Valley, Hades, Mario Kart,
CS2, League of Legends, Valorant, Fortnite, Rocket League, FIFA/EA FC,
Civilization VI, Cyberpunk 2077, The Witcher 3, Diablo IV.

**Card/Strategy games (4):** Hearthstone, MTG Arena, Among Us.

**Tabletop games (4):** Chess, Poker, Settlers of Catan, UNO.

Community packs are auto-downloaded from
[`Chance-Konstruktion/ha-gaming-assistant-prompts`](https://github.com/Chance-Konstruktion/ha-gaming-assistant-prompts)
and hot-reloaded via the `gaming_assistant.refresh_prompt_packs` service.

To write your own pack, see **[`docs/pack_authoring.md`](docs/pack_authoring.md)**
— covers the manifest schema, validation rules, local testing, and the
submission workflow. The bundled `_template.json` is a copy-paste starting
point.

### Tip History

Tips are stored per game with image deduplication. The history sensor shows:
- Number of tips this session
- Last 5 tips
- Current game name
- Active client ID

Clear history via `gaming_assistant.clear_history`.

---

## Entities

### Conversation

| Entity | Type | Description |
|--------|------|-------------|
| `conversation.gaming_assistant` | Conversation | Voice control via HA Assist (select as conversation agent) |

### Controls (adjustable from the dashboard)

| Entity | Type | Description |
|--------|------|-------------|
| `select.gaming_assistant_assistant_mode` | Select | Coach / Co-Player / Opponent / Analyst |
| `select.gaming_assistant_spoiler_level` | Select | Default spoiler level (None / Low / Medium / High) |
| `number.gaming_assistant_interval` | Number (slider) | Capture/analysis interval (5–120 s) |
| `number.gaming_assistant_timeout` | Number (slider) | Analysis timeout (10–300 s) |
| `switch.gaming_assistant_auto_announce` | Switch | Auto-announce new tips via TTS |
| `switch.gaming_assistant_auto_summary` | Switch | Auto-summarize sessions on end |

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.gaming_assistant_tip` | Latest AI tip (attributes: game, worker_status) |
| `sensor.gaming_assistant_status` | Status (idle / analyzing / error) |
| `sensor.gaming_assistant_history` | Tip count + recent tips as attributes |
| `sensor.gaming_assistant_latency` | Duration of last analysis (seconds) |
| `sensor.gaming_assistant_error_count` | Errors since startup |
| `sensor.gaming_assistant_frames_processed` | Total frames analyzed |
| `sensor.gaming_assistant_last_analysis` | Timestamp of last successful analysis |
| `sensor.gaming_assistant_active_watchers` | Number of active camera watchers |
| `sensor.gaming_assistant_registered_workers` | Auto-discovered workers via MQTT |
| `sensor.gaming_assistant_session_summary` | Last session summary (attributes: game, timestamp) |
| `binary_sensor.gaming_mode` | ON when a game is detected |

### Image (Debug)

| Entity | Description |
|--------|-------------|
| `image.gaming_assistant_last_frame` | Last received frame from any capture client (JPEG). Useful for verifying the image pipeline. Attributes: client_id, timestamp, game. |

## Services

| Service | Description |
|---------|-------------|
| `gaming_assistant.analyze` | Trigger an immediate screenshot analysis |
| `gaming_assistant.start` | Resume the capture agent |
| `gaming_assistant.stop` | Pause the capture agent |
| `gaming_assistant.process_image` | Manually analyze an image (path or base64) |
| `gaming_assistant.ask` | Ask a direct question (optional image context) |
| `gaming_assistant.set_spoiler_level` | Change spoiler settings per category/game |
| `gaming_assistant.set_spoiler_profile` | Set/clear a per-game spoiler profile |
| `gaming_assistant.clear_history` | Clear tip history |
| `gaming_assistant.capture_from_camera` | One-shot capture from a HA camera entity |
| `gaming_assistant.watch_camera` | Continuous camera monitoring at interval |
| `gaming_assistant.stop_watch_camera` | Stop camera watcher(s) |
| `gaming_assistant.announce` | Speak current tip (or custom message) via TTS |
| `gaming_assistant.summarize_session` | Generate a summary of the last gaming session |
| `gaming_assistant.refresh_prompt_packs` | Re-download prompt packs from the community repo and hot-reload |

> **Note:** Assistant mode, spoiler level, interval, and timeout are now
> controlled via entities (see above) instead of services.

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
| `--game-hint` | | Manual game name (useful on Wayland) |
| `--detect-change` | off | Skip unchanged frames |

> **Linux note:** The PC agent now uses `xprop` for window title detection on
> X11. On Wayland, auto-detection is not available -- use `--game-hint` instead.

### Android Agent (`capture_agent_android.py`)

Same as PC agent, plus:

| Argument | Default | Description |
|----------|---------|-------------|
| `--device` | | ADB device serial or IP:port |

### Android TV Agent (`capture_agent_android_tv.py`)

Same as Android agent, plus:

| Argument | Default | Description |
|----------|---------|-------------|
| `--game-hint` | | Manual game name for streaming apps |

### IP Webcam Agent (`capture_agent_ipcam.py`)

Polls a JPEG snapshot URL (Android IP Webcam app, iOS camera apps,
any MJPEG-friendly device) and publishes frames over MQTT.

| Argument | Default | Description |
|----------|---------|-------------|
| `--url` | *(required)* | Snapshot URL, e.g. `http://192.168.1.42:8080/shot.jpg` |
| `--interval` | 5 | Seconds between captures |
| `--quality` | 75 | JPEG quality (1-100) |
| `--resize` | 960x540 | Image dimensions |
| `--auth-user` / `--auth-password` | | Optional HTTP basic auth |
| `--timeout` | 8 | HTTP timeout in seconds |
| `--game-hint` | | Manual game name |
| `--detect-change` | off | Skip unchanged frames |

On HTTP errors the agent now backs off exponentially (2s, 4s, 8s, …,
capped at 60s) and exits only after 20 consecutive failures.

### HDMI Bridge Agent (`capture_agent_bridge.py`)

Captures from a V4L2 device (e.g. a USB HDMI dongle on a Raspberry Pi)
so that game consoles can be analyzed without installing anything on
the console itself.

```bash
pip install opencv-python
python capture_agent_bridge.py --broker 192.168.1.10 --device /dev/video0
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--device` | `/dev/video0` | V4L2 device path or index |
| `--capture-resolution` | 1280x720 | Requested input resolution |
| `--resize` | 960x540 | Output size for MQTT |
| `--quality` | 70 | JPEG quality (1-100) |
| `--interval` | 2 | Seconds between frames |
| `--client-type` | `console` | Reported source type |
| `--game-hint` | | Manual game name |
| `--detect-change` | off | Skip unchanged frames |

A systemd example is included at
`worker/systemd/gaming-assistant-bridge.service` — adjust broker IP,
device path, and the user before enabling.

### PC Overlay HUD (`tools/overlay_pc.py`)

Optional, display-only. Subscribes to `gaming_assistant/tip` over MQTT
and renders the latest tip in an always-on-top transparent window.
Press **F8** to toggle, **Esc** to quit. See `tools/README.md` for
details.

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

## License

MIT -- do whatever you want with it.
