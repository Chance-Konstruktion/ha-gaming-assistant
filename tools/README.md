# Gaming Assistant – Companion Tools

Small, optional helpers that live outside the Home Assistant integration.

## overlay_pc.py — PC Overlay HUD (display only)

Always-on-top Tkinter window that subscribes to `gaming_assistant/tip`
and shows the latest tip on top of your game. **No input actions** are
performed; this is intentionally a read-only companion.

```bash
pip install paho-mqtt
python overlay_pc.py --broker 192.168.1.10
python overlay_pc.py --broker 192.168.1.10 --position bottom-right --alpha 0.8
```

Hotkeys:
- `F8` – toggle visibility
- `Esc` – quit

Use `--topic gaming_assistant/<client_id>/tip` if you want to filter by
capture client.
