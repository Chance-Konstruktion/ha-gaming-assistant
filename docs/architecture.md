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

## Tiered Cognition (perception → tactics → strategy)

The reasoning stack is organised as **tiers** staggered by latency and
cost. Cheap perception runs on every frame and decides when it is worth
spending an expensive model call — instead of one flat fixed-interval LLM
loop that re-derives everything from scratch each time.

| Tier | Cadence | Cost | Job | Where |
|------|---------|------|-----|-------|
| **1 — Reflex / Perception** | every frame | none (no LLM) | Measure the frame: scene-change magnitude, motion class. Emits *measured* signals. | `perception.py` (`PerceptionTier`) |
| **2 — Tactics** | seconds | medium (vision LLM) | Produce the actual tip, consuming Tier 1 signals as input. | `image_processor.py` → `llm_backend.py` |
| **3 — Strategy / Meta** | every few tips / session | low today (deterministic) | Distil a session-level **strategic focus** from game-state trends and feed it back down into Tier 2. Also: session recap. | `strategy.py` (`StrategyTier`), `session_tracker.py` (recap) |

**Why Tier 1 exists.** Structured game state used to be produced *after*
the LLM, by scraping the prose tip back out with regexes
(`game_state.extract_observations_from_tip`). That made perception
downstream of, and dependent on, the model's wording. Tier 1 inverts the
flow: it **measures first** and hands the measurements to Tier 2 as input.
On a key collision the measured value wins over the scraped guess, and all
signals for a frame merge into a *single* state snapshot.

```
frame ─► Tier 1 (perception.py)  ── measured signals ─►  Tier 2 (image_processor.py)
            scene_change, motion        (prompt input)        vision LLM ─► tip
                                                                   │
                                                                   ▼
                                                       GameStateManager (one snapshot/frame:
                                                       measured signals override tip-scraped)
```

Tier 1 keeps a per-client perceptual-hash memory so scene change is
computed per capture source. The first frame from a client is always
treated as significant.

**Event-driven escalation.** Tier 2 is no longer run on every frame.
`coordinator._process_image` consults `PerceptionTier.should_escalate()`
and spends an LLM call only when:

- the frame is a **significant** change (`scene_change ≥ SCENE_CHANGE_SIGNIFICANT`
  or it is the first frame for the client), or
- the **heartbeat** has elapsed (`TIER2_HEARTBEAT_SECONDS`) since the last
  analysis, so a paused or slowly-changing scene still gets a refreshed tip
  instead of going silent.

Frames that don't escalate are handled by Tier 1 only: their measured
signals are still written to the game state (keeping trends flowing), the
status returns to `idle`, and no LLM call is made. The count of such
frames is exposed as `frames_skipped` for diagnostics.

```
frame ─► Tier 1 ─► should_escalate(significant | heartbeat)?
                       │ no  ──► record measured state, idle, frames_skipped++
                       │ yes ──► Tier 2 (LLM) ─► tip + merged snapshot
                                     ▲                    │
                          strategy_note (fed back down)   ▼
                                     └────────  Tier 3: record_tip ─► refresh focus
```

### Tier 3 feedback loop

`StrategyTier` (`strategy.py`) makes the strategy a *live* input rather
than a dead-end recap:

- After each Tier 2 tip the coordinator calls `record_tip(game, tip)`.
  Every `STRATEGY_EVERY_N_TIPS` tips it recomputes a **strategic focus**
  from the trends `GameStateManager.detect_trends()` already surfaces
  (e.g. declining health → "prioritise survival and play defensively";
  a stalled phase → "try a different approach"; sinking momentum →
  "change tactics").
- Before each Tier 2 call the coordinator reads `note(game)` and passes it
  as `strategy_note`, which `ImageProcessor.process` puts at the **top** of
  the prompt context (above the Tier 1 live signals and the rolling state
  block). So tactical tips reason under the session's higher-level frame.
- The current focus is exposed as `strategy_note` for diagnostics. The
  deterministic synthesiser can later be swapped for an LLM "reflection"
  behind the same interface and injection point.

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
- `agent_last_action` / `agent_actions_published` / `agent_actions_failed`
  – surfaced via the `Gaming Assistant Agent Action` sensor and the
  `gaming_assistant_agent_action` event (one per decision).

## Safety Boundaries (Phase 5)

Agent Mode is governed on both ends. On the Home Assistant side an
`AgentActionGovernor` (`agent_governor.py`) is the safety gate:

- **Opt-in.** The integration never sends actions unless the user
  explicitly enables Agent Mode, which **resets to OFF on every restart**.
- **Rate limited.** At most one action per `AGENT_ACTION_MIN_INTERVAL`
  seconds, so the AI can never flood the executor with inputs.
- **Dead-man switch.** After `AGENT_MAX_CONSECUTIVE_FAILURES` consecutive
  action-generation failures (backend down, repeated timeouts), Agent Mode
  **auto-disables** so a broken pipeline never keeps the AI "driving".
- **Audited.** Every decision (`published` / `no_op` / `error` /
  `auto_disabled`) updates the audit sensor and fires
  `gaming_assistant_agent_action` for automations.
- Actions travel as JSON on `gaming_assistant/{client_id}/action` and
  must pass `PromptBuilder.parse_action()` validation.
- The worker maintains a **whitelist** of allowed buttons/axes. Any
  response referencing a disallowed button is rejected, not executed.
- We use `vgamepad` (virtual Xbox/PS controller) rather than raw
  keyboard/mouse injection so the AI can never "escape" the game.
