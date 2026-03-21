# Changelog

All notable changes to the Gaming Assistant for Home Assistant.

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
