# Gaming Assistant für Home Assistant
## Master-Roadmap für ChatGPT Codex (und ähnliche KI-Assistenten)

> Zweck dieses Dokuments: Eine **umsetzbare, priorisierte und technisch konkrete** Entwicklungsroadmap, die von Menschen und KI-Assistenten Schritt für Schritt abgearbeitet werden kann.

---

## 1) Projektzusammenfassung

Der **Gaming Assistant** ist eine Home-Assistant-Integration (HACS), die Gameplay-Screenshots analysiert und daraus kontextbezogene Tipps generiert. Die Analyse läuft lokal über Vision-LLMs (z. B. Ollama), inklusive Spoiler-Kontrolle und Game-spezifischer Prompt-Logik.

### Produktziel
- Echtzeit-nahe, hilfreiche Tipps während des Spielens.
- Maximale Privatsphäre durch lokale Verarbeitung.
- Geräteunabhängig durch Thin-Client-Erfassung (PC, Steam Deck/Linux Handhelds, Android, Android TV/Google TV, Kameraquellen, Konsolen via Kamera).
- Klare Erweiterbarkeit für Community, Overlay, Sprache und Agent-Mode.

### Aktueller Stand (Baseline: v0.4.0)
- Thin-Client-Architektur aktiv.
- Capture Agents für PC und Android (ADB).
- MQTT-basierte Bild- und Metadaten-Pipeline.
- Spoiler-System mit Kategorien/Leveln.
- Prompt Packs + Prompt Builder.
- History-Management + deduplizierte Tipps.
- Legacy-Kompatibilität für alte Worker-Pfade.

### Produktweite Zielgruppe (erweitert)
- Competitive & Casual Gamer (PC/Konsole/Mobile).
- Couch- und TV-Setups (Android TV/Google TV).
- Strategie-/Denkspiele (z. B. Schach, Karten- und Brettspiele via Handykamera).
- Handheld-Nutzer (z. B. Steam Deck, sofern Capture verfügbar).

---

## 1.1) Strategische Ausrichtung (konfliktbereinigt)

Diese Roadmap priorisiert nach aktuellem Stand (Single Source of Truth):
1. **Android TV/Google TV + IP Cam + Steam Deck/PC** als primäre Capture-Wege.
2. **HDMI-Dongle/Capture-Card** nur optionaler Fallback für Sonderfälle.

Damit ist die Richtung konsistent zu "software-first" und living-room-freundlichen Setups.

---

## 2) Architektur-Masterplan

## 2.1 Zielarchitektur (Thin Client)

```text
Capture Source (PC / Steam Deck / Android / Android TV App / IP Webcam)
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
- **Dual Interaction Model**: Ask-Mode + Proaktiv-Mode.

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
Mehr Eingangsquellen, damit praktisch jedes Setup (PC/Steam Deck/Console/Mobile/TV) angebunden werden kann.

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

### 4.2 Android TV / Google TV Capture-Integration (PRIORITÄT)
**Deliverables**
- Neues Modul/Companion-App-Konzept: `android_tv_capture/` (Kotlin) **oder** ADB-basierter Polling-Agent als Übergang.
- Erfassung von Screenshots auf Android TV (MediaProjection API in App oder ADB `screencap`).
- MQTT-Publishing kompatibel zu bestehender Topic-Struktur.

**Implementierungsschritte**
1. Architektur-Entscheidung (ADR): native TV-App vs. ADB-only Übergang.
2. MVP 1: ADB-Pfad stabilisieren (`adb exec-out screencap -p`) mit dedizierter TV-Konfiguration.
3. MVP 2: Native Android-TV-App mit Foreground Service + Snapshot-Intervall + MQTT Client.
4. Metadaten erweitern (`client_type: android_tv`, `app_package`, optional `input_source`).
5. README-Setup für Sony/Philips/Chromecast/Shield ergänzen.

**Abhängigkeiten**
- Übergang: bestehender Python-Stack + ADB.
- Native App: Kotlin + Android TV SDK + MQTT Client (Paho/alternativ).

**Risiken**
- TV-Hersteller-Beschränkungen für Screen Capture.
- Rechte-/Permission-Flow je Android-Version.

### 4.3 HDMI-Bridge (depriorisiert, optional)
**Status**
- Nur optionaler Fallback, **nicht** primärer Fokus.

**Lieferumfang (wenn nötig)**
- Minimaler Bridge-Agent für Sonderfälle mit externer Capture-Hardware.

### 4.4 Linux/macOS Feinschliff
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

### 4.5 Per-Game Spoiler Profile
**Deliverables**
- Persistente Profile je Spiel.
- Service: `gaming_assistant.set_spoiler_profile`.
- Fallback: globales Default-Profil.

**Implementierungsschritte**
1. `spoiler.py` um Profile-Storage erweitern.
2. In Pipeline pro erkannter Game-ID Profil laden.
3. Service-Schema + Validierung ergänzen.
4. Sensorattribute um aktives Profil erweitern.

### 4.6 Prompt Pack Lifecycle
**Deliverables**
- Versionierung/Manifest für Prompt Packs.
- Optionales Update-Service-Konzept (remote oder lokaler Import).

**Implementierungsschritte**
1. Pack-Schema mit `version`, `game_id`, `constraints`, `examples` definieren.
2. Loader-Validierung + Fehlerberichte verbessern.
3. Lokales Override-Konzept dokumentieren.

### 4.7 Session-Zusammenfassungen
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

### 4.8 PC Overlay HUD
**Deliverables**
- Optionales Overlay-Programm (`tools/overlay_pc.py` oder separates Repo).
- MQTT Subscriber für aktuelle Tipps.
- Hotkey/Toggle + Position/Transparenz konfigurierbar.

**Implementierungsschritte**
1. Lightweight GUI (z. B. Tkinter/PySide/Pygame).
2. Render-Layer nicht-blockierend.
3. Minimales Config-File + Presets.

### 4.9 Android Overlay
**Deliverables**
- Begleit-App (Kotlin) mit „draw over apps“ Berechtigung.
- Anzeige der letzten Tipps + optional TTS-Trigger.

### 4.10 Lovelace-Ausbau
**Deliverables**
- Erweiterte Dashboard-Karte (live Tip, History, Profilumschaltung, Quelle).
- Bessere Diagnoseansicht (letzter Fehler, Latenz, Modellname).

---

## Phase 4 (v0.8.x): Voice Copilot + Agent Mode (experimentell)

### Ziel
Interaktive Steuerung und aktive Assistenz bei strengen Sicherheitsgrenzen.

### 4.11 Sprach-Copilot
**Deliverables**
- STT-Integration (z. B. Whisper/Faster-Whisper/Wyoming).
- Frage-Antwort-Zyklus: Audio + Bild + Kontext -> Antworttip.
- TTS-Rückkanal über HA.

### 4.12 Agent Mode (Sicherheitsmodus)
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

### 4.13 Prompt Pack Sharing
**Deliverables**
- Externe Prompt-Pack-Registry (Repo/Index).
- Submission-Templates + Validierung.

### 4.14 Multi-Client & Multi-User UX
**Deliverables**
- Besseres Client-Routing im Coordinator.
- Pro Client eigene Einstellungen/History-Anzeigen.

### 4.15 Contributor Experience
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
- `worker/capture_agent_android_tv.py` (optionaler Übergangsagent via ADB)
- `android_tv_capture/` (Companion-App, Kotlin)
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
- Quellen: Desktop Capture, Android TV (ADB/App), IP Webcam.
- Szenarien: hoher Bilddurchsatz, Broker-Neustart, Modellfehler, ungültige Metadaten.

## 7.3 Performance-Checks
- Verarbeitungslatenz pro Bild.
- RAM/CPU-Nutzung HA + Agent.
- Netzwerkverbrauch je Capture-Quelle.

---

## 8) Release- und Migrationsplan

## 8.1 Zielversionen
- **0.5.x**: Android-TV/Google-TV Capture + IP-Webcam Reife + Plattform-Robustheit.
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

**Empfohlene Reihenfolge ab jetzt (für parallel arbeitende Assistants):**
- Track A (Capture): GA-102 -> GA-103 -> GA-107
- Track B (Interaction): GA-111 -> GA-112
- Track C (Domain Expansion): GA-113 + zusätzliche Prompt-Packs

1. **GA-101:** `capture_agent_ipcam.py` implementieren + README-Abschnitt.
2. **GA-102:** Android-TV ADB-MVP (`capture_agent_android_tv.py`) mit stabiler Screenshot-Pipeline.
3. **GA-103:** Architektur-ADR + Scaffold für native Android-TV-App (Foreground Service + MQTT).
4. **GA-104:** Spoiler-Profil-Persistenz pro Spiel in Integration ergänzen.
5. **GA-105:** Prompt-Pack-Manifest/Validierung einführen.
6. **GA-106:** Session-Summary-Mechanik in History + Prompt Builder integrieren.
7. **GA-107:** Erweiterte Diagnosesensoren (Latenz, letzter Fehler, Quelle, client_type).
8. **GA-108:** Overlay-PC-Prototyp (nur Anzeige, kein Agent Mode).
9. **GA-109:** Test-Harness mit Beispielbildern für reproduzierbare E2E-Läufe.
10. **GA-110:** HDMI-Bridge nur als optionales Community-Addon (niedrige Priorität).
11. **GA-111:** Ask-Mode-Service (`gaming_assistant.ask`) für freie Fragen plus Screenshot-Kontext.
12. **GA-112:** Proaktiv-Modus mit Regelprofilen ("silent", "coach", "aggressive hints").
13. **GA-113:** Prompt-Profile für Nicht-Action-Spiele (Schach/Karten/Brettspiele).

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
- Nächster Hebel: **Android-TV/Google-TV first** plus robuste Kameraquellen (v0.5.x).
- Danach: **intelligentere Kontextsteuerung** (v0.6.x) und **sichtbare UX** (v0.7.x).
- Voice/Agent Mode erst mit klaren Sicherheits- und Qualitätsleitplanken.
- Roadmap ist so strukturiert, dass Codex Tickets direkt umsetzen kann.

