"""
Gaming Assistant – Android TV / Google TV Capture Agent (Thin Client)
=====================================================================
Captures screenshots from Android TV devices over ADB and publishes
frames + metadata via MQTT for the Home Assistant Gaming Assistant pipeline.

Targets:
- Google TV / Android TV
- NVIDIA Shield
- TVs with Android TV firmware (Sony, Philips, ...)
- Fire TV devices with ADB enabled (best effort)

Requirements:
    pip install -r requirements-capture.txt
    adb available in PATH

Usage:
    python capture_agent_android_tv.py \
      --broker 192.168.1.10 \
      --device 192.168.1.55:5555 \
      --client-id livingroom-tv
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("capture_agent_android_tv")

TOPIC_CMD = "gaming_assistant/command"


def _adb_cmd(args: list[str], device: str | None = None) -> list[str]:
    """Build ADB command with optional device selector."""
    base = ["adb"]
    if device:
        base.extend(["-s", device])
    return [*base, *args]


def check_adb_connection(device: str | None = None) -> bool:
    """Verify ADB can talk to the selected device."""
    try:
        result = subprocess.run(
            _adb_cmd(["get-state"], device),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return result.returncode == 0 and "device" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def capture_tv_screen(
    device: str | None,
    resize: tuple[int, int],
    quality: int,
) -> tuple[bytes, str]:
    """Capture screen from Android TV device via adb exec-out screencap -p."""
    proc = subprocess.run(
        _adb_cmd(["exec-out", "screencap", "-p"], device),
        capture_output=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore") or "screencap failed")

    img = Image.open(BytesIO(proc.stdout)).convert("RGB")
    img = img.resize(resize, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    jpeg_bytes = buffer.getvalue()
    frame_hash = hashlib.md5(jpeg_bytes).hexdigest()

    return jpeg_bytes, frame_hash


def detect_foreground_package(device: str | None = None) -> str:
    """Try to extract currently focused app package from dumpsys window."""
    try:
        proc = subprocess.run(
            _adb_cmd(["shell", "dumpsys", "window", "windows"], device),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = proc.stdout
        # Typical line contains: mCurrentFocus=Window{... u0 com.package.name/...}
        for line in text.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                if " u0 " in line and "/" in line:
                    part = line.split(" u0 ", 1)[1]
                    pkg = part.split("/", 1)[0].strip()
                    if pkg and " " not in pkg:
                        return pkg
        return ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def build_mqtt_client(
    broker: str, port: int, username: str, password: str, client_id: str = ""
):
    """Create and connect MQTT client with Last Will (LWT)."""
    client = mqtt.Client(client_id="gaming_assistant_capture_android_tv", clean_session=True)

    if username:
        client.username_pw_set(username, password)

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


def main():
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – Android TV / Google TV Capture Agent"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=f"android-tv-{platform.node()}",
        help="Unique client ID (default: android-tv-hostname)",
    )
    parser.add_argument("--device", default=None, help="ADB device serial or IP:port")
    parser.add_argument("--interval", type=int, default=5, help="Seconds between captures")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality 1-100")
    parser.add_argument("--resize", default="960x540", help="Image size WxH")
    parser.add_argument("--game-hint", default="", help="Optional fixed game/game-type")
    parser.add_argument(
        "--detect-change", action="store_true",
        help="Skip sending if frame has not changed",
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
    log.info("Interval : %ds", args.interval)

    if not check_adb_connection(args.device):
        log.error(
            "Cannot reach Android TV via ADB. Enable developer mode + network debugging."
        )
        if args.device:
            log.info("Trying adb connect %s", args.device)
            subprocess.run(["adb", "connect", args.device], timeout=10, check=False)
            if not check_adb_connection(args.device):
                log.error("Still unreachable. Exiting.")
                return
        else:
            return

    client, running = build_mqtt_client(args.broker, args.port, args.user, args.password, client_id)
    time.sleep(1)

    last_hash = ""
    consecutive_errors = 0
    max_errors = 8

    try:
        while True:
            if not running["active"]:
                log.info("Agent paused – waiting for start command...")
                time.sleep(5)
                continue

            try:
                jpeg_bytes, frame_hash = capture_tv_screen(args.device, resize, args.quality)
                if args.detect_change and frame_hash == last_hash:
                    log.debug("Frame unchanged, skipping")
                    time.sleep(args.interval)
                    continue
                last_hash = frame_hash

                package_name = detect_foreground_package(args.device)

                client.publish(topic_image, jpeg_bytes)
                meta = {
                    "client_type": "android_tv",
                    "window_title": args.game_hint or package_name,
                    "app_package": package_name,
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
                    "transport": "adb",
                }
                client.publish(topic_meta, json.dumps(meta))

                log.info(
                    "Sent frame (%d KB) app=%s",
                    len(jpeg_bytes) // 1024,
                    package_name or args.game_hint or "(unknown)",
                )
                consecutive_errors = 0
            except Exception as err:  # pylint: disable=broad-except
                log.exception("Capture error: %s", err)
                consecutive_errors += 1

            if consecutive_errors >= max_errors:
                log.error("Too many consecutive errors (%d). Exiting.", max_errors)
                break

            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Stopping agent...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
