# Gaming Assistant für Home Assistant — Roadmap

Lebendiges Planungsdokument für die Weiterentwicklung der Integration.
Statusangaben werden bei jeder Release aktualisiert; abgehakte Tasks
bleiben als Beleg im Dokument stehen, damit nachvollziehbar ist, was
ausgeliefert wurde.

**Aktueller Stand:** v0.13.0 (April 2026).
Detaillierte Versionshistorie: `CHANGELOG.md`.

Statusmarker:
- ✅ erledigt (mit Versionsangabe)
- 🟡 teilweise erledigt
- ⬜ offen / geplant
- 🧪 experimentell / Forschungsphase

---

## 1) Projektzusammenfassung

Der **Gaming Assistant** ist eine Home-Assistant-Integration (HACS),
die Gameplay-Screenshots analysiert und daraus kontextbezogene Tipps
generiert. Die Analyse läuft lokal über Vision-LLMs (z. B. Ollama)
oder optional über Cloud-Backends, inklusive Spoiler-Kontrolle und
Game-spezifischer Prompt-Logik.

### Produktziel
- Echtzeit-nahe, hilfreiche Tipps während des Spielens.
- Maximale Privatsphäre durch lokale Verarbeitung (Cloud nur wenn
  bewusst aktiviert).
- Geräteunabhängig durch Thin-Client-Erfassung (PC, Android, Android
  TV, IP-Webcam, HDMI-Bridge).
- Klare Erweiterbarkeit für Community-Packs, Overlay, Sprache und
  späteren Agent-Mode.

---

## 2) Architektur (Stand v0.13.0)

```text
Capture Source (PC / Android / Android TV / IP Webcam / HDMI-Bridge)
  -> Screenshot + Metadaten
  -> MQTT Publish (binary + JSON)

Home Assistant Integration ("Brain")
  -> MQTT Listener (bounded queue, dedup)
  -> Game-/Context-Erkennung
  -> History + Spoiler Profile (per Game)
  -> Prompt Pack Loader + Validator (manifest-basiert)
  -> Prompt Builder (modes: coach/coplay/opponent/analyst, action)
  -> LLM Backend (Ollama / GPT-4o / Gemini / DeepSeek / LM Studio / Groq)
  -> Sensoren / Services / Events / Conversation Agent

Optional Companions
  -> tools/overlay_pc.py     (Display-only HUD)
  -> YOLO Worker             (externe GPU-Objekterkennung)
  -> Agent Mode Executor     (geplant, vgamepad, Whitelist-Sandbox)
```

Detailliertes Diagramm: `docs/architecture.md`.

### Kernprinzipien
- **Compute zentral in HA**, Capture minimal halten.
- **Sicher-by-default**, insbesondere für jeden zukünftigen Agent
  Mode (vgamepad statt OS-Input, Whitelist + Audit).
- **Idempotente Services** + nachvollziehbare Zustände.
- **Backward Compatibility**, wo sinnvoll.
- **Feature-Flags** für experimentelle Module.

### Nicht-funktionale Ziele
- Latenz: 2–8 s pro Analysezyklus (modellabhängig).
- Robustheit bei MQTT-Ausfall (Retry/Backoff/Reconnect).
- Geringe Capture-CPU-Last.
- Transparente Logs + Diagnostik (`Last Error`-Sensor seit v0.13).

---

## 3) Funktionsstand (Inventar)

### Integration-Kern — ✅
- `coordinator.py` mit MQTT-Pipeline und Backoff-Setup.
- `image_processor.py`, `prompt_builder.py`, `spoiler.py`,
  `history.py`, `game_state.py`, `llm_backend.py`.
- 4 Assistenz-Modi (coach / coplay / opponent / analyst).
- Per-Game Spoiler-Profile mit Persistenz.
- HA Camera Watcher (kontinuierliches Monitoring).
- TTS Auto-Announce + `gaming_assistant_new_tip` Event.
- Conversation Agent (HA Assist, EN + DE).
- Session Tracking + `summarize_session` Service.
- Multi-LLM-Backends (lokal + Cloud).

### Capture-Quellen — ✅

| Quelle | Datei | Status |
|--------|-------|--------|
| PC (Windows/Linux/macOS) | `worker/capture_agent.py` | ✅ |
| Android (ADB) | `worker/capture_agent_android.py` | ✅ |
| Android TV / Google TV | `worker/capture_agent_android_tv.py` | ✅ |
| IP Webcam | `worker/capture_agent_ipcam.py` | ✅ — v0.13 mit Exponential Backoff |
| HDMI-Bridge (V4L2 / Pi) | `worker/capture_agent_bridge.py` | ✅ v0.13 |

### Prompt Packs — ✅
- Externe Community-Repo:
  [`Chance-Konstruktion/ha-gaming-assistant-prompts`](https://github.com/Chance-Konstruktion/ha-gaming-assistant-prompts).
- Auto-Download beim HA-Start, Cache hat Vorrang vor gebündelten
  Packs.
- Manifest + Schema-Validator (`pack_manifest.json`, v0.13).
- Hot-Reload-Service `gaming_assistant.refresh_prompt_packs` (v0.13).
- 26+ gebündelte Packs (Action, RPG, Tabletop, Card).

### Diagnose & UX — ✅
- Sensoren: Tip, Status, Latency, Frames Processed, Error Count,
  **Last Error** (v0.13), Last Analysis, Workers, Active Watchers,
  Session Summary, Last Frame (Image-Entity).
- Lovelace-Dashboard v2 mit Runtime-Bereich und Diagnose-Karten.
- Sidebar-Panel mit Active-Model- und Active-Client-Chips.
- PC-Overlay-HUD `tools/overlay_pc.py` (v0.13, Display-only).

---

## 4) Backlog & Status nach Phasen

### Phase 1 — Capture-Quellen erweitern (v0.5.x)

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-101 | IP-Webcam-Agent inkl. Exponential Backoff | ✅ v0.13 |
| GA-102 | HDMI-Bridge-Agent (`/dev/video*`) + systemd-Beispiel | ✅ v0.13 |
| GA-LIN | Linux/macOS Window-Title-Erkennung (X11 + `--game-hint`) | ✅ v0.5/v0.7 |

### Phase 2 — Prompt-/Spoiler-Intelligenz (v0.6.x)

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-103 | Per-Game Spoiler-Profile mit Persistenz + Service | ✅ v0.5 |
| GA-104 | Prompt-Pack-Manifest + Schema-Validator | ✅ v0.13 |
| GA-105 | Session-Summary + Auto-Summary | ✅ v0.9 |

### Phase 3 — UX, Overlay, Dashboard (v0.7.x – v0.12.x)

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-106 | Diagnosesensoren (Latency, Last Error, Workers, Quelle) | ✅ v0.13 |
| GA-107 | PC-Overlay-Prototyp (Display-only) | ✅ v0.13 |
| GA-LOV | Modernisiertes Lovelace-Dashboard | ✅ v0.11 |
| GA-PNL | Sidebar-Panel mit Status-Chips | ✅ v0.12 |
| GA-IMG | `image.gaming_assistant_last_frame` Debug-Entity | ✅ v0.12 |

### Phase 4 — Voice & Conversation (v0.8.x – v0.9.x)

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-VOI | TTS Announce + Auto-Announce | ✅ v0.9 |
| GA-EVT | `gaming_assistant_new_tip` Event | ✅ v0.9 |
| GA-CON | Conversation Agent (HA Assist, EN + DE) | ✅ v0.9.1 |
| GA-LNG | Automatische Spracherkennung | ✅ v0.9 |
| GA-CMP | Compact-Mode für kleine Modelle | ✅ v0.9 |
| GA-IMV | Bild-Kontext bei Sprachfragen (Audio + Bild + Tipp) | ⬜ optional |

### Phase 5 — Agent Mode / Player 2 (v1.0.x)

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-ACT | Action-Output-Format im PromptBuilder (JSON-Schema + Whitelist-Parser) | ✅ v0.13 |
| GA-109 | `vgamepad`-Executor-Worker (`worker/agent_executor.py`, MQTT `gaming_assistant/{client_id}/action`, Whitelist + Audit-Log) | ✅ — Worker + Whitelist + Dry-Run + Not-Aus + Audit-Log (unreleased). |
| GA-110 | Schach-Bot-Prototyp auf Action-Mode (TTS-Ansage für physisches Schach + optional vgamepad für PC-Schach) | ⬜ |
| GA-111 | ViZDoom-Hybrid: Reflex-Agent + LLM-Strategie | 🧪 |
| GA-AUD | Audit-Log + konfigurierbare Bestätigung pro Aktion | 🟡 — opt-in HA-seitiges Action-Publishing (`set_agent_mode`-Service + Agent-Mode-Switch, Whitelist, INFO-Audit, Reset-on-restart) implementiert (unreleased). Per-Aktion-Bestätigung fehlt noch. |

### Phase 6 — Community & Ökosystem

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-113 | Prompt-Pack-Sharing über externe Community-Repo + Auto-Download + Hot-Reload | ✅ — Repo + Loader v0.4, Hot-Reload-Service v0.13 |
| GA-114 | Multi-Client-Routing (eigene Einstellungen / History pro Client) | 🟡 — Active-Client-Tracking ist da, dedizierte UI fehlt |
| GA-115 | Pack-Authoring-Guide + Submission-Workflow (`docs/pack_authoring.md`) | ✅ v0.13 |
| GA-116 | Issue-/PR-Templates + Release-Checkliste | 🟡 — CI vorhanden, Checkliste fehlt |

### Phase 7 — Multi-Modell & Performance

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-LLM | Multi-LLM-Backend (Ollama / GPT / Gemini / DeepSeek / LM Studio / Groq) | ✅ v0.10 |
| GA-YOL | YOLO-Worker für Object Detection (CUDA / NCNN / Hailo / TFLite) | ✅ v0.10 |
| GA-GST | Game-State-Engine + Trend Detection | ✅ v0.10 |

### Begleit-Apps & Test-Infrastruktur

| Task | Beschreibung | Status |
|------|--------------|--------|
| GA-AND | Android Capture Agent (eigene App, Foreground-Service, CI-Build) | ✅ v0.11/v0.12 |
| GA-112 | Android Draw-Over-Apps Overlay (Kotlin Begleit-App) | ⬜ |
| GA-117 | Test-Harness mit Beispielbildern für reproduzierbare E2E | ✅ v0.13 (`tests/fixtures/`) |

---

## 5) Aufgabenstruktur (Task-Spec-Format)

Neue Tasks werden als Markdown- oder Issue-Spec abgelegt:

```yaml
task_id: GA-XXX
title: Kurzbeschreibung
phase: v0.X
scope_files:
  - custom_components/gaming_assistant/...
  - worker/...
inputs:
  - CLI args / service payload / MQTT topics
outputs:
  - entities, services, files, logs
constraints:
  - backwards compatible: true/false
  - security gates: ...
acceptance_criteria:
  - ...
test_plan:
  - unit: ...
  - integration: ...
  - manual: ...
docs_update:
  - README
  - dashboard example
```

Empfohlener Workflow je Task:
1. Relevante Dateien lesen, Diff-Plan erzeugen.
2. Minimalen funktionsfähigen Patch erstellen.
3. Tests + Lint ausführen (`python -m unittest discover -s tests`).
4. Doku aktualisieren (`README.md`, `docs/`, `CHANGELOG.md`).
5. PR mit klarer Risk/Impact-Section.

---

## 6) Technische Bausteine

### MQTT-Konventionen
- **Eingehend** (Capture → HA):
  - `gaming_assistant/{client_id}/image` — JPEG-Bytes
  - `gaming_assistant/{client_id}/meta`  — JSON (Game, Resolution, Source)
  - `gaming_assistant/{client_id}/status`— `online` / `offline` (LWT)
- **Ausgehend** (HA → Subscribers):
  - `gaming_assistant/tip`     — Aktueller Tipp (String)
  - `gaming_assistant/status`  — `analyzing` / `idle` / `error`
- **Experimentell / Phase 5**:
  - `gaming_assistant/{client_id}/action` — Strukturierte JSON-Aktion (gegated, opt-in)
  - `gaming_assistant/{client_id}/voice`  — optional, Sprachsteuerung

### Geplante neue Dateien
- `worker/agent_executor.py` (vgamepad Executor — GA-109) ✅ implementiert
- `worker/requirements-player2.txt` enthält jetzt `vgamepad` + `paho-mqtt`
- `docs/agent_mode.md` (Sicherheitsleitplanken-Doku — GA-AUD)

### Häufig zu ändernde Dateien
- `custom_components/gaming_assistant/coordinator.py`
- `custom_components/gaming_assistant/__init__.py`
- `custom_components/gaming_assistant/services.yaml`
- `custom_components/gaming_assistant/strings.json` + `translations/*.json`
- `worker/capture_agent.py` und Geschwister
- `README.md`

---

## 7) Qualitätsstrategie

### Tests (Pflicht je PR)
- Unit-Tests für Spoiler, History, Prompt Builder, Pack-Validator.
- Integrationstests mit gemocktem MQTT + Ollama API.
- Regressionstests für Legacy-Topics.
- Aktueller Stand: **313 Tests grün**.

### Test-Matrix
- Plattformen: Windows, Linux, macOS (best effort), Android (ADB).
- Quellen: Desktop Capture, IP Webcam, HDMI-Bridge.
- Szenarien: hoher Bilddurchsatz, Broker-Neustart, Modellfehler,
  ungültige Metadaten, ungültige Prompt-Packs.

### Performance-Checks
- Verarbeitungslatenz pro Bild (`Latency`-Sensor).
- RAM/CPU-Nutzung HA + Agent.
- Netzwerkverbrauch je Capture-Quelle.

---

## 8) Release- und Migrationsplan

### Versions-Status
- **0.5.x** ✅ Neue Capture-Quellen + Plattform-Robustheit.
- **0.6.x** ✅ Erweiterte Spoiler-/Prompt-Intelligenz.
- **0.7.x** ✅ Camera & Worker Auto-Registration.
- **0.8.x** ✅ Dashboard-Entitäten.
- **0.9.x** ✅ Voice + Session Summary + Conversation Agent.
- **0.10.x** ✅ State Engine + Multi-LLM + YOLO Worker.
- **0.11.x** ✅ Dashboard v2 + Android CI + Test Suite.
- **0.12.x** ✅ Debug-Image-Entity, Sidebar-Chips.
- **0.13.x** ✅ Roadmap-Closeout: HDMI-Bridge, Pack-Manifest, Last-Error,
  PC-Overlay, Action-Mode, Pack-Refresh-Service.
- **1.0.x** ⬜ Player 2 / Agent Mode (vgamepad-Executor, Whitelist,
  Audit-Log).

### Definition of Done
Ein Feature gilt als „done", wenn:
1. Code implementiert + getestet (Unit + manuell, wo sinnvoll).
2. Services/Entities dokumentiert (Strings + Translations).
3. Migration/Upgrade-Hinweise vorhanden, falls relevant.
4. Beispielautomation oder Usage-Beispiel im README/Lovelace.
5. CHANGELOG-Eintrag vorhanden.

---

## 9) Dokumentationsplan

Pro Release zu prüfen:
- `README.md` (Installation, Setup, Beispiele).
- `CHANGELOG.md` (Versionshistorie als Single-Source-of-Truth).
- `docs/architecture.md` (Architekturdiagramm).
- `docs/FAQ.md` (Troubleshooting + häufige Fragen).
- Dashboard-/Automation-Beispiele in `lovelace/`.
- Pack-Authoring-Guide (Repo `ha-gaming-assistant-prompts`).

---

## 10) Offene Designentscheidungen (ADR-light)

Bei folgenden Themen vor Implementierung Entscheidung dokumentieren:

| Thema | Status |
|-------|--------|
| Remote-Pack-Trust-Modell (Signaturen, Allowlist, manuelle Reviews) | ⬜ — derzeit Trust-by-Repo-Origin |
| Agent-Mode-Scope (nur „assistive actions" vs. volle Input-Kontrolle) | ⬜ — Phase 5 setzt auf vgamepad-only |
| Overlay im Hauptrepo vs. Companion-Repo | ✅ — Hauptrepo (`tools/`), reine Display-Komponente |
| Mindest-Hardwareprofil für empfehlenswerte Modelle | 🟡 — README-Tabelle vorhanden, nicht ADR-formal |

---

## 11) Stakeholder-Kurzfassung

- Phasen 1–4 sind vollständig ausgeliefert.
- v0.13 hat die letzten Capture- und Diagnose-Lücken geschlossen.
- Nächster großer Hebel ist **Phase 5** (Agent Mode mit vgamepad), die
  bereits durch das Action-Schema in v0.13 vorbereitet ist. Der Executor
  (`worker/agent_executor.py`, GA-109) ist implementiert, ebenso das opt-in
  HA-seitige Action-Publishing (`set_agent_mode`, GA-AUD); es fehlt noch die
  Per-Aktion-Bestätigungs-UI.
- Community-Beiträge laufen über das separate Prompt-Pack-Repo, das
  per Auto-Download und neuem `refresh_prompt_packs`-Service direkt
  in jede Installation gespiegelt wird.
