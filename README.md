# 🎮 Gaming Assistant for Home Assistant

A HACS custom integration that brings an AI-powered gaming coach into your smart home.
Uses a local Vision LLM (via [Ollama](https://ollama.com)) to analyze your game screen
and push tips directly into Home Assistant — no cloud, no subscriptions.

---

## How It Works

```
Gaming PC
  ├── Screenshot (every N seconds)
  ├── Frame change detection (skip if nothing changed)
  └── Vision LLM via Ollama
          │
         MQTT
          │
   Home Assistant
     ├── sensor.gaming_assistant_tip
     ├── sensor.gaming_assistant_status
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
| Gaming PC | Windows / Linux / macOS with Python 3.10+ |
| Ollama | Running locally, with a vision model pulled |

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
- **Ollama Host** (e.g. `http://192.168.1.10:11434` if Ollama runs on your gaming PC)
- **Vision Model** (default: `qwen2.5vl`)
- **Interval** (seconds between analyses, default: 10)

> **Note:** The config flow validates the Ollama connection. If the server is
> unreachable you'll see an error and can correct the URL before proceeding.

### Step 3 – Worker Setup (Gaming PC)

```bash
# Install dependencies
pip install -r worker/requirements.txt

# Windows: also install for game detection
pip install pywin32

# Start the worker
python worker/gaming_assistant_worker.py \
  --broker 192.168.1.10 \
  --ollama http://localhost:11434 \
  --model qwen2.5vl \
  --interval 10
```

---

## Entities

| Entity | Description |
|--------|-------------|
| `sensor.gaming_assistant_tip` | Latest AI-generated gameplay tip |
| `sensor.gaming_assistant_status` | Worker status (idle / analyzing / error) |
| `binary_sensor.gaming_mode` | ON when a known game is detected |

## Services

| Service | Description |
|---------|-------------|
| `gaming_assistant.analyze` | Trigger an immediate screenshot analysis |
| `gaming_assistant.start` | Resume the worker |
| `gaming_assistant.stop` | Pause the worker |

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

## Windows Autostart

To start the worker automatically on Windows boot:

1. Run: `pyinstaller worker/gaming_assistant_worker.py --onefile`
2. Copy the generated `.exe` to `shell:startup`
3. Create a shortcut with your `--broker` argument

---

## Troubleshooting

**Config flow error: 500 Internal Server Error**
→ Make sure the MQTT integration (Mosquitto) is fully set up **before** adding Gaming Assistant.
→ Delete `__pycache__` inside `custom_components/gaming_assistant/` and restart HA.

**Sensor stuck on "Waiting for tips..."**
→ Check that the worker is running and can reach the MQTT broker.
→ Verify MQTT is set up in Home Assistant (Mosquitto add-on).

**Ollama timeout**
→ The model may be loading for the first time. Wait 60 s and try again.
→ Reduce image size by lowering the `resize` parameter in the worker.

**No game detection**
→ Install `pywin32` on Windows and make sure the game is in the foreground.
→ Add your game's window title to `KNOWN_GAMES` in the worker script.

---

## Changelog

### 0.2.0
- **Fix:** MQTT subscriptions now retry with exponential backoff (up to 5 attempts)
  instead of failing immediately when the broker isn't ready yet.
- **Fix:** Config flow validates the Ollama connection and shows a clear error
  when the server is unreachable.
- **Fix:** Services are registered only once and cleaned up only when the last
  config entry is unloaded (prevents errors with multiple entries).
- **Added:** `translations/en.json` and `translations/de.json` for proper
  HA localisation support.
- **Added:** `.gitignore`, `LICENSE` (MIT).

### 0.1.3
- Initial public release.

---

## License

MIT – do whatever you want with it. 🎮
