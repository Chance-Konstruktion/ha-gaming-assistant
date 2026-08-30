"""
Gaming Assistant – PC Overlay HUD
=================================
A tiny always-on-top window that shows the latest gaming tip pushed by
Home Assistant. Subscribes to ``gaming_assistant/tip`` on MQTT and renders
the message in a transparent Tkinter overlay.

This is explicitly a *display-only* prototype. It does NOT execute any
actions (that belongs to Phase 5 / Agent Mode, behind explicit opt-in).

Requirements:
    pip install paho-mqtt

Usage:
    python overlay_pc.py --broker 192.168.1.10
    python overlay_pc.py --broker 192.168.1.10 --position top-right --alpha 0.85
    python overlay_pc.py --broker 192.168.1.10 --topic "gaming_assistant/tip"

Hotkey:
    F8 – toggle overlay visibility
    Esc – quit
"""

from __future__ import annotations

import argparse
import logging
import threading
import tkinter as tk
from tkinter import font as tkfont

import paho.mqtt.client as mqtt

log = logging.getLogger("overlay_pc")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


POSITIONS = {
    "top-left":     lambda w, h, sw, sh: (20, 20),
    "top-right":    lambda w, h, sw, sh: (sw - w - 20, 20),
    "bottom-left":  lambda w, h, sw, sh: (20, sh - h - 80),
    "bottom-right": lambda w, h, sw, sh: (sw - w - 20, sh - h - 80),
    "center-top":   lambda w, h, sw, sh: ((sw - w) // 2, 40),
}


class OverlayApp:
    """Tkinter overlay window driven by MQTT messages from HA."""

    def __init__(
        self,
        position: str,
        alpha: float,
        width: int,
        font_size: int,
    ) -> None:
        self.root = tk.Tk()
        self.root.title("Gaming Assistant Overlay")
        self.root.overrideredirect(True)          # no window chrome
        self.root.attributes("-topmost", True)    # always on top
        self.root.attributes("-alpha", alpha)
        self.root.configure(bg="black")

        self.width = width
        self.position = position

        tip_font = tkfont.Font(family="Segoe UI", size=font_size, weight="bold")
        self.label = tk.Label(
            self.root,
            text="Gaming Assistant\n(waiting for tips…)",
            fg="#7CFC00",
            bg="black",
            font=tip_font,
            wraplength=width - 24,
            justify="left",
            padx=12,
            pady=10,
        )
        self.label.pack(fill="both", expand=True)

        self._visible = True
        self.root.bind("<F8>", lambda _e: self.toggle_visibility())
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

        self._place_window()

    def _place_window(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        h = max(80, self.label.winfo_reqheight() + 20)
        placer = POSITIONS.get(self.position, POSITIONS["top-right"])
        x, y = placer(self.width, h, sw, sh)
        self.root.geometry(f"{self.width}x{h}+{x}+{y}")

    def toggle_visibility(self) -> None:
        self._visible = not self._visible
        if self._visible:
            self.root.deiconify()
        else:
            self.root.withdraw()

    def set_tip(self, text: str) -> None:
        """Thread-safe update: always marshal into the Tk main loop."""
        def _update() -> None:
            self.label.config(text=text.strip())
            self._place_window()
        self.root.after(0, _update)

    def run(self) -> None:
        self.root.mainloop()


def start_mqtt(
    app: OverlayApp,
    broker: str,
    port: int,
    topic: str,
    username: str,
    password: str,
) -> mqtt.Client:
    """Background MQTT client that feeds incoming tips into the overlay."""
    client = mqtt.Client(client_id="gaming_assistant_overlay", clean_session=True)

    if username:
        client.username_pw_set(username, password)

    def on_connect(c, userdata, flags, rc):  # noqa: ANN001
        if rc == 0:
            log.info("MQTT connected to %s:%d (topic=%s)", broker, port, topic)
            c.subscribe(topic)
        else:
            log.error("MQTT connection failed (rc=%d)", rc)

    def on_message(c, userdata, msg):  # noqa: ANN001
        try:
            payload = msg.payload.decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            return
        if payload:
            app.set_tip(payload)

    client.on_connect = on_connect
    client.on_message = on_message

    def runner() -> None:
        try:
            client.connect(broker, port, keepalive=60)
            client.loop_forever()
        except OSError as err:
            log.error("MQTT loop terminated: %s", err)

    threading.Thread(target=runner, daemon=True).start()
    return client


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – PC Overlay HUD (display only)"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument("--topic", default="gaming_assistant/tip",
                        help="Topic to subscribe to for tip text")
    parser.add_argument("--position", default="top-right", choices=list(POSITIONS))
    parser.add_argument("--alpha", type=float, default=0.85,
                        help="Window opacity (0.1 - 1.0)")
    parser.add_argument("--width", type=int, default=420, help="Overlay width in px")
    parser.add_argument("--font-size", type=int, default=12)
    args = parser.parse_args()

    app = OverlayApp(
        position=args.position,
        alpha=max(0.1, min(1.0, args.alpha)),
        width=args.width,
        font_size=args.font_size,
    )
    start_mqtt(
        app,
        broker=args.broker,
        port=args.port,
        topic=args.topic,
        username=args.user,
        password=args.password,
    )
    app.run()


if __name__ == "__main__":  # pragma: no cover
    main()
