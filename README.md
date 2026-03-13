# Gaming Assistant for Home Assistant

A HACS custom integration that brings an AI-powered gaming coach into your smart home.
Uses a local Vision LLM (via [Ollama](https://ollama.com)) to analyze your game screen
and push tips directly into Home Assistant — no cloud, no subscriptions.

---

## How It Works

```
  Capture Source (choose one)
  ├── A) Capture Agent on Gaming PC (MQTT → HA)
  ├── B) Android Capture Agent via ADB (MQTT → HA)
  ├── C) HA Camera Entity (IP Webcam, etc.)
  │       └── service: capture_from_camera
  └── D) Legacy Worker (self-contained)
          │
     Home Assistant (Ollama on HA host or LAN)
     ├── Image Processing Pipeline
     │     ├── Deduplication
     │     ├── Game Detection → Prompt Pack
     │     ├── Spoiler Filtering
     │     ├── Conversation History
     │     └── Ollama Vision LLM
     ├── sensor.gaming_assistant_tip
     ├── sensor.gaming_assistant_status
     ├── sensor.gaming_assistant_history
     └── binary_sensor.gaming_mode
          │
     Automations
     ├── TTS (speak tip aloud)
     ├── RGB lights
     └── Notifications
```

---

## Requirements

| Component | Details |
|-----------|---------|
| Home Assistant | 2024.1+ with MQTT integration |
| MQTT Broker | Mosquitto (built-in HA add-on) |
| Ollama | Running locally or on LAN, with a vision model pulled |

### Capture Sources (choose one or more)

| Source | Use Case | Extra Requirements |
|--------|----------|-------------------|
| **Capture Agent** (PC) | Desktop gaming | Python 3.10+ on gaming PC |
| **Capture Agent** (Android) | Mobile gaming via ADB | ADB + Python on host |
| **HA Camera Entity** | Console/TV gaming via IP Webcam | Android phone with IP Webcam app, pointed at screen |
| **Legacy Worker** | Standalone (v0.3 compat) | Python 3.10+ on gaming PC |

### Recommended Vision Models

| Model | VRAM | Notes |
|-------|------|-------|
| `qwen2.5vl` | ~8 GB | Best quality, recommended |
| `llava` | ~8 GB | Good general purpose |
| `bakllava` | ~6 GB | Lighter option |
| `llama3.2-vision` | ~10 GB | Excellent, needs more VRAM |

---

## Installation

### Step 1 – HACS

1. Open HACS → Integrations → ⋮ → **Custom repositories**
2. Add this repo URL, type: **Integration**
3. Find **Gaming Assistant** in the list and click **Install**
4. Restart Home Assistant

### Step 2 – Add Integration

Go to **Settings → Devices & Services → Add Integration → Gaming Assistant**

Fill in:
- **Ollama Host** (e.g. `http://192.168.1.10:11434`)
- **Vision Model** (default: `qwen2.5vl`)
- **Interval** (seconds between analyses, default: 10)
- **Default Spoiler Level** (none / low / medium / high)

---

## Capture Sources

### Option A – Capture Agent on Gaming PC (recommended)

Thin client that only captures screenshots and sends them to HA via MQTT.
All intelligence runs in Home Assistant.

```bash
pip install -r worker/requirements-capture.txt

python worker/capture_agent.py \
  --broker 192.168.1.10 \
  --interval 5 \
  --detect-change
```

### Option B – Android Capture Agent via ADB

```bash
pip install -r worker/requirements-capture.txt

adb devices  # verify connection

python worker/capture_agent_android.py \
  --broker 192.168.1.10 \
  --interval 5
```

### Option C – HA Camera Entity (IP Webcam)

Point a phone running [IP Webcam](https://play.google.com/store/apps/details?id=com.pas.webcam) at your TV/monitor.
Set up the [IP Webcam Integration](https://www.home-assistant.io/integrations/android_ip_webcam/) in HA.

Then create an automation:

```yaml
- alias: "Gaming Assistant – Capture from IP Webcam"
  trigger:
    - platform: time_pattern
      seconds: "/10"  # Every 10 seconds
  condition:
    - condition: state
      entity_id: binary_sensor.gaming_mode
      state: "on"
  action:
    - service: gaming_assistant.capture_from_camera
      data:
        entity_id: camera.ip_webcam  # Your camera entity
        game_hint: "Elden Ring"       # Optional
        client_type: console
```

Or call the service manually from Developer Tools → Services:

```yaml
service: gaming_assistant.capture_from_camera
data:
  entity_id: camera.ip_webcam
  game_hint: "Zelda"
  client_type: console
```

### Option D – Legacy Worker (v0.3 compatible)

The old self-contained worker still works. It runs Ollama locally and
publishes tips directly via MQTT.

```bash
pip install -r worker/requirements.txt
python worker/gaming_assistant_worker.py --broker 192.168.1.10 --model qwen2.5vl
```

---

## Entities

| Entity | Description |
|--------|-------------|
| `sensor.gaming_assistant_tip` | Latest AI-generated gameplay tip |
| `sensor.gaming_assistant_status` | Worker status (idle / analyzing / error) |
| `sensor.gaming_assistant_history` | Tip count + recent tips in attributes |
| `binary_sensor.gaming_mode` | ON when a known game is detected |

## Services

| Service | Description |
|---------|-------------|
| `gaming_assistant.capture_from_camera` | Grab snapshot from a HA camera entity and analyze it |
| `gaming_assistant.process_image` | Analyze an image file or base64 data |
| `gaming_assistant.set_spoiler_level` | Change spoiler settings (per category, per game) |
| `gaming_assistant.clear_history` | Clear tip history |
| `gaming_assistant.analyze` | Trigger immediate analysis (legacy worker) |
| `gaming_assistant.start` | Resume the worker |
| `gaming_assistant.stop` | Pause the worker |

---

## Spoiler Control

Control how much the AI reveals per category:

```yaml
# Set all categories to "low" spoilers
service: gaming_assistant.set_spoiler_level
data:
  category: all
  level: low

# Allow full mechanics tips but no story spoilers for Elden Ring
service: gaming_assistant.set_spoiler_level
data:
  category: story
  level: none
  game: Elden Ring

service: gaming_assistant.set_spoiler_level
data:
  category: mechanics
  level: high
  game: Elden Ring
```

**Categories:** story, items, enemies, bosses, locations, lore, mechanics
**Levels:** none, low, medium, high

---

## Game-Specific Prompt Packs

Prompt packs provide game-specific coaching. Built-in packs:
- Elden Ring
- Dark Souls III
- Baldur's Gate 3
- Minecraft
- Zelda: Tears of the Kingdom

Add your own: copy `prompt_packs/_template.json` and fill in your game's details.

---

## Lovelace Dashboard

Copy the card from `lovelace/dashboard.yaml` into a Manual card in your dashboard.

---

## Automations

See `lovelace/automations_example.yaml` for ready-to-use automations:
- Speak tips via TTS
- Change RGB light color when gaming starts/stops
- Send tips as mobile notifications

---

## Troubleshooting

**Config flow error: 500 Internal Server Error**
→ Make sure the MQTT integration (Mosquitto) is fully set up **before** adding Gaming Assistant.
→ Delete `__pycache__` inside `custom_components/gaming_assistant/` and restart HA.

**Sensor stuck on "Waiting for tips..."**
→ Check that the capture agent is running and can reach the MQTT broker.
→ Verify MQTT is set up in Home Assistant (Mosquitto add-on).

**Ollama timeout**
→ The model may be loading for the first time. Wait 60 s and try again.
→ Reduce image size by lowering the `--quality` or `--resize` parameter.

**capture_from_camera fails**
→ Make sure the camera entity exists and is streaming.
→ Test in Developer Tools → Services first.

**ADB screencap fails**
→ Run `adb devices` and check the device shows as "device" (not "unauthorized").
→ On the phone, accept the USB debugging prompt if shown.

---

## Changelog

### 0.4.0
- **Architecture:** Moved all intelligence (LLM calls, prompt building, spoiler
  control) into the HA integration. Capture agents are now thin clients.
- **Added:** `capture_from_camera` service – grab snapshots from any HA camera
  entity (IP Webcam, Generic Camera, etc.) and analyze them. No external agent
  needed for console/TV gaming.
- **Added:** Spoiler control system with per-category, per-game settings.
- **Added:** Game-specific prompt packs (Elden Ring, Dark Souls III, BG3,
  Minecraft, Zelda: TotK) with custom coaching prompts.
- **Added:** Persistent conversation history with deduplication.
- **Added:** `sensor.gaming_assistant_history` for tip count and recent tips.
- **Added:** `process_image`, `set_spoiler_level`, `clear_history` services.
- **Added:** Thin client capture agents (`capture_agent.py`, `capture_agent_android.py`).
- **Compat:** Legacy v0.3 workers still work via MQTT tip/mode/status topics.

### 0.3.0
- **Added:** Android worker (`worker/android_worker.py`) – capture mobile game
  screenshots via ADB and analyze them with the same Ollama + MQTT pipeline.
- **Added:** `requirements-android.txt` for Android worker dependencies.

### 0.2.0
- **Fix:** MQTT subscriptions now retry with exponential backoff (up to 5 attempts).
- **Fix:** Config flow validates the Ollama connection.
- **Added:** `translations/en.json` and `translations/de.json`.
- **Added:** `.gitignore`, `LICENSE` (MIT).

### 0.1.3
- Initial public release.

---

## License

MIT
