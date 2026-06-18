# Changelog

All notable changes to the Gaming Assistant for Home Assistant.

## [Unreleased]

### Agent Mode (Player 2) hardening

- **Added:** `AgentActionGovernor` (`agent_governor.py`) — a pure, unit-tested
  safety gate for autonomous play:
  - **Rate limiting** — at most one published action per
    `AGENT_ACTION_MIN_INTERVAL` seconds (no input flooding).
  - **Dead-man switch** — Agent Mode auto-disables after
    `AGENT_MAX_CONSECUTIVE_FAILURES` consecutive action failures, so a broken
    pipeline never keeps the AI "driving".
- **Added:** HA-native audit — a `Gaming Assistant Agent Action` sensor
  (state = last decision status; attributes = full action, published/failed
  counters, active whitelist) and a `gaming_assistant_agent_action` event
  fired for every decision (`published` / `no_op` / `error` / `auto_disabled`).
- **Added:** 15 tests — behavioural coverage of the governor and the audit
  sensor, plus a wiring contract test.

## [260618] - 2026-06-18 — "Hardening, Pipeline Fixes & Cleanup"

A repo-wide quality pass. Fixes real wiring bugs, removes dead code, moves
blocking work off the event loop, adds linting + real entity tests, and
corrects documentation drift. (Switched to date-based versioning: `YYMMDD`.)

- **Fixed (pipeline):** the per-client status topic
  `gaming_assistant/{id}/status` carries both plain-text capture-agent
  presence (`online`/`offline`) and JSON YOLO-worker status. The handler now
  tolerates both shapes — previously every capture-agent connect/disconnect
  hit a JSON parser and logged a warning, and agent presence was never
  recorded.
- **Fixed (pipeline):** Game State persistence is now wired up. State is
  lazily loaded from disk per game and saved on session end and shutdown, so
  structured per-game state survives restarts. (`save()`/`load()` existed but
  were never called.) All disk work runs in the executor.
- **Fixed:** `async_set_model` now reuses the configured provider id
  (e.g. `deepseek`, `gemini`) instead of the backend class, so switching
  models no longer collapses a provider back onto the OpenAI preset or flips
  `allow_images`.
- **Added:** `gaming_assistant.send_yolo_command` service — sends `status`,
  `restart`, `set_confidence`, or `set_max_fps` to external YOLO workers
  (wires up the previously dead command channel).
- **Performance:** moved blocking file I/O (`history.py`) and Pillow
  decode/resize work (`image_processor.py`) off the Home Assistant event loop
  into the executor.
- **Fixed:** `manifest.json` now declares its `Pillow` dependency (used for
  perceptual-hash dedup and image downscaling).
- **Changed (workers):** every MQTT client now passes an explicit paho
  `CallbackAPIVersion`, and capture agents derive a unique connection
  client-id from `--client-id` to avoid broker reconnect storms.
- **Removed:** dead constants (`CONF_SPOILER_SETTINGS`, `ATTR_LAST_TIP`,
  `ATTR_GAMING_MODE`, `CONF_AGENT_MODE`, `OLLAMA_RETRY_DELAY`), a write-only
  `_processing` flag, unused imports, and a no-op self-assignment.
  `worker/legacy/*` is now clearly marked deprecated; orphaned dev mockups
  (`Preview.html`, `tweaks-panel.jsx`) moved to `dev/`.
- **Tests/CI:** added ruff linting to CI (which caught a real `NameError` in
  the MQTT setup), added behavioral tests for the switch/binary_sensor/image
  platforms (previously 0% coverage), and raised the coverage gate 45 → 50.
- **Docs:** corrected the version label, a broken `_template.json` link, the
  "26 packs included" claim (they are auto-downloaded, not bundled), and
  game-count typos; removed a stale internal handoff doc.

The two items below shipped in this release (previously under *Unreleased*):

- **Added:** `worker/agent_executor.py` (GA-109) — the Agent Mode / Player 2
  executor. An optional worker that subscribes to
  `gaming_assistant/{client_id}/action`, validates each action against the
  `PromptBuilder` action schema and a configurable button whitelist, and
  replays accepted actions on a virtual Xbox controller via `vgamepad`.
  Safety first: `--dry-run` (and the implicit fallback when `vgamepad` is
  missing) validates and logs without sending input, every action is
  appended to a JSON-lines audit log, and `stop`/`start` on
  `gaming_assistant/command` is an emergency pause that releases all inputs.
  Inputs are also released on disconnect and shutdown. Added 38 unit tests
  (`tests/test_agent_executor.py`).
- **Added:** `paho-mqtt` to `worker/requirements-player2.txt`.
- **Added:** Home-Assistant-side Agent Mode publishing (GA-AUD). A new
  `gaming_assistant.set_agent_mode` service and an **Agent Mode** switch
  enable opt-in action publishing: when on, each analyzed frame also asks
  the LLM for one controller action (`PromptBuilder.build_action`),
  validates it (`parse_action` + button whitelist), and publishes it to
  `gaming_assistant/{client_id}/action` for the executor. Strictly opt-in
  and **resets to OFF on every restart**; action generation is fully
  isolated so it can never disrupt the normal tip pipeline.

## [0.13.0] - 2026-04-24 — "Roadmap Close-Out: Bridge, Overlay, Action Mode"

Closes several long-standing items from `ROADMAP.md`.

- **Added:** `gaming_assistant.refresh_prompt_packs` service — re-downloads
  the latest packs from the community repository
  (`Chance-Konstruktion/ha-gaming-assistant-prompts`) and hot-reloads them
  without restarting Home Assistant. Invalid packs are reported but do
  not break existing ones.
- **Added:** Pack authoring guide (`docs/pack_authoring.md`) covering the
  manifest schema, field reference, local-testing workflow, and the
  community submission process. README and FAQ now link to it.
- **Added:** `worker/capture_agent_bridge.py` (GA-102) — HDMI bridge
  capture agent for Raspberry Pi / SBC setups with a USB HDMI dongle.
  Uses OpenCV's V4L2 backend, identical MQTT topic layout as the other
  agents. Ships with a systemd unit in `worker/systemd/`.
- **Added:** Prompt pack manifest + validator (GA-104). Packs are now
  validated against `prompt_packs/pack_manifest.json`; malformed packs are
  skipped with a clear warning and surfaced in
  `PromptPackLoader.invalid_packs`. Pack schema supports optional
  `version`, `game_id`, `constraints`, and `examples` fields.
- **Added:** `Gaming Assistant Last Error` diagnostic sensor (GA-106)
  — shows the latest exception message, type, and timestamp.
- **Added:** `tools/overlay_pc.py` (GA-107) — lightweight, display-only
  Tkinter HUD that subscribes to `gaming_assistant/tip` over MQTT.
  Hotkeys F8 (toggle) / Esc (quit); no input automation.
- **Added:** Action-mode in `PromptBuilder` (Phase 5.1) —
  `build_action()` produces a schema-constrained prompt, and
  `parse_action()` validates the LLM's JSON reply against a button
  whitelist. Foundation for the upcoming `vgamepad` executor.
- **Added:** `docs/architecture.md` and `docs/FAQ.md`.
- **Added:** `tests/fixtures/` with sample prompt packs (valid + invalid)
  and a tiny synthetic frame (GA-108) plus fixture-based tests.
- **Improved:** IP Webcam agent (GA-101) now uses exponential backoff
  (2s, 4s, 8s, …, capped at 60s) when the HTTP endpoint fails, instead
  of sleeping the regular interval.
- **Bumped:** Integration version to `0.13.0`.

## [0.12.1] - 2026-04-05 — "CLI & CI Fixes"
- **Fixed:** `detect_foreground_app()` in legacy Android worker — shell pipe `|`
  was passed as a literal subprocess argument instead of being interpreted by a
  shell, causing foreground app detection to silently fail.
- **Fixed:** CI workflow now installs `aiohttp` so the test suite can import
  `llm_backend` (previously all 9 test files failed during collection).

## [0.12.0] - 2026-03-21 — "Debug Image, Dashboard Fixes & Android Build"
- **Added:** `image.gaming_assistant_last_frame` entity — shows the last
  received frame from any capture client directly in Home Assistant
  (useful for debugging the image pipeline).
- **Added:** Active Model and Active Client chips in the sidebar panel status
  bar — always visible at a glance.
- **Fixed:** Panel camera placeholder changed from "Keine Kamera" / "No camera"
  to "Nur Capture-Clients" / "Capture clients only" (more accurate when using
  MQTT capture agents instead of HA camera entities).
- **Fixed:** Lovelace dashboard now includes a picture-entity card for the
  last received frame.
- **Fixed:** Android Capture Agent build — downgraded AGP to 8.5.2 and pinned
  AndroidX dependencies to compileSdk 34 compatible versions.

## [0.11.0] - 2026-03-21 — "Dashboard v2, Android CI & Test Suite"
- **Added:** Modernized Lovelace Dashboard (v0.11) with Runtime section showing
  active model, active client, known clients list, and available models.
- **Added:** Source Type entity in dashboard status row.
- **Added:** Error count card in diagnostics section.
- **Added:** GitHub Actions workflow for Android Capture Agent — auto-builds
  debug APK on PRs touching `android-capture-agent/`.
- **Added:** Dedicated test suites: `test_config_flow.py`, `test_prompt_builder.py`,
  `test_spoiler.py`.
- **Added:** Android README with CI artifact flow and manual release signing docs.
- **Fixed:** Dashboard Start/Stop buttons use `call-service` instead of
  deprecated `perform-action`.
- **Changed:** 214 tests + 130 subtests total.

## [0.10.0] — "State Engine & Multi-LLM"
- **Added:** Game State Engine — structured per-game state tracking across frames.
- **Added:** Trend detection (health declining, phase changes, momentum shifts).
- **Added:** LLM Backend Abstraction Layer — pluggable AI providers:
  Ollama, OpenAI GPT-4o, Google Gemini, DeepSeek, LM Studio, Groq.
- **Added:** Privacy-first cloud mode — text-only backends never receive images.
- **Added:** YOLO Object Detection Worker (external GPU/NPU service via MQTT).
- **Added:** 13 new prompt packs (CS2, LoL, Valorant, Fortnite, Rocket League,
  FIFA, Civ VI, Cyberpunk 2077, Witcher 3, Diablo IV, Hearthstone, MTG Arena, Among Us).
- **Added:** Config flow step for LLM provider selection with API key input.

## [0.9.1] — "Voice Control"
- **Added:** Conversation agent for HA Assist — voice control in EN & DE.
- **Added:** Free-form questions via Assist forwarded to LLM.
- **Fixed:** Windows batch files find Python reliably.

## [0.9.0] — "Voice & Language"
- **Added:** TTS announce service, auto-announce switch, new_tip event.
- **Added:** Session tracking, summarize_session service, auto-summary.
- **Added:** Automatic language detection from HA settings.
- **Added:** 4 new prompt packs (Stardew Valley, Hades, BotW, Mario Kart).

## [0.8.0] — "Dashboard Entities"
- **Added:** Select/Number entities for mode, spoiler, interval, timeout.
- **Added:** Workers sensor, full DE/EN translations.

## [0.7.0] — "Camera & Workers"
- **Added:** Camera entity selection in config flow, worker auto-registration.

## [0.6.0] — "Tabletop & Modes"
- **Added:** Assistant modes (coach/coplay/opponent/analyst).
- **Added:** Tabletop prompt packs (Chess, Poker, Catan, UNO).
- **Added:** Camera watcher, Windows GUI app, 5 diagnostic sensors.

## [0.5.0] — "Ask Mode & Persistence"
- **Added:** Ask mode, per-game spoiler profiles, camera capture service.
- **Added:** X11 window detection, Android TV foreground app detection.

## [0.4.0] — "Thin Client Architecture"
- **BREAKING:** New capture agents replace old all-in-one workers.
- **Added:** Central image processing in HA, spoiler system, prompt packs, history.

## [0.3.0]
- **Added:** Android worker via ADB.

## [0.2.0]
- **Fixed:** MQTT retry with backoff, config flow validation.
- **Added:** EN/DE translations.

## [0.1.3]
- Initial public release.
