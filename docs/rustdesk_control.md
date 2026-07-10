# RustDesk als zusätzlicher Steuerungskanal

Status: Konzept (Phase 8, GA-118 … GA-121). Kein Code, nur Architektur.

## Warum

Die bestehenden Capture-Agents (`worker/capture_agent_android.py`, `worker/capture_agent_android_tv.py`) lesen Geräte nur passiv aus (ADB-Screenshots). Der Agent Mode (`worker/agent_executor.py`) kann aktiv steuern, aber ausschließlich über ein virtuelles Gamepad — bewusst kein Keyboard/Mouse, kein OS-Zugriff.

Für Player-2-Assist und einen Pause-Trigger, der auch vom Smartphone aus funktioniert, reicht das nicht. RustDesk deckt das geräteunabhängig ab (Windows/macOS/Linux/Android) ohne dass wir für jede Plattform eine eigene Begleit-App bauen müssen.

## Was RustDesk *nicht* kann

RustDesk ist ein Remote-Desktop-**Protokoll für einen Menschen am Bildschirm**, keine Automatisierungs-Library. Es gibt keine öffentliche API, mit der externer Code "sende Taste X" oder "klicke hier" an ein bereits verbundenes Gerät schickt. Alles, was innerhalb einer RustDesk-Session an Eingaben passiert, kommt von der Person, die die Session bedient — nicht von unserem Python-Code.

Automatisierbar über die RustDesk-CLI ist nur:
- Verbindung zu einer ID aufbauen/beenden (`rustdesk --connect <id> --password ...`)
- Permanentes Passwort/Session-Konfiguration setzen

## Architektur-Entscheidung

Zwei getrennte Bausteine, kein Ersatz für Bestehendes:

1. **Verbindungs-Steuerung** (`worker/rustdesk_controller.py`, GA-119): dünner Wrapper um die RustDesk-CLI, analog zum `_adb_cmd()`-Pattern der Android-Agents. Öffnet/schließt Sessions auf Kommando (z. B. HA-Service `gaming_assistant.open_remote_session`, GA-120). Läuft als externer Prozess — kein RustDesk-Quellcode wird importiert oder gelinkt, damit bleibt das Projekt vollständig MIT-lizenziert (GPLv3 von RustDesk betrifft nur, wer deren Code einbettet, nicht wer den fertigen Client als separaten Prozess aufruft).
2. **Companion-Listener** (optional, GA-121): kleiner Prozess auf dem Zielgerät, der MQTT-Kommandos wie `pause` lokal in eine Medientaste/einen Shortcut übersetzt. Nötig, weil Punkt 1 keine scriptbaren Eingaben liefert. Läuft parallel zu RustDesk, nicht darüber.

## Nicht-Ziele

- Kein Ersatz für `agent_executor.py` (Gamepad bleibt der Weg für automatisierte Spielaktionen).
- Kein Ersatz für die ADB-Capture-Agents.
- Kein Einbetten/Forken von RustDesk-Quellcode in dieses Repo.

## Offene Fragen für die Umsetzung

- Wie wird das RustDesk-Passwort/die ID sicher in HA hinterlegt (Secrets, nicht im Log)?
- Soll `open_remote_session` automatisch bei `assistant_mode = coplay` oder bei einem Pause-Trigger feuern, oder nur manuell per Service-Call?
- Companion-Listener: eigenes kleines Repo/Skript pro Plattform oder in `worker/` bündeln?
