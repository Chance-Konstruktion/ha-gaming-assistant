# RustDesk als zusätzlicher Steuerungskanal

Status: umgesetzt (Phase 8, GA-118 … GA-121), noch nicht veröffentlicht.

## Warum

Die bestehenden Capture-Agents (`worker/capture_agent_android.py`, `worker/capture_agent_android_tv.py`) lesen Geräte nur passiv aus (ADB-Screenshots). Der Agent Mode (`worker/agent_executor.py`) kann aktiv steuern, aber ausschließlich über ein virtuelles Gamepad — bewusst kein Keyboard/Mouse, kein OS-Zugriff.

Für Player-2-Assist und einen Pause-Trigger, der auch vom Smartphone aus funktioniert, reicht das nicht. RustDesk deckt das geräteunabhängig ab (Windows/macOS/Linux/Android) ohne dass wir für jede Plattform eine eigene Begleit-App bauen müssen.

## Was RustDesk *nicht* kann

RustDesk ist ein Remote-Desktop-**Protokoll für einen Menschen am Bildschirm**, keine Automatisierungs-Library. Es gibt keine öffentliche API, mit der externer Code "sende Taste X" oder "klicke hier" an ein bereits verbundenes Gerät schickt. Alles, was innerhalb einer RustDesk-Session an Eingaben passiert, kommt von der Person, die die Session bedient — nicht von unserem Python-Code.

Automatisierbar über die RustDesk-CLI ist nur der Aufbau einer Verbindung: `rustdesk --connect <id> [--password <pw>]` bzw. `--file-transfer <id>`. Der Aufruf übergibt die Verbindung als URI an die laufende RustDesk-Instanz (D-Bus unter Linux, Fenster-Nachricht unter Windows, URL-Schema unter macOS) und endet sofort. **Schließen lässt sich eine Session per CLI nicht**; sie endet im RustDesk-Fenster. Geprüft am Quelltext (`src/core_main.rs`) und an RustDesk 1.5.0.

## Architektur

Zwei getrennte Bausteine, kein Ersatz für Bestehendes:

1. **Verbindungs-Steuerung** (`worker/rustdesk_controller.py`, GA-119): läuft auf dem Rechner, an dem ein Mensch die Session bedient (meist der Gaming-PC), und startet den installierten RustDesk-Client als eigenen Prozess. Kein RustDesk-Quellcode wird importiert oder gelinkt, damit bleibt das Projekt vollständig MIT-lizenziert (GPLv3 von RustDesk betrifft nur, wer deren Code einbettet, nicht wer den fertigen Client als separaten Prozess aufruft). Auslöser ist der HA-Service `gaming_assistant.open_remote_session` (GA-120).
2. **Companion-Listener** (`worker/companion_listener.py`, GA-121): kleiner Prozess, der benannte Befehle aus HA lokal ausführt — Medientasten, einzelne Tasten (Escape, Leertaste, F-Tasten …) oder Android-Tastencodes per ADB. Nötig, weil Punkt 1 keine scriptbaren Eingaben liefert. Läuft parallel zu RustDesk, nicht darüber. Auslöser ist `gaming_assistant.companion_command`.

```
HA-Service open_remote_session ──MQTT gaming_assistant/{pc}/remote──► rustdesk_controller ──► rustdesk --connect <id>
HA-Service companion_command  ──MQTT gaming_assistant/{gerät}/companion──► companion_listener ──► Taste / adb keyevent
                                    ◄── …/remote_result bzw. …/companion_result (Ergebnis, JSON)
```

## Entscheidungen zu den früher offenen Fragen

- **ID und Passwort liegen nie in HA.** Peers (`tablet`, `laptop` …) werden auf dem Rechner mit dem Controller konfiguriert (`--peers` JSON oder `--peer NAME=ID`); HA schickt nur den Namen. Am besten gar kein Passwort hinterlegen und RustDesk sich das Passwort merken lassen: ein hinterlegtes Passwort steht kurz in der Prozessliste, weil RustDesk es nur über die Kommandozeile annimmt. Ergebnisse, die zurück an HA gehen, nennen nur Peer und Modus.
- **Kein eingebauter Auto-Trigger.** `open_remote_session` und `companion_command` sind Services; ob sie bei Co-Player-Modus, Türklingel oder per Sprachbefehl feuern, entscheidet eine Automation. Beispiele in `lovelace/automations_example.yaml`.
- **Companion-Listener im Repo** (`worker/`), ein Skript für Windows, Linux (xdotool) und macOS (osascript, ohne Medientasten). Android-Geräte brauchen keine eigene App: Der Listener auf dem PC schickt Tastencodes per ADB, wie es die ADB-Capture-Agents ohnehin nutzen.

## Leitplanken

- Beide Worker führen nur aus, was **lokal** definiert ist: bekannte Peers bzw. benannte Befehle. Ein Angreifer mit Zugriff auf den Broker kann höchstens eine der freigegebenen Sitzungen öffnen oder eine der freigegebenen Tasten drücken.
- HA prüft Controller- und Gerätenamen, bevor etwas gesendet wird: nur eine Topic-Ebene, keine MQTT-Wildcards.
- Gegen Fluten: derselbe Peer frühestens nach `--cooldown` Sekunden (Standard 10), Befehle frühestens nach `--min-interval` Sekunden (Standard 0,5).
- `companion_listener.py --dry-run` protokolliert nur und drückt nichts.
- Der Agent Mode nutzt keinen dieser Kanäle; er bleibt beim virtuellen Gamepad.

## Nicht-Ziele

- Kein Ersatz für `agent_executor.py` (Gamepad bleibt der Weg für automatisierte Spielaktionen).
- Kein Ersatz für die ADB-Capture-Agents.
- Kein Einbetten/Forken von RustDesk-Quellcode in dieses Repo.
- Kein Schließen von Sessions per Befehl (RustDesk bietet es nicht an).
