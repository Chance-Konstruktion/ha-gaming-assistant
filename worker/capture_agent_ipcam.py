"""
Gaming Assistant – IP Webcam Capture Agent (Thin Client)
=========================================================
Captures JPEG frames from an IP Webcam endpoint and publishes them
as binary MQTT images to Home Assistant.

Typical sources:
- Android IP Webcam app (`http://<phone-ip>:8080/shot.jpg`)
- iOS camera apps with JPEG snapshot endpoint
- Any local MJPEG/JPEG snapshot source

Requirements:
    pip install -r requirements-capture.txt

Usage:
    python capture_agent_ipcam.py \
      --broker 192.168.1.10 \
      --url http://192.168.1.42:8080/shot.jpg \
      --client-id console-cam
"""

import argparse
import hashlib
import json
import logging
import platform
import time
from io import BytesIO

import paho.mqtt.client as mqtt
import requests
from PIL import Image

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("capture_agent_ipcam")

# ---------------------------------------------------------------------------
# MQTT Topics
# ---------------------------------------------------------------------------
TOPIC_CMD = "gaming_assistant/command"


# ---------------------------------------------------------------------------
# Frame fetch + processing
# ---------------------------------------------------------------------------
def fetch_snapshot(
    url: str,
    timeout: int,
    resize: tuple[int, int],
    quality: int,
    auth_user: str,
    auth_password: str,
) -> tuple[bytes, str]:
    """Fetch one snapshot from URL -> resize/compress -> bytes + hash."""
    auth = (auth_user, auth_password) if auth_user else None
    response = requests.get(url, timeout=timeout, auth=auth)
    response.raise_for_status()

    img = Image.open(BytesIO(response.content)).convert("RGB")
    img = img.resize(resize, Image.LANCZOS)

    output = BytesIO()
    img.save(output, format="JPEG", quality=quality)
    jpeg_bytes = output.getvalue()
    frame_hash = hashlib.md5(jpeg_bytes).hexdigest()

    return jpeg_bytes, frame_hash


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def build_mqtt_client(
    broker: str, port: int, username: str, password: str, client_id: str = ""
):
    """Create and connect the MQTT client with Last Will (LWT)."""
    client = mqtt.Client(client_id="gaming_assistant_capture_ipcam", clean_session=True)

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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – IP Webcam Capture Agent (Thin Client)"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument("--url", required=True, help="Snapshot URL (e.g. .../shot.jpg)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument("--auth-user", default="", help="HTTP basic auth username")
    parser.add_argument("--auth-password", default="", help="HTTP basic auth password")
    parser.add_argument("--timeout", type=int, default=8, help="HTTP timeout in seconds")
    parser.add_argument(
        "--client-id", default=f"ipcam-{platform.node()}",
        help="Unique client ID (default: ipcam-hostname)",
    )
    parser.add_argument("--interval", type=int, default=5, help="Seconds between captures")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality 1-100")
    parser.add_argument("--resize", default="960x540", help="Image size WxH")
    parser.add_argument("--game-hint", default="", help="Optional fixed game name")
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

    log.info("=== Gaming Assistant – IP Webcam Capture Agent ===")
    log.info("Broker   : %s:%d", args.broker, args.port)
    log.info("Client ID: %s", client_id)
    log.info("URL      : %s", args.url)
    log.info("Interval : %ds", args.interval)
    log.info("Resize   : %s", args.resize)
    log.info("Quality  : %d", args.quality)
    log.info("Change detection: %s", "ON" if args.detect_change else "OFF")

    client, running = build_mqtt_client(
        args.broker, args.port, args.user, args.password, client_id
    )
    time.sleep(1)

    last_hash = ""
    consecutive_errors = 0
    max_errors = 20

    try:
        while True:
            if not running["active"]:
                log.info("Agent paused – waiting for start command...")
                time.sleep(5)
                continue

            try:
                jpeg_bytes, frame_hash = fetch_snapshot(
                    args.url,
                    args.timeout,
                    resize,
                    args.quality,
                    args.auth_user,
                    args.auth_password,
                )

                if args.detect_change and frame_hash == last_hash:
                    log.debug("Frame unchanged, skipping")
                    time.sleep(args.interval)
                    continue
                last_hash = frame_hash

                client.publish(topic_image, jpeg_bytes)

                meta = {
                    "client_type": "ipcam",
                    "window_title": args.game_hint,
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
                    "source_url": args.url,
                }
                client.publish(topic_meta, json.dumps(meta))

                log.info(
                    "Sent frame (%d KB) game=%s",
                    len(jpeg_bytes) // 1024,
                    args.game_hint or "(hint not set)",
                )
                consecutive_errors = 0

            except requests.RequestException as err:
                log.warning("Snapshot request failed: %s", err)
                consecutive_errors += 1
            except Exception as err:
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
