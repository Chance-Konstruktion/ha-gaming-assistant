# Gaming Assistant for Home Assistant

A HACS custom integration that brings an AI-powered gaming coach into your smart home.
Uses a local Vision LLM (via [Ollama](https://ollama.com)) to analyze your game screen
and push tips directly into Home Assistant -- no cloud, no subscriptions.

---

## Architecture

v0.8 uses a **Thin Client Architecture**: the gaming device only captures and sends
screenshots. All intelligence runs in Home Assistant.

```
Gaming PC / Android / Tabletop Camera (Capture Agent)
  └── Screenshot capture + JPEG compress + MQTT publish (binary image)
         │
    Home Assistant (the "Brain")
      ├── MQTT Image Listener
      ├── Image Deduplication (hash)
      ├── Game Detection (via client metadata)
      ├── History Manager (per game, JSONL)
      ├── Spoiler Level System
      ├── Assistant Modes (coach / coplay / opponent / analyst)
      ├── Prompt Pack Loader (video games + tabletop)
      ├── Dynamic Prompt Builder
      ├── Camera Watcher (continuous HA camera monitoring)
      ├── Conversation Agent (HA Assist voice control)
      ├── Ollama Vision LLM Call
      └── Sensors + Entities + Services
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
| Gaming PC | Windows / Linux / macOS with Python 3.10+ |
| Ollama | Running locally or on a machine reachable from HA |

### Recommended Vision Models

| Model | VRAM | Notes |
|-------|------|-------|
| `qwen2.5vl` | ~8 GB | Best quality, recommended |
| `llava` | ~8 GB | Good general purpose |
| `bakllava` | ~6 GB | Lighter option |
| `llama3.2-vision` | ~10 GB | Excellent, needs more VRAM |
| `ministral:3b` | ~2 GB | Lightweight, good for low-VRAM setups |

> **Small models (3B):** Models like Ministral 3B work but produce shorter,
> less detailed tips. The integration automatically keeps prompts concise.
> Best for simple games (board games, card games) or when hardware is limited.

---

## Installation

### Step 1 -- HACS

1. Open HACS -> Integrations -> ... -> **Custom repositories**
2. Add this repo URL, type: **Integration**
3. Find **Gaming Assistant** in the list and click **Install**
4. Restart Home Assistant

### Step 2 -- Add Integration

Go to **Settings -> Devices & Services -> Add Integration -> Gaming Assistant**

The config flow has 5 steps:
1. **Ollama Host** -- URL of your Ollama server
2. **Model & Interval** -- Choose a vision model, capture interval, and timeout
3. **Spoiler Level** -- Default spoiler level (none/low/medium/high)
4. **Camera** -- Optionally select a HA camera to auto-watch
5. **Voice Announcements** -- TTS engine, speaker, and auto-announce toggle

> **Note:** The config flow validates the Ollama connection. If the server is
> unreachable you'll see an error and can correct the URL.

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

**Video games:** Elden Ring, Dark Souls III, Baldur's Gate 3,
Minecraft, Zelda: Tears of the Kingdom, Zelda: Breath of the Wild,
Stardew Valley, Hades, Mario Kart.

**Tabletop games:** Chess, Poker, Settlers of Catan, UNO.

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

### 0.9.1 -- "Voice Control"
- **Added:** Conversation agent for Home Assistant Assist -- control the Gaming
  Assistant entirely by voice. Registered as a native HA conversation entity so
  it appears in the Assist pipeline settings.
- **Added:** Voice commands (English & German) for:
  - Mode switching ("switch mode to opponent" / "wechsel modus auf gegner")
  - Spoiler control ("set spoiler to low" / "ändere spoiler auf niedrig")
  - Start/stop ("start" / "stoppe")
  - Current tip ("current tip" / "aktueller tipp")
  - Session summary ("session summary" / "zusammenfassung")
  - Screenshot analysis ("analyze" / "analysiere")
- **Added:** Free-form questions via Assist are forwarded to the Ollama-backed
  ask pipeline -- e.g. "How do I beat this boss?" works as natural conversation.
- **Fixed:** Windows batch files (`gaming_assistant.bat`, `build_exe.bat`) now
  reliably find Python using py launcher, python3, and common install paths
  instead of failing on Windows Store app aliases.

### 0.9.0 -- "Voice & Language"
- **Added:** `gaming_assistant.announce` service -- speak tips via any HA TTS
  engine (e.g. Piper) to any media player/speaker.
- **Added:** `switch.gaming_assistant_auto_announce` entity -- toggle automatic
  TTS announcements for every new tip.
- **Added:** `gaming_assistant_new_tip` event fired on every new tip, carrying
  `tip`, `game`, `client_id`, and `assistant_mode` data for custom automations.
- **Added:** Config flow step 5 for TTS setup (engine, speaker, auto-announce).
- **Added:** TTS settings in options flow for reconfiguration.
- **Added:** Automatic language detection from Home Assistant language settings.
  The AI now responds in the user's configured language (German, French, etc.).
- **Added:** Session tracking with automatic end detection (5 min inactivity).
- **Added:** `gaming_assistant.summarize_session` service -- generate a 2-3
  sentence summary of the last gaming session.
- **Added:** `switch.gaming_assistant_auto_summary` entity -- auto-generate
  session summaries when a session ends (requires 3+ tips).
- **Added:** `sensor.gaming_assistant_session_summary` -- shows the last
  session summary with game name and timestamp as attributes.
- **Added:** `gaming_assistant_session_ended` event for session-end automations.
- **Added:** 4 new prompt packs: Stardew Valley, Hades, Breath of the Wild,
  Mario Kart.
- **Improved:** Prompt Builder supports compact prompts for small models (3B).
- **Changed:** Config flow updated to 5 steps (added TTS step).

### 0.8.0 -- "Dashboard Entities"
- **Added:** Select entity for assistant mode -- switch between Coach,
  Co-Player, Opponent, and Analyst directly from the dashboard dropdown.
- **Added:** Select entity for default spoiler level (None/Low/Medium/High).
- **Added:** Number entities (sliders) for analysis interval (5–120 s) and
  timeout (10–300 s) -- adjustable live without reconfiguring.
- **Added:** Workers sensor showing auto-discovered MQTT workers.
- **Added:** Full German and English translations for all new entities
  including state labels.
- **Removed:** `gaming_assistant.set_mode` service (replaced by select entity).
- **Changed:** Options flow simplified to model and camera only. Interval,
  timeout, and spoiler level are now controlled via entities.
- **Changed:** Config flow updated to 4 steps (added camera step).

### 0.7.0 -- "Camera & Workers"
- **Added:** Config flow step 4 for camera entity selection (auto-watch on setup).
- **Added:** Worker auto-registration via MQTT.
- **Added:** Camera entity configurable in options flow.

### 0.6.0 -- "Tabletop & Modes"
- **Added:** Assistant modes -- coach, coplay, opponent, analyst -- via
  `gaming_assistant.set_mode` service. Each mode changes how the AI interacts
  with the game (helping, competing, or commentating).
- **Added:** Tabletop game prompt packs for Chess, Poker, Settlers of Catan,
  and UNO. Point a camera at your board game for live coaching.
- **Added:** `watch_camera` / `stop_watch_camera` services for continuous
  HA camera monitoring at configurable intervals (great for tabletop games).
- **Added:** `client_type` parameter (pc, android, android_tv, console,
  tabletop) for context-aware prompts.
- **Added:** Windows GUI app (`gaming_assistant_gui.py`) with `build_exe.bat`
  for single-file .exe deployment -- no Python needed on the gaming PC.
- **Added:** Windows launcher (`install_and_run.bat`) for easy first-time setup.
- **Added:** 5 diagnostic sensors: latency, error count, frames processed,
  last analysis timestamp, active watchers.
- **Improved:** History storage switched from JSON to JSONL for better
  performance and append-friendly writes.
- **Improved:** Configurable Ollama timeout.

### 0.5.0 -- "Ask Mode & Persistence"
- **Added:** Ask mode -- ask the assistant direct questions via `gaming_assistant.ask`
  service, optionally with an image for context.
- **Added:** Per-game spoiler profiles via `gaming_assistant.set_spoiler_profile`.
  Profiles persist across HA restarts (stored as JSON).
- **Added:** Camera capture service `gaming_assistant.capture_from_camera` --
  use any HA camera entity as image source (great for consoles).
- **Added:** X11 window title detection via `xprop` (Linux).
  `detect_window_title()` now tries Windows API, then X11, with graceful fallback.
- **Added:** Android TV now detects foreground app package via `dumpsys window`.
- **Improved:** CI checks all Python files (not just hardcoded list of 4).
- **Improved:** 43 unit tests covering capture agents, prompt builder, and spoiler system.
- **Fixed:** Branding -- correct codeowners, repo URLs, copyright.

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
