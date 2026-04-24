# Gaming Assistant – FAQ & Troubleshooting

## Setup

### Which capture agent should I use?

| Setup | Agent |
|-------|-------|
| Windows / Linux / macOS PC | `worker/capture_agent.py` |
| Android phone / tablet (ADB) | `worker/capture_agent_android.py` |
| Android TV / Google TV | `worker/capture_agent_android_tv.py` |
| IP Webcam app / JPEG endpoint | `worker/capture_agent_ipcam.py` |
| Console + USB HDMI capture dongle on a Pi | `worker/capture_agent_bridge.py` |

### Do I need a GPU?

Only if you want a **local vision** model. Small text-only backends
(DeepSeek, Groq) run comfortably on a Raspberry Pi – they receive game
state + context descriptions instead of raw images.

### Which MQTT topics do I need to allow?

- `gaming_assistant/#` is sufficient for the integration.
- Capture agents publish to `gaming_assistant/{client_id}/image`,
  `gaming_assistant/{client_id}/meta`, and set a Last Will on
  `gaming_assistant/{client_id}/status`.

## "No tips" troubleshooting

1. **Is the capture agent connected?** Check the `Gaming Assistant
   Workers` sensor. If the worker is listed but `status == offline`,
   the MQTT broker lost it (Last Will fired).
2. **Is MQTT wired up?** The integration requires the HA MQTT
   integration to be configured. Restart after changing broker config.
3. **Is the model reachable?** Open the HA sidebar panel; the active
   model chip shows `—` when the backend can't be reached.
4. **Look at `Gaming Assistant Last Error`.** Since v0.13 this sensor
   exposes the exact exception message from the last failed analysis.
5. **Check the HA logs** for `gaming_assistant` entries. Dedup hits
   show up as debug messages.

## "MQTT connected but no image"

- Confirm the capture agent prints `Sent frame (xx KB)` every interval.
- In HA, the `image.gaming_assistant_last_frame` entity (v0.12+) shows
  the most recently received frame. An empty picture entity means the
  image topic is not being delivered to the integration.
- Some MQTT brokers strip binary payloads when `retain=true` is used
  with weird ACLs. Publish images with `retain=false` (the agents already
  do this).

## "Model timeout"

- Vision models on Ollama can be slow; bump `CONF_TIMEOUT` in the
  integration options.
- For small models (`:3b`, `:1b`), the integration auto-switches to
  **compact mode** prompts. If you see garbled JSON or ignored
  instructions, keep compact mode enabled.
- The `Gaming Assistant Latency` sensor shows the last analysis time in
  seconds – a rising trend usually means GPU contention.

## Spoiler profiles

- Global spoiler levels apply to every game unless you set a per-game
  profile via `gaming_assistant.set_spoiler_profile` (service) or the
  Lovelace selector.
- Prompt packs can ship `spoiler_defaults`. Those are used as a
  one-time baseline: if you later change a category manually, your
  preference wins.

## Prompt packs

### My custom pack doesn't load

Since v0.13 the loader validates packs against
`prompt_packs/manifest.json`. Common reasons for rejection:

- `id` is not snake_case (must match `^[a-z0-9_]+$`).
- `keywords` is missing or empty.
- `spoiler_defaults` has a level other than `none|low|medium|high`.

Check Home Assistant's log for a line such as
`Prompt pack xyz.json is invalid: <reason>`.

### Where do downloaded packs live?

`<config>/gaming_assistant/prompt_packs/`. Packs in this directory
**override** bundled ones with the same `id`, so a user override wins
over the shipped default.

## Performance tuning

- Reduce capture resolution (`--resize 720x405`) on weak networks or
  Raspberry Pi capture.
- Enable `--detect-change` to suppress identical frames (saves broker
  bandwidth and skips redundant LLM calls).
- Pick `qwen2.5vl:7b` or `llama3.2-vision:11b` for the best
  quality/latency trade-off on an RTX 3060-class GPU.

## Safety

### Can the AI take over my keyboard?

No. The integration never sends OS-level input. The optional Agent
Mode (Phase 5) uses `vgamepad` – a virtual Xbox controller – so the
model can press A/B/LT/RT only. `PromptBuilder.parse_action()`
whitelists exactly which buttons are allowed.

### Does HA send my game footage to the cloud?

Only if you configure a cloud backend (`openai`, `gemini`, …) **and**
`CONF_LLM_ALLOW_IMAGES` is enabled. Text-only providers never receive
frames. Local backends (`ollama`, `lmstudio`) keep everything on your
network.
