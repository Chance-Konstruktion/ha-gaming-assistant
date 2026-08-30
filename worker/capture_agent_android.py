"""
Gaming Assistant – Android Capture Agent (Thin Client)
=======================================================
Captures screenshots from an Android device via ADB, compresses them as JPEG,
and publishes raw bytes to Home Assistant via MQTT.

All intelligence runs in Home Assistant. This agent only captures and sends.

Requirements:
    pip install -r requirements-capture.txt

Prerequisites:
    - ADB installed and in PATH
    - Android device connected via USB or Wi-Fi with USB debugging enabled

Usage:
    python capture_agent_android.py --broker 192.168.1.10

    # Target a specific device:
    python capture_agent_android.py --broker 192.168.1.10 --device 192.168.1.42:5555
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
log = logging.getLogger("capture_agent_android")

# ---------------------------------------------------------------------------
# MQTT Topics
# ---------------------------------------------------------------------------
TOPIC_CMD = "gaming_assistant/command"

# ---------------------------------------------------------------------------
# Known mobile games for auto-detection
# ---------------------------------------------------------------------------
KNOWN_GAMES = [
    "PUBG", "Call of Duty", "Genshin Impact", "Honkai",
    "Minecraft", "Brawl Stars", "Clash Royale", "Clash of Clans",
    "Diablo Immortal", "Wild Rift", "Arena of Valor",
    "Asphalt", "Mobile Legends", "Free Fire",
]


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------
def _adb_cmd(args: list[str], device: str | None = None) -> list[str]:
    """Build an ADB command list, optionally targeting a specific device."""
    cmd = ["adb"]
    if device:
        cmd.extend(["-s", device])
    cmd.extend(args)
    return cmd


def check_adb_connection(device: str | None = None) -> bool:
    """Verify that ADB can reach the target device."""
    try:
        result = subprocess.run(
            _adb_cmd(["shell", "echo", "ok"], device),
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def capture_android_screen(
    device: str | None = None,
    resize: tuple[int, int] = (960, 540),
    quality: int = 75,
) -> tuple[bytes, str]:
    """Capture a screenshot from Android via ADB.

    Returns (jpeg_bytes, frame_hash).
    """
    result = subprocess.run(
        _adb_cmd(["exec-out", "screencap", "-p"], device),
        capture_output=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ADB screencap failed (rc={result.returncode}): "
            f"{result.stderr.decode(errors='replace')}"
        )

    img = Image.open(BytesIO(result.stdout)).convert("RGB")
    img = img.resize(resize, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    jpeg_bytes = buffer.getvalue()

    frame_hash = hashlib.md5(jpeg_bytes).hexdigest()
    return jpeg_bytes, frame_hash


def detect_foreground_app(device: str | None = None) -> str:
    """Detect the foreground app on the Android device.

    Returns the game name if a known game is running, or empty string.
    """
    try:
        result = subprocess.run(
            _adb_cmd(["shell", "dumpsys", "activity", "activities"], device),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ""

        resumed_lines = [
            line for line in result.stdout.splitlines() if "mResumedActivity" in line
        ]
        haystack = " ".join(resumed_lines).lower()

        for game in KNOWN_GAMES:
            normalized = game.lower().replace(" ", "")
            if normalized in haystack.replace(" ", ""):
                return game
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def build_mqtt_client(
    broker: str, port: int, username: str, password: str, client_id: str = ""
):
    """Create and connect the MQTT client with Last Will (LWT)."""
    client = mqtt.Client(
        client_id="gaming_assistant_capture_android", clean_session=True
    )

    if username:
        client.username_pw_set(username, password)

    # Set Last Will and Testament — broker publishes this if we disconnect unexpectedly
    if client_id:
        lwt_topic = f"gaming_assistant/{client_id}/status"
        client.will_set(lwt_topic, payload="offline", qos=1, retain=True)

    running = {"active": True}

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connected to %s:%d", broker, port)
            c.subscribe(TOPIC_CMD)
            if client_id:
                c.publish(
                    f"gaming_assistant/{client_id}/status",
                    "online", qos=1, retain=True,
                )
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
        description="Gaming Assistant – Android Capture Agent (Thin Client)"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=f"android-{platform.node()}",
        help="Unique client ID (default: android-hostname)"
    )
    parser.add_argument("--interval", type=int, default=5, help="Seconds between captures")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality 1-100")
    parser.add_argument("--resize", default="960x540", help="Image size WxH")
    parser.add_argument("--device", default=None, help="ADB device serial or IP:port")
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

    log.info("=== Gaming Assistant – Android Capture Agent ===")
    log.info("Broker   : %s:%d", args.broker, args.port)
    log.info("Client ID: %s", client_id)
    log.info("Interval : %ds", args.interval)
    log.info("Device   : %s", args.device or "default (first connected)")

    # Verify ADB connection
    if not check_adb_connection(args.device):
        log.error(
            "Cannot reach Android device via ADB. "
            "Make sure USB debugging is enabled and the device is connected."
        )
        if args.device:
            log.error("Trying to connect to %s ...", args.device)
            subprocess.run(["adb", "connect", args.device], timeout=10)
            if not check_adb_connection(args.device):
                log.error("Still cannot reach device. Exiting.")
                return
        else:
            return

    log.info("ADB connection verified")

    client, running = build_mqtt_client(
        args.broker, args.port, args.user, args.password, client_id
    )
    time.sleep(1)  # Let MQTT connect

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
                # 1. Detect foreground game
                game = detect_foreground_app(args.device)

                # 2. Capture screenshot via ADB
                jpeg_bytes, frame_hash = capture_android_screen(
                    args.device, resize, args.quality
                )

                # 3. Optional: frame change detection
                if args.detect_change and frame_hash == last_hash:
                    log.debug("Frame unchanged, skipping")
                    time.sleep(args.interval)
                    continue
                last_hash = frame_hash

                # 4. Publish image as raw JPEG bytes
                client.publish(topic_image, jpeg_bytes)

                # 5. Publish metadata as JSON
                meta = {
                    "client_type": "android",
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

            except RuntimeError as e:
                log.error("ADB error: %s", e)
                consecutive_errors += 1

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
        log.info("Android capture agent stopped.")


if __name__ == "__main__":
    main()
