# Gaming Assistant für Home Assistant
## Master-Roadmap für ChatGPT Codex (und ähnliche KI-Assistenten)

> Zweck dieses Dokuments: Eine **umsetzbare, priorisierte und technisch konkrete** Entwicklungsroadmap, die von Menschen und KI-Assistenten Schritt für Schritt abgearbeitet werden kann.

---

## 1) Projektzusammenfassung

Der **Gaming Assistant** ist eine Home-Assistant-Integration (HACS), die Gameplay-Screenshots analysiert und daraus kontextbezogene Tipps generiert. Die Analyse läuft lokal über Vision-LLMs (z. B. Ollama), inklusive Spoiler-Kontrolle und Game-spezifischer Prompt-Logik.

### Produktziel
- Echtzeit-nahe, hilfreiche Tipps während des Spielens.
- Maximale Privatsphäre durch lokale Verarbeitung.
- Geräteunabhängig durch Thin-Client-Erfassung (PC, Android, Kameraquellen, HDMI-Bridge).
- Klare Erweiterbarkeit für Community, Overlay, Sprache und Agent-Mode.

### Aktueller Stand (v0.9.0)
- Thin-Client-Architektur aktiv.
- Capture Agents für PC, Android (ADB), Android TV, IP Webcam.
- MQTT-basierte Bild- und Metadaten-Pipeline.
- Spoiler-System mit Kategorien/Leveln + Per-Game-Profile.
- Prompt Packs + Prompt Builder (mit Compact-Modus für kleine Modelle).
- History-Management + deduplizierte Tipps.
- Legacy-Kompatibilität für alte Worker-Pfade.
- 4 Assistenz-Modi: Coach, Co-Player, Opponent, Analyst.
- HA Camera Watcher (kontinuierliches Monitoring).
- Dashboard-Entities (Select, Number, Switch).
- **TTS-Ansagen** (`gaming_assistant.announce` + Auto-Announce).
- **Event-System** (`gaming_assistant_new_tip`).
- **Automatische Spracherkennung** aus HA-Konfiguration.
- **Compact-Prompt-Modus** für kleine Modelle (z.B. Ministral 3B).

---

## 2) Architektur-Masterplan

## 2.1 Zielarchitektur (Thin Client)

```text
Capture Source (PC / Android / IP Webcam / HDMI-Bridge)
  -> Screenshot + Metadaten + optional Audio
  -> MQTT Publish (binary + JSON)

Home Assistant Integration (Brain)
  -> MQTT Listener
  -> Dedup + Preprocessing
  -> Game-/Context-Erkennung
  -> History + Spoiler Profiling
  -> Prompt Assembly (Pack + Verlauf + Restriktionen)
  -> Vision LLM Call (Ollama)
  -> Tip + Status + Telemetrie
  -> Sensoren / Services / Automations

Optional Clients
  -> Overlay (PC/Android)
  -> Voice Copilot
  -> Agent Mode Executor (sicherheitsbegrenzt)
```

## 2.2 Kernprinzipien
- **Compute zentral in HA**, Capture minimal halten.
- **Sicher-by-default** (insbesondere für Agent Mode).
- **Idempotente Services** + nachvollziehbare Zustände.
- **Backward Compatibility**, wo sinnvoll.
- **Feature Flags** für experimentelle Module.

## 2.3 Nicht-funktionale Anforderungen
- Latenz Ziel: 2–8 Sekunden pro Analysezyklus (modellabhängig).
- Robustheit bei MQTT-Ausfall (Retry/Backoff/Reconnect).
- Geringe Client-CPU-Last auf Capture-Geräten.
- Transparente Logs + Diagnostik für Nutzer.

---

## 3) Bestehende Module als Fundament (v0.4.0)

### Integration-Kern
- `custom_components/gaming_assistant/__init__.py` – Setup, Services, MQTT-Initialisierung.
- `custom_components/gaming_assistant/coordinator.py` – State, MQTT-Subscriptions, Pipeline-Steuerung.
- Sensoren/Binary Sensoren für Tip/Status/Gaming Mode/History.

### Intelligence-Schicht
- `image_processor.py` – zentrale Bildanalyse.
- `prompt_builder.py` – dynamische Prompt-Erstellung.
- `spoiler.py` – globale Spoiler-Policies.
- `history.py` – Verlauf + Session-Kontext.
- `prompt_packs/*.json` – pro Spiel spezialisiertes Verhalten.

### Capture-Seite
- `worker/capture_agent.py` – Desktop Capture.
- `worker/capture_agent_android.py` – Android via ADB.

---

## 4) Detaillierte Roadmap nach Phasen

## Phase 1 (v0.5.x): Capture-Quellen erweitern

### Ziel
Mehr Eingangsquellen, damit praktisch jedes Setup (PC/Console/Mobile) angebunden werden kann.

### 4.1 IP Webcam Source
**Deliverables**
- Neues Worker-Modul: `worker/capture_agent_ipcam.py`.
- CLI-Parameter: `--url`, `--interval`, `--quality`, `--client-id`, `--broker`, `--port`, optional Auth.
- Publiziert Bild + Metadaten auf bestehende Topic-Struktur.

**Implementierungsschritte**
1. JPEG von `--url` zyklisch abrufen.
2. Optional re-encode/compress via Pillow.
3. Hash-basierte Change Detection (optional Flag).
4. MQTT publish (`gaming_assistant/{client_id}/image`, `.../meta`).
5. Retry-Strategie für HTTP-Fehler.

**Abhängigkeiten**
- `requests`, `Pillow`, `paho-mqtt`.

**Akzeptanzkriterien**
- Stabiler Betrieb > 60 Minuten ohne Crash.
- Bei Kamera-Ausfall: saubere Fehlermeldung + Auto-Recovery.

### 4.2 HDMI-Bridge (Raspberry Pi)
**Deliverables**
- Neues Worker-Modul: `worker/capture_agent_bridge.py`.
- Unterstützung für `/dev/video*` (USB Capture) + optional CSI Kamera.
- Setup-Doku für Pi (minimal reproduzierbar).

**Implementierungsschritte**
1. Capture-Backend abstrahieren (`opencv`/`ffmpeg`/`v4l2`).
2. Einheitliches Frame-Processing wie Desktop-Agent.
3. Topic-/Metadaten-Format identisch halten.
4. Systemd-Service-Beispiel bereitstellen.

**Risiken**
- Unterschiedliche Treiber/Dongles.
- Encoding-Latenz auf schwacher Hardware.

### 4.3 Linux/macOS Feinschliff
**Deliverables**
- Verbesserte Window-Title/Game-Erkennung auf Linux.
- Dokumentierte macOS-Einschränkungen + Berechtigungen.

**Implementierungsschritte**
1. X11-Fallback (wenn verfügbar).
2. Wayland „best effort“ als experimentell markieren.
3. `--game-hint` sauber durchreichen, wenn automatische Erkennung fehlt.

---

## Phase 2 (v0.6.x): Prompt/Spoiler-Intelligenz ausbauen

### Ziel
Präzisere Tipps und bessere Personalisierung pro Spiel/Session.

### 4.4 Per-Game Spoiler Profile
**Deliverables**
- Persistente Profile je Spiel.
- Service: `gaming_assistant.set_spoiler_profile`.
- Fallback: globales Default-Profil.

**Implementierungsschritte**
1. `spoiler.py` um Profile-Storage erweitern.
2. In Pipeline pro erkannter Game-ID Profil laden.
3. Service-Schema + Validierung ergänzen.
4. Sensorattribute um aktives Profil erweitern.

### 4.5 Prompt Pack Lifecycle
**Deliverables**
- Versionierung/Manifest für Prompt Packs.
- Optionales Update-Service-Konzept (remote oder lokaler Import).

**Implementierungsschritte**
1. Pack-Schema mit `version`, `game_id`, `constraints`, `examples` definieren.
2. Loader-Validierung + Fehlerberichte verbessern.
3. Lokales Override-Konzept dokumentieren.

### 4.6 Session-Zusammenfassungen
**Deliverables**
- Rolling Summary statt nur „letzte N Tipps“.
- Kontextkompression für lange Sessions.

**Implementierungsschritte**
1. Trigger nach X Interaktionen.
2. Summarization-Prompt für LLM-Aufruf.
3. Speicherung im History-Format.
4. Prompt Builder nutzt bevorzugt Summary + letzte Ereignisse.

---

## Phase 3 (v0.7.x): UX, Overlay und Dashboard

### Ziel
Tipps sichtbarer und direkter nutzbar machen.

### 4.7 PC Overlay HUD
**Deliverables**
- Optionales Overlay-Programm (`tools/overlay_pc.py` oder separates Repo).
- MQTT Subscriber für aktuelle Tipps.
- Hotkey/Toggle + Position/Transparenz konfigurierbar.

**Implementierungsschritte**
1. Lightweight GUI (z. B. Tkinter/PySide/Pygame).
2. Render-Layer nicht-blockierend.
3. Minimales Config-File + Presets.

### 4.8 Android Overlay
**Deliverables**
- Begleit-App (Kotlin) mit „draw over apps“ Berechtigung.
- Anzeige der letzten Tipps + optional TTS-Trigger.

### 4.9 Lovelace-Ausbau
**Deliverables**
- Erweiterte Dashboard-Karte (live Tip, History, Profilumschaltung, Quelle).
- Bessere Diagnoseansicht (letzter Fehler, Latenz, Modellname).

---

## Phase 4 (v0.8.x–v0.9.x): Voice Copilot + Agent Mode (experimentell)

### Ziel
Interaktive Steuerung und aktive Assistenz bei strengen Sicherheitsgrenzen.

### 4.10 Sprach-Copilot
**Status: TTS-Ausgabe implementiert in v0.9.0**
- `gaming_assistant.announce` Service für TTS-Ausgabe.
- Auto-Announce Switch-Entity.
- `gaming_assistant_new_tip` Event für Automationen.
- Automatische Spracherkennung aus HA-Konfiguration.

**Noch offen:**
- STT-Integration (z. B. Whisper/Faster-Whisper/Wyoming).
- Frage-Antwort-Zyklus: Audio + Bild + Kontext -> Antworttip.

### 4.11 Agent Mode (Sicherheitsmodus)
**Deliverables**
- Separater, deaktivierter-by-default Modus.
- Whitelist-fähige Aktionen (z. B. nur bestimmte Keys).
- Explizite Bestätigung (Overlay Button/Hotkey) pro Aktion oder Session.

**Implementierungsschritte**
1. Neues Topic-Design für Aktionen.
2. Striktes JSON-Schema + Signatur/Token.
3. Lokaler Executor mit Safety-Gates.
4. Vollständiges Audit-Logging jeder Aktion.

**Sicherheitsanforderung (MUSS)**
- Kein Agent Mode ohne explizites Opt-in.
- Keine stillen Aktionen im Hintergrund.

---

## Phase 5 (v0.9.x): Community & Ökosystem

### Ziel
Inhalte und Nutzung skalieren über Community-Beiträge.

### 4.12 Prompt Pack Sharing
**Deliverables**
- Externe Prompt-Pack-Registry (Repo/Index).
- Submission-Templates + Validierung.

### 4.13 Multi-Client & Multi-User UX
**Deliverables**
- Besseres Client-Routing im Coordinator.
- Pro Client eigene Einstellungen/History-Anzeigen.

### 4.14 Contributor Experience
**Deliverables**
- Issue-Templates, PR-Template, Release-Checkliste.
- „How to build a pack“-Guide inkl. Beispiele.

---

## 5) Aufgabenstruktur für Codex (Abarbeitungsformat)

Jedes Feature wird als „Codex Task Spec“ abgelegt (Issue/Markdown):

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

Empfohlener Codex-Workflow je Task:
1. Relevante Dateien lesen, Diff-Plan erzeugen.
2. Minimalen funktionsfähigen Patch erstellen.
3. Tests + Lint ausführen.
4. Doku aktualisieren.
5. PR mit klarer Risk/Impact-Section.

---

## 6) Technische Bausteine und Modulplan

### 6.1 Geplante neue Dateien (Beispiele)
- `worker/capture_agent_ipcam.py`
- `worker/capture_agent_bridge.py`
- `custom_components/gaming_assistant/spoiler_profiles.py` (optional)
- `custom_components/gaming_assistant/prompt_packs/manifest.json`
- `docs/`-Struktur für Setup und Quellen

### 6.2 Voraussichtlich zu ändernde Dateien
- `custom_components/gaming_assistant/coordinator.py`
- `custom_components/gaming_assistant/__init__.py`
- `custom_components/gaming_assistant/services.yaml`
- `custom_components/gaming_assistant/strings.json`
- `custom_components/gaming_assistant/translations/*.json`
- `worker/capture_agent.py`
- `README.md`

### 6.3 MQTT-Konventionsplan
- Eingehend:
  - `gaming_assistant/{client_id}/image`
  - `gaming_assistant/{client_id}/meta`
- Ausgehend:
  - `gaming_assistant/tip`
  - `gaming_assistant/status`
- Optional neu (experimentell):
  - `gaming_assistant/{client_id}/action`
  - `gaming_assistant/{client_id}/voice`

---

## 7) Qualitätsstrategie

## 7.1 Tests (Pflicht je PR)
- Unit-Tests für Spoiler, History, Prompt Builder.
- Integrationstests mit gemocktem MQTT + Ollama API.
- Regressionstests für Legacy-Topics.

## 7.2 Test-Matrix
- Plattformen: Windows, Linux, macOS (best effort), Android (ADB).
- Quellen: Desktop Capture, IP Webcam, HDMI-Bridge.
- Szenarien: hoher Bilddurchsatz, Broker-Neustart, Modellfehler, ungültige Metadaten.

## 7.3 Performance-Checks
- Verarbeitungslatenz pro Bild.
- RAM/CPU-Nutzung HA + Agent.
- Netzwerkverbrauch je Capture-Quelle.

---

## 8) Release- und Migrationsplan

## 8.1 Zielversionen
- **0.5.x**: Neue Capture-Quellen + Plattform-Robustheit.
- **0.6.x**: Erweiterte Spoiler-/Prompt-Intelligenz.
- **0.7.x**: Overlay + Dashboard UX.
- **0.8.x**: Voice + sicherer Agent Mode (experimentell).
- **0.9.x**: Community-Ökosystem + Multi-Client-Reife.
- **1.0.0**: Stabil, dokumentiert, breite Community-Freigabe.

## 8.2 Definition of Done (DoD)
Ein Feature gilt nur dann als „done“, wenn:
1. Code implementiert + getestet.
2. Services/Entities dokumentiert.
3. Migration/Upgrade-Hinweise vorhanden.
4. Beispielautomation oder Usage-Beispiel vorhanden.
5. Changelog-Eintrag enthalten.

---

## 9) Dokumentationsplan

Pro Release müssen aktualisiert werden:
- `README.md` (Installation, Setup, Beispiele)
- Dashboard/Automation-Beispiele
- Troubleshooting („No tips“, „MQTT connected but no image“, „Model timeout“)
- Prompt-Pack-Authoring-Guide

Zusätzlich empfohlen:
- Architekturdiagramm als eigene Datei (`docs/architecture.md`)
- FAQ für typische Hardware-Setups

---

## 10) Backlog (konkret formulierte nächste Tasks)

1. **GA-101:** `capture_agent_ipcam.py` implementieren + README-Abschnitt.
2. **GA-102:** Bridge-Agent-Prototyp für `/dev/video0` + Systemd-Beispiel.
3. **GA-103:** Spoiler-Profil-Persistenz pro Spiel in Integration ergänzen.
4. **GA-104:** Prompt-Pack-Manifest/Validierung einführen.
5. **GA-105:** Session-Summary-Mechanik in History + Prompt Builder integrieren.
6. **GA-106:** Erweiterte Diagnosesensoren (Latenz, letzter Fehler, Quelle).
7. **GA-107:** Overlay-PC-Prototyp (nur Anzeige, kein Agent Mode).
8. **GA-108:** Test-Harness mit Beispielbildern für reproduzierbare E2E-Läufe.

---

## 11) Hinweise für KI-Assistenten (Codex Playbook)

Wenn ein KI-Assistent an diesem Projekt arbeitet, soll jede Ausgabe folgende Struktur haben:
1. **Patch-Plan** (welche Dateien, warum).
2. **Implementierung** (klein, inkrementell, rückwärtskompatibel).
3. **Tests** (automatisiert + manuell).
4. **Dokumentation** (angepasste Beispiele).
5. **Risiken/Offene Punkte**.

### Prompt-Vorlage für Codex

```text
Implementiere Task <GA-XXX> für das Projekt Gaming Assistant.
Kontext:
- Thin Client Architektur mit MQTT Bildpipeline.
- Home Assistant Integration in custom_components/gaming_assistant.
- Bestehende Topics und Services dürfen nicht gebrochen werden.

Liefere:
1) Codeänderungen in kleinen, nachvollziehbaren Commits.
2) Unit- und Integrationstests.
3) README-/Service-Doku-Update.
4) Kurze Migrationshinweise.

Achte auf:
- robuste Fehlerbehandlung,
- klare Logs,
- keine Breaking Changes ohne Flag.
```

---

## 12) Entscheidungsliste (ADR-light)

Bei folgenden Themen vor Implementierung Entscheidung dokumentieren:
- Remote Prompt-Pack Updates: ja/nein, mit welchen Trust-Modellen?
- Agent Mode Scope: nur „assistive actions“ oder vollständige Input-Kontrolle?
- Overlay im Hauptrepo vs. separates Companion-Repo.
- Mindest-Hardwareprofil für empfehlenswerte Modelle.

---

## 13) Kurzfassung für Stakeholder

- Das Projekt ist auf gutem Fundament (v0.4.0).
- Nächster Hebel: **mehr Capture-Quellen** (v0.5.x).
- Danach: **intelligentere Kontextsteuerung** (v0.6.x) und **sichtbare UX** (v0.7.x).
- Voice/Agent Mode erst mit klaren Sicherheits- und Qualitätsleitplanken.
- Roadmap ist so strukturiert, dass Codex Tickets direkt umsetzen kann.

