# Gaming Assistant – Architecture Overview

This document describes how the pieces of the Gaming Assistant integration
fit together. It is a companion to `README.md`; see the README for setup
instructions and `ROADMAP.md` for the full roadmap.

## Thin Client Architecture

The integration follows a **thin-client** model: every gaming device just
captures a frame and publishes it over MQTT. All reasoning runs inside
Home Assistant. This keeps capture agents small and portable across
Windows, Linux, macOS, Android, Android TV, and Raspberry Pi / HDMI bridges.

```
┌─────────────────────────────────────────────────────────────────┐
│ Capture (one or many)                                           │
│   PC  |  Android  |  Android TV  |  IP Webcam  |  HDMI Bridge   │
│                                                                 │
│   capture_agent.py / capture_agent_android.py                   │
│   capture_agent_android_tv.py / capture_agent_ipcam.py          │
│   capture_agent_bridge.py   (NEW, Raspberry Pi HDMI)            │
│                                                                 │
│   resize → JPEG → MQTT publish                                  │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼  MQTT:  gaming_assistant/{client_id}/image
                         │         gaming_assistant/{client_id}/meta
┌─────────────────────────────────────────────────────────────────┐
│ Home Assistant integration (the "brain")                        │
│                                                                 │
│   coordinator.py                                                │
│   ├── MQTT listener + dedup (image_processor.py)                │
│   ├── Game detection from metadata                              │
│   ├── GameStateManager (game_state.py)                          │
│   ├── HistoryManager (history.py)                               │
│   ├── SpoilerManager (spoiler.py) – per-game profiles           │
│   ├── PromptPackLoader (prompt_packs/) – manifest + validator   │
│   ├── PromptBuilder (prompt_builder.py)                         │
│   │     modes: coach / coplay / opponent / analyst              │
│   │     build_summary(), build_action()  ← Phase 5.1            │
│   ├── LLMBackend (llm_backend.py) – Ollama / GPT / Gemini / …   │
│   └── sensor.py / binary_sensor.py / select.py / number.py /    │
│       switch.py / image.py                                      │
│                                                                 │
│   Outputs:                                                      │
│     - sensors (tip, latency, error, last-error, session summary)│
│     - events (gaming_assistant_new_tip, _session_ended)         │
│     - services (announce, summarize_session, set_spoiler_profile)│
│     - conversation agent (HA Assist)                            │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼  MQTT:  gaming_assistant/tip (optional)
┌─────────────────────────────────────────────────────────────────┐
│ Optional companions                                             │
│   tools/overlay_pc.py   – tiny Tkinter HUD (display only)       │
│   YOLO worker           – external GPU object detection         │
│   Agent Mode executor   – Phase 5 (vgamepad, opt-in, whitelist) │
└─────────────────────────────────────────────────────────────────┘
```

## MQTT Topic Conventions

| Direction | Topic | Payload |
|-----------|-------|---------|
| In | `gaming_assistant/{client_id}/image` | JPEG bytes |
| In | `gaming_assistant/{client_id}/meta`  | JSON (game hint, resolution, …) |
| In | `gaming_assistant/{client_id}/status`| `online` / `offline` (LWT) |
| Out | `gaming_assistant/tip` | Latest tip (string) |
| Out | `gaming_assistant/status` | `analyzing` / `idle` / `error` |
| Experimental | `gaming_assistant/{client_id}/action` | Structured JSON action (Phase 5) |

## Processing Pipeline

1. **Image arrives** on `gaming_assistant/{client_id}/image`.
2. `ImageProcessor` hashes and deduplicates frames – identical frames
   within a short window are dropped.
3. A **game context** is resolved from the client's most recent
   `meta` payload (window title / app name) via `PromptPackLoader`.
4. `SpoilerManager` merges the pack's `spoiler_defaults` with any
   per-game override, producing a deterministic prompt block.
5. `HistoryManager` provides the last N tips for dedup + "give a new
   insight" guidance.
6. `GameStateManager` contributes structured per-game state snapshots
   (health, score, phase) when a pack declares a `state_schema`.
7. `PromptBuilder.build()` assembles everything in a fixed order.
   `PromptBuilder.build_action()` is used when Agent Mode is active.
8. `LLMBackend` sends the prompt (plus the image for vision backends)
   to the configured provider.
9. The resulting tip is announced via sensors, the `new_tip` event,
   optional TTS, and – via the `gaming_assistant/tip` topic – the
   optional PC overlay.

## Prompt Pack Manifest (v1)

`custom_components/gaming_assistant/prompt_packs/pack_manifest.json` holds:

- `manifest_version` – integer, bumped on breaking pack schema changes.
- `min_integration_version` – soft floor for loading packs.
- `pack_schema` – JSON Schema describing every pack:
  `id`, `name`, `keywords`, `system_prompt` (required); `version`,
  `game_id`, `spoiler_defaults`, `constraints`, `examples` (optional).

The loader (`prompt_packs/__init__.py`) calls `validate_pack()` for each
JSON file, logs violations, and records them under
`PromptPackLoader.invalid_packs` – invalid packs are skipped at runtime
instead of corrupting the prompt.

## Diagnostics

All runtime metrics live on the coordinator and are surfaced as sensors:

- `latency` – seconds of the last LLM call.
- `error_count` – lifetime counter since startup.
- `last_error_message` / `last_error_type` / `last_error_timestamp`
  (NEW) – surfaced via the `Gaming Assistant Last Error` sensor.
- `frames_processed`, `last_analysis`, `registered_workers`,
  `active_watchers`, `session_summary`.

## Safety Boundaries (Phase 5)

- **Agent Mode is opt-in.** The integration never sends actions
  unless the user explicitly enables the feature flag.
- Actions travel as JSON on `gaming_assistant/{client_id}/action` and
  must pass `PromptBuilder.parse_action()` validation.
- The worker maintains a **whitelist** of allowed buttons/axes. Any
  response referencing a disallowed button is rejected, not executed.
- We use `vgamepad` (virtual Xbox/PS controller) rather than raw
  keyboard/mouse injection so the AI can never "escape" the game.
