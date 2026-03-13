"""
Gaming Assistant – Android TV Capture Agent (Thin Client)
==========================================================
Captures screenshots from an Android TV / Google TV device via ADB,
compresses them as JPEG, and publishes raw bytes to Home Assistant via MQTT.

All intelligence runs in Home Assistant. This agent only captures and sends.

Requirements:
    pip install -r requirements-capture.txt

Prerequisites:
    - ADB installed and in PATH
    - Android TV device with developer options and network debugging enabled
    - Device paired via: adb pair <ip>:<pairing-port>

Usage:
    python capture_agent_android_tv.py --broker 192.168.1.10 --device 192.168.1.100:5555
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
from PIL import Image

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("capture_agent_android_tv")

# ---------------------------------------------------------------------------
# MQTT Topics
# ---------------------------------------------------------------------------
TOPIC_CMD = "gaming_assistant/command"

# ---------------------------------------------------------------------------
# Known Android TV games / apps
# ---------------------------------------------------------------------------
KNOWN_GAMES = [
    "PUBG", "Call of Duty", "Genshin Impact", "Honkai",
    "Minecraft", "Stadia", "GeForce NOW", "Xbox Game Pass",
    "Steam Link", "Moonlight", "Asphalt", "Dead Cells",
    "Diablo Immortal", "Alto's Odyssey", "Crossy Road",
]


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------
def _adb_cmd(args: list[str], device: str | None = None) -> list[str]:
    cmd = ["adb"]
    if device:
        cmd.extend(["-s", device])
    cmd.extend(args)
    return cmd


def check_adb_connection(device: str | None = None) -> bool:
    try:
        result = subprocess.run(
            _adb_cmd(["shell", "echo", "ok"], device),
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def capture_tv_screen(
    device: str | None = None,
    resize: tuple[int, int] = (960, 540),
    quality: int = 75,
) -> tuple[bytes, str]:
    """Capture screenshot from Android TV via ADB screencap."""
    result = subprocess.run(
        _adb_cmd(["exec-out", "screencap", "-p"], device),
        capture_output=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ADB screencap failed: {result.stderr.decode(errors='replace')}"
        )

    img = Image.open(BytesIO(result.stdout)).convert("RGB")
    img = img.resize(resize, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    jpeg_bytes = buffer.getvalue()

    return jpeg_bytes, hashlib.md5(jpeg_bytes).hexdigest()


def detect_foreground_app(device: str | None = None) -> str:
    """Detect the foreground app/game on Android TV via dumpsys."""
    try:
        result = subprocess.run(
            _adb_cmd(
                ["shell", "dumpsys", "activity", "activities",
                 "|", "grep", "mResumedActivity"],
                device,
            ),
            capture_output=True, text=True, timeout=10,
        )
        activity_line = result.stdout.strip()
        for game in KNOWN_GAMES:
            if game.lower().replace(" ", "") in activity_line.lower():
                return game
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def build_mqtt_client(broker: str, port: int, username: str, password: str):
    client = mqtt.Client(
        client_id="gaming_assistant_capture_android_tv", clean_session=True
    )
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
        description="Gaming Assistant – Android TV Capture Agent (Thin Client)"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=f"android-tv-{platform.node()}",
        help="Unique client ID (default: android-tv-hostname)",
    )
    parser.add_argument("--interval", type=int, default=5, help="Seconds between captures")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality 1-100")
    parser.add_argument("--resize", default="960x540", help="Image size WxH")
    parser.add_argument(
        "--device", default=None,
        help="ADB device serial or IP:port (e.g. 192.168.1.100:5555)",
    )
    parser.add_argument("--game-hint", default="", help="Manual game name hint")
    parser.add_argument(
        "--detect-change", action="store_true",
        help="Skip sending if frame hasn't changed",
    )
    args = parser.parse_args()

    try:
        w, h = args.resize.lower().split("x")
        resize = (int(w), int(h))
    except ValueError:
        log.error("Invalid --resize format. Use WxH, e.g. 960x540")
        return

    client_id = args.client_id
    topic_image = f"gaming_assistant/{client_id}/image"
    topic_meta = f"gaming_assistant/{client_id}/meta"

    log.info("=== Gaming Assistant – Android TV Capture Agent ===")
    log.info("Broker   : %s:%d", args.broker, args.port)
    log.info("Client ID: %s", client_id)
    log.info("Device   : %s", args.device or "default")

    if not check_adb_connection(args.device):
        log.error("Cannot reach Android TV device via ADB.")
        if args.device:
            subprocess.run(["adb", "connect", args.device], timeout=10)
            if not check_adb_connection(args.device):
                log.error("Still cannot reach device. Exiting.")
                return
        else:
            return

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
                game = args.game_hint or detect_foreground_app(args.device)
                jpeg_bytes, frame_hash = capture_tv_screen(
                    args.device, resize, args.quality
                )

                if args.detect_change and frame_hash == last_hash:
                    time.sleep(args.interval)
                    continue
                last_hash = frame_hash

                client.publish(topic_image, jpeg_bytes)
                meta = {
                    "client_type": "android_tv",
                    "window_title": game,
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
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
                log.error("Too many errors (%d). Exiting.", MAX_ERRORS)
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Android TV capture agent stopped.")


if __name__ == "__main__":
    main()
