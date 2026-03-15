"""
Gaming Assistant – Windows GUI Launcher
========================================
Simple tkinter GUI that wraps capture_agent.py.
Settings are saved to config.ini so you only configure once.

Can be frozen into a single .exe with PyInstaller:
    pyinstaller --onefile --windowed --name GamingAssistant gaming_assistant_gui.py
"""

import configparser
import hashlib
import json
import logging
import os
import platform
import sys
import threading
import time
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import messagebox, scrolledtext

import paho.mqtt.client as mqtt
from mss import mss
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Running as PyInstaller .exe
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_PATH = BASE_DIR / "config.ini"
LOG_PATH = BASE_DIR / "gaming_assistant.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("gaming_assistant")

# ---------------------------------------------------------------------------
# Known games
# ---------------------------------------------------------------------------
KNOWN_GAMES = [
    "Wolfenstein", "Doom", "Cyberpunk", "Elden Ring",
    "Dark Souls", "Minecraft", "Counter-Strike", "Valorant",
    "Overwatch", "Baldur's Gate", "Starfield", "The Witcher",
    "Hogwarts Legacy", "Diablo", "Path of Exile", "Fortnite",
    "Zelda", "God of War", "Horizon", "Resident Evil",
    "Final Fantasy", "Assassin's Creed", "Red Dead",
    "Civilization", "Age of Empires", "Total War",
]

TOPIC_CMD = "gaming_assistant/command"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config() -> dict:
    """Load settings from config.ini or return defaults."""
    defaults = {
        "broker": "",
        "port": "1883",
        "username": "",
        "password": "",
        "client_id": platform.node(),
        "interval": "5",
        "quality": "75",
        "resize": "960x540",
        "monitor": "1",
        "game_hint": "",
        "detect_change": "true",
    }
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH, encoding="utf-8")

    result = dict(defaults)
    if config.has_section("gaming_assistant"):
        for key in defaults:
            if config.has_option("gaming_assistant", key):
                result[key] = config.get("gaming_assistant", key)
    return result


def save_config(settings: dict) -> None:
    """Save settings to config.ini."""
    config = configparser.ConfigParser()
    config["gaming_assistant"] = settings
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        config.write(f)


# ---------------------------------------------------------------------------
# Screenshot + game detection (same as capture_agent.py)
# ---------------------------------------------------------------------------
def capture_screen(monitor_index: int, resize: tuple, quality: int) -> tuple:
    with mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 1
        shot = sct.grab(monitors[monitor_index])
        img = Image.frombytes("RGB", shot.size, shot.rgb)

    img = img.resize(resize, Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    jpeg_bytes = buffer.getvalue()
    frame_hash = hashlib.md5(jpeg_bytes).hexdigest()
    return jpeg_bytes, frame_hash


def detect_window_title() -> tuple:
    try:
        import win32gui
        title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
        return title, "win32gui"
    except Exception:
        return "", "none"


def detect_active_game(window_title: str) -> str:
    title_lower = window_title.lower()
    for game in KNOWN_GAMES:
        if game.lower() in title_lower:
            return game
    return ""


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------
class GamingAssistantApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Gaming Assistant")
        self.root.geometry("520x620")
        self.root.resizable(False, False)

        self.running = False
        self.thread = None
        self.stop_event = threading.Event()
        self.mqtt_client = None

        self.settings = load_config()
        self._build_ui()

    # -- UI ----------------------------------------------------------------

    def _build_ui(self):
        r = self.root

        # Title
        tk.Label(r, text="Gaming Assistant", font=("Segoe UI", 16, "bold")).pack(pady=(10, 5))
        tk.Label(r, text="Screenshot Capture Agent", font=("Segoe UI", 9)).pack()

        # Settings frame
        sf = tk.LabelFrame(r, text="Einstellungen", padx=10, pady=10)
        sf.pack(fill="x", padx=15, pady=10)

        # Broker IP (required)
        tk.Label(sf, text="MQTT Broker IP *", anchor="w").grid(row=0, column=0, sticky="w")
        self.broker_var = tk.StringVar(value=self.settings["broker"])
        tk.Entry(sf, textvariable=self.broker_var, width=30).grid(row=0, column=1, padx=5, pady=2)

        # Port
        tk.Label(sf, text="Port", anchor="w").grid(row=1, column=0, sticky="w")
        self.port_var = tk.StringVar(value=self.settings["port"])
        tk.Entry(sf, textvariable=self.port_var, width=10).grid(row=1, column=1, sticky="w", padx=5, pady=2)

        # Username
        tk.Label(sf, text="MQTT User", anchor="w").grid(row=2, column=0, sticky="w")
        self.user_var = tk.StringVar(value=self.settings["username"])
        tk.Entry(sf, textvariable=self.user_var, width=20).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        # Password
        tk.Label(sf, text="MQTT Passwort", anchor="w").grid(row=3, column=0, sticky="w")
        self.pass_var = tk.StringVar(value=self.settings["password"])
        tk.Entry(sf, textvariable=self.pass_var, width=20, show="*").grid(row=3, column=1, sticky="w", padx=5, pady=2)

        # Interval
        tk.Label(sf, text="Intervall (Sek.)", anchor="w").grid(row=4, column=0, sticky="w")
        self.interval_var = tk.StringVar(value=self.settings["interval"])
        tk.Entry(sf, textvariable=self.interval_var, width=5).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        # Game hint
        tk.Label(sf, text="Spiel (optional)", anchor="w").grid(row=5, column=0, sticky="w")
        self.game_var = tk.StringVar(value=self.settings["game_hint"])
        tk.Entry(sf, textvariable=self.game_var, width=25).grid(row=5, column=1, sticky="w", padx=5, pady=2)

        # Quality
        tk.Label(sf, text="JPEG Qualität", anchor="w").grid(row=6, column=0, sticky="w")
        self.quality_var = tk.StringVar(value=self.settings["quality"])
        tk.Entry(sf, textvariable=self.quality_var, width=5).grid(row=6, column=1, sticky="w", padx=5, pady=2)

        # Detect change checkbox
        self.detect_var = tk.BooleanVar(value=self.settings["detect_change"].lower() == "true")
        tk.Checkbutton(sf, text="Unveränderte Frames überspringen", variable=self.detect_var).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=5
        )

        # Buttons
        bf = tk.Frame(r)
        bf.pack(pady=10)

        self.start_btn = tk.Button(
            bf, text="  START  ", font=("Segoe UI", 12, "bold"),
            bg="#4CAF50", fg="white", command=self.start, width=12
        )
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = tk.Button(
            bf, text="  STOP  ", font=("Segoe UI", 12, "bold"),
            bg="#f44336", fg="white", command=self.stop, width=12, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=5)

        # Status
        self.status_var = tk.StringVar(value="Bereit")
        status_label = tk.Label(r, textvariable=self.status_var, font=("Segoe UI", 10))
        status_label.pack(pady=5)

        # Log output
        lf = tk.LabelFrame(r, text="Log", padx=5, pady=5)
        lf.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(lf, height=10, font=("Consolas", 8), state="disabled")
        self.log_text.pack(fill="both", expand=True)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _log(self, msg: str):
        """Thread-safe log to GUI."""
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"{time.strftime('%H:%M:%S')} {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _append)

    # -- Actions -----------------------------------------------------------

    def start(self):
        broker = self.broker_var.get().strip()
        if not broker:
            messagebox.showerror("Fehler", "Bitte MQTT Broker IP eingeben!")
            return

        # Save settings
        settings = {
            "broker": broker,
            "port": self.port_var.get().strip(),
            "username": self.user_var.get().strip(),
            "password": self.pass_var.get().strip(),
            "client_id": self.settings.get("client_id", platform.node()),
            "interval": self.interval_var.get().strip(),
            "quality": self.quality_var.get().strip(),
            "resize": self.settings.get("resize", "960x540"),
            "monitor": self.settings.get("monitor", "1"),
            "game_hint": self.game_var.get().strip(),
            "detect_change": str(self.detect_var.get()).lower(),
        }
        save_config(settings)
        self.settings = settings

        # Start capture thread
        self.stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Läuft...")
        self._log(f"Gestartet – Broker: {broker}")

    def stop(self):
        self.stop_event.set()
        self.running = False

        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Gestoppt")
        self._log("Gestoppt")

    def _on_close(self):
        self.stop()
        self.root.destroy()

    # -- Capture thread ----------------------------------------------------

    def _capture_loop(self):
        s = self.settings
        broker = s["broker"]
        port = int(s["port"])
        interval = int(s["interval"])
        quality = int(s["quality"])
        monitor = int(s["monitor"])
        game_hint = s["game_hint"]
        detect_change = s["detect_change"].lower() == "true"
        client_id = s["client_id"]

        try:
            w, h = s["resize"].lower().split("x")
            resize = (int(w), int(h))
        except ValueError:
            resize = (960, 540)

        topic_image = f"gaming_assistant/{client_id}/image"
        topic_meta = f"gaming_assistant/{client_id}/meta"

        # MQTT connect
        paused = {"value": False}

        try:
            client = mqtt.Client(client_id="gaming_assistant_capture", clean_session=True)
            if s["username"]:
                client.username_pw_set(s["username"], s["password"])

            def on_connect(c, ud, flags, rc):
                if rc == 0:
                    self._log(f"MQTT verbunden mit {broker}:{port}")
                    c.subscribe(TOPIC_CMD)
                else:
                    self._log(f"MQTT Fehler (rc={rc})")

            def on_message(c, ud, msg):
                payload = msg.payload.decode("utf-8").strip().lower()
                if payload == "stop":
                    paused["value"] = True
                    self._log("Pausiert (MQTT Befehl)")
                elif payload == "start":
                    paused["value"] = False
                    self._log("Fortgesetzt (MQTT Befehl)")

            client.on_connect = on_connect
            client.on_message = on_message
            client.connect(broker, port, keepalive=60)
            client.loop_start()
            self.mqtt_client = client

        except Exception as err:
            self._log(f"MQTT Verbindungsfehler: {err}")
            self.root.after(0, self.stop)
            return

        time.sleep(1)
        last_hash = ""
        frames = 0
        errors = 0

        while not self.stop_event.is_set():
            if paused["value"]:
                time.sleep(2)
                continue

            try:
                jpeg_bytes, frame_hash = capture_screen(monitor, resize, quality)

                if detect_change and frame_hash == last_hash:
                    time.sleep(interval)
                    continue
                last_hash = frame_hash

                window_title, detector = detect_window_title()
                game = detect_active_game(window_title)
                effective_title = game or window_title or game_hint

                client.publish(topic_image, jpeg_bytes)

                meta = {
                    "client_type": "pc",
                    "window_title": effective_title,
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
                    "detector": detector,
                }
                client.publish(topic_meta, json.dumps(meta))

                frames += 1
                errors = 0
                size_kb = len(jpeg_bytes) // 1024
                self._log(f"Frame #{frames} ({size_kb} KB) – {effective_title or '(kein Spiel)'}")
                self.root.after(0, lambda: self.status_var.set(
                    f"Läuft... | Frames: {frames} | {effective_title or 'kein Spiel'}"
                ))

            except Exception as err:
                errors += 1
                self._log(f"Fehler: {err}")
                if errors >= 10:
                    self._log("Zu viele Fehler – stoppe")
                    self.root.after(0, self.stop)
                    return

            self.stop_event.wait(interval)

    # -- Run ---------------------------------------------------------------

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = GamingAssistantApp()
    app.run()
