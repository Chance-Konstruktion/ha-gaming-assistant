"""
Gaming Assistant – Capture Agent (Thin Client)
===============================================
Runs on the Gaming PC. Captures screenshots, compresses them as JPEG,
and publishes raw bytes to Home Assistant via MQTT.

All intelligence (prompt building, game analysis, spoiler control) runs
in Home Assistant. This agent only captures and sends images.

Requirements:
    pip install -r requirements-capture.txt

Optional (game detection on Windows):
    pip install pywin32

Usage:
    python capture_agent.py --broker 192.168.1.10
"""

import argparse
import hashlib
import json
import logging
import platform
import time
from io import BytesIO

import paho.mqtt.client as mqtt
from mss import mss
from PIL import Image

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("capture_agent")

# ---------------------------------------------------------------------------
# MQTT Topics
# ---------------------------------------------------------------------------
TOPIC_CMD = "gaming_assistant/command"

# ---------------------------------------------------------------------------
# Known games for window title detection
# ---------------------------------------------------------------------------
KNOWN_GAMES = [
    "Wolfenstein", "Doom", "Cyberpunk", "Elden Ring",
    "Dark Souls", "Minecraft", "Counter-Strike", "Valorant",
    "Overwatch", "Baldur's Gate", "Starfield", "The Witcher",
    "Hogwarts Legacy", "Diablo", "Path of Exile", "Fortnite",
]


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------
def capture_screen(
    monitor_index: int = 1,
    resize: tuple[int, int] = (960, 540),
    quality: int = 75,
) -> tuple[bytes, str]:
    """Capture -> Resize -> JPEG bytes + hash."""
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


# ---------------------------------------------------------------------------
# Game detection (Windows only, graceful fallback)
# ---------------------------------------------------------------------------
def _detect_window_title_windows() -> str:
    """Return the foreground window title on Windows via win32gui."""
    try:
        import win32gui
        return win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except ImportError:
        pass
    except Exception:
        pass
    return ""


def _detect_window_title_x11() -> str:
    """Return the focused window title on Linux/X11 via xprop."""
    import subprocess
    try:
        # Get the active window ID
        result = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ""
        # Extract window ID (e.g. "0x1234567")
        parts = result.stdout.strip().split()
        window_id = parts[-1] if parts else ""
        if not window_id or window_id == "0x0":
            return ""
        # Get the window name
        result = subprocess.run(
            ["xprop", "-id", window_id, "WM_NAME"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ""
        # Parse: WM_NAME(STRING) = "Window Title"
        line = result.stdout.strip()
        if "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def detect_window_title() -> str:
    """Return the foreground window title (Windows: win32gui, Linux/X11: xprop)."""
    if platform.system() == "Windows":
        return _detect_window_title_windows()
    return _detect_window_title_x11()


def detect_active_game(window_title: str) -> str:
    """Match window title against known games."""
    title_lower = window_title.lower()
    for game in KNOWN_GAMES:
        if game.lower() in title_lower:
            return game
    return ""


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def build_mqtt_client(broker: str, port: int, username: str, password: str):
    """Create and connect the MQTT client."""
    client = mqtt.Client(client_id="gaming_assistant_capture", clean_session=True)

    if username:
        client.username_pw_set(username, password)

    running = {"active": True}

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connected to %s:%d", broker, port)
            c.subscribe(TOPIC_CMD)
        else:
            log.error("MQTT connection failed (rc=%d)", rc)

    def on_message(c, userdata, msg):
        payload = msg.payload.decode("utf-8").strip().lower()
        log.info("MQTT command received: %s", payload)
        if payload == "stop":
            running["active"] = False
        elif payload == "start":
            running["active"] = True

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(broker, port, keepalive=60)
    client.loop_start()

    return client, running


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – Capture Agent (Thin Client)"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=platform.node(),
        help="Unique client ID (default: hostname)"
    )
    parser.add_argument("--interval", type=int, default=5, help="Seconds between captures")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality 1-100")
    parser.add_argument("--resize", default="960x540", help="Image size WxH")
    parser.add_argument("--monitor", type=int, default=1, help="Monitor index (1=primary)")
    parser.add_argument(
        "--game-hint", default="",
        help="Manual game name hint (useful on Wayland where auto-detection fails)",
    )
    parser.add_argument(
        "--detect-change", action="store_true",
        help="Skip sending if frame hasn't changed"
    )
    args = parser.parse_args()

    # Parse resize
    try:
        w, h = args.resize.lower().split("x")
        resize = (int(w), int(h))
    except ValueError:
        log.error("Invalid --resize format. Use WxH, e.g. 960x540")
        return

    client_id = args.client_id
    topic_image = f"gaming_assistant/{client_id}/image"
    topic_meta = f"gaming_assistant/{client_id}/meta"

    log.info("=== Gaming Assistant – Capture Agent ===")
    log.info("Broker   : %s:%d", args.broker, args.port)
    log.info("Client ID: %s", client_id)
    log.info("Interval : %ds", args.interval)
    log.info("Quality  : %d", args.quality)
    log.info("Resize   : %s", args.resize)
    log.info("Monitor  : %d", args.monitor)

    client, running = build_mqtt_client(
        args.broker, args.port, args.user, args.password
    )
    time.sleep(1)

    last_hash = ""
    consecutive_errors = 0
    MAX_ERRORS = 5

    try:
        while True:
            if not running["active"]:
                log.info("Agent paused – waiting for start command...")
                time.sleep(5)
                continue

            try:
                jpeg_bytes, frame_hash = capture_screen(
                    args.monitor, resize, args.quality
                )

                if args.detect_change and frame_hash == last_hash:
                    log.debug("Frame unchanged, skipping")
                    time.sleep(args.interval)
                    continue
                last_hash = frame_hash

                if args.game_hint:
                    game = args.game_hint
                else:
                    window_title = detect_window_title()
                    game = detect_active_game(window_title)

                client.publish(topic_image, jpeg_bytes)

                meta = {
                    "client_type": "pc",
                    "window_title": game if args.game_hint else (game or window_title),
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
                    "detector": "hint" if args.game_hint else platform.system().lower(),
                }
                client.publish(topic_meta, json.dumps(meta))

                log.info(
                    "Sent frame (%d KB) game=%s",
                    len(jpeg_bytes) // 1024,
                    game or "(unknown)",
                )
                consecutive_errors = 0

            except Exception as e:
                log.exception("Capture error: %s", e)
                consecutive_errors += 1

            if consecutive_errors >= MAX_ERRORS:
                log.error("Too many consecutive errors (%d). Exiting.", MAX_ERRORS)
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Shutting down...")

    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Capture agent stopped.")


if __name__ == "__main__":
    main()
