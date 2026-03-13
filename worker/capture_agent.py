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

Linux/X11 note:
    If `xprop` is available, the agent tries to read the active window title.
    Wayland support is best-effort only; use --game-hint as fallback.

Usage:
    python capture_agent.py --broker 192.168.1.10
"""

import argparse
import hashlib
import json
import logging
import platform
import subprocess
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
# Game detection helpers
# ---------------------------------------------------------------------------
def _detect_window_title_windows() -> str:
    """Return foreground window title on Windows (pywin32)."""
    try:
        import win32gui

        return win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except ImportError:
        return ""
    except Exception:
        return ""


def _detect_window_title_x11() -> str:
    """Return active window title via xprop (Linux/X11)."""
    try:
        active = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if active.returncode != 0 or "#" not in active.stdout:
            return ""

        window_id = active.stdout.split("#", 1)[1].strip()
        if not window_id:
            return ""

        title = subprocess.run(
            ["xprop", "-id", window_id, "_NET_WM_NAME"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if title.returncode != 0:
            return ""

        # Example output: _NET_WM_NAME(UTF8_STRING) = "Game Title"
        if "=" not in title.stdout:
            return ""
        value = title.stdout.split("=", 1)[1].strip().strip('"')
        return value
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def detect_window_title() -> tuple[str, str]:
    """Return (window title, detector source)."""
    # 1) Windows API
    win_title = _detect_window_title_windows()
    if win_title:
        return win_title, "win32gui"

    # 2) Linux X11 via xprop
    x11_title = _detect_window_title_x11()
    if x11_title:
        return x11_title, "x11_xprop"

    # 3) Unknown/unsupported (often Wayland without tooling)
    return "", "none"


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
    parser.add_argument("--game-hint", default="", help="Manual fallback game/app hint")
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
    max_errors = 5

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

                # 3. Detect window title / game
                window_title, detector = detect_window_title()
                game = detect_active_game(window_title)
                effective_title = game or window_title or args.game_hint

                client.publish(topic_image, jpeg_bytes)

                meta = {
                    "client_type": "pc",
                    "window_title": effective_title,
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
                    "detector": detector,
                }
                client.publish(topic_meta, json.dumps(meta))

                log.info(
                    "Sent frame (%d KB) game=%s detector=%s",
                    len(jpeg_bytes) // 1024,
                    effective_title or "(unknown)",
                    detector,
                )
                consecutive_errors = 0

            except Exception as err:
                log.exception("Capture error: %s", err)
                consecutive_errors += 1

            if consecutive_errors >= max_errors:
                log.error("Too many consecutive errors (%d). Exiting.", max_errors)
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
