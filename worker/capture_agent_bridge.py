"""
Gaming Assistant – HDMI Bridge Capture Agent (Thin Client)
===========================================================
Captures frames from a Video4Linux device (e.g. a USB HDMI capture card
plugged into a Raspberry Pi or SBC) and publishes them as binary MQTT
images to Home Assistant.

Typical sources:
- USB HDMI capture dongle on /dev/video0 (MacroSilicon MS2109, UVC)
- Raspberry Pi CSI camera exposed via v4l2
- Any other UVC-compatible capture device

Why this agent exists:
- Lets game consoles (PlayStation, Switch, Xbox, Dreamcast, …) be analyzed
  without installing anything on the console itself.
- Keeps the Thin-Client contract intact: just capture + MQTT, all
  intelligence runs in Home Assistant.

Requirements:
    pip install -r requirements-capture.txt
    # OpenCV provides the v4l2 backend used here:
    pip install opencv-python

Usage:
    python capture_agent_bridge.py --broker 192.168.1.10 --device /dev/video0

    # With all options:
    python capture_agent_bridge.py \\
      --broker 192.168.1.10 \\
      --device /dev/video0 \\
      --client-id console-hdmi \\
      --interval 2 \\
      --quality 70 \\
      --resize 960x540 \\
      --game-hint "Elden Ring" \\
      --detect-change

Systemd example (Raspberry Pi):
    See worker/systemd/gaming-assistant-bridge.service in this repo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import time
from io import BytesIO

import paho.mqtt.client as mqtt
from PIL import Image

try:  # pragma: no cover - import guard tested indirectly
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("capture_agent_bridge")


# ---------------------------------------------------------------------------
# MQTT Topics
# ---------------------------------------------------------------------------
TOPIC_CMD = "gaming_assistant/command"


# ---------------------------------------------------------------------------
# Frame capture
# ---------------------------------------------------------------------------
def open_device(device: str, width: int, height: int):
    """Open a v4l2 device via OpenCV and configure capture resolution.

    `device` may be an integer index ("0") or a path ("/dev/video0").
    """
    if cv2 is None:
        raise RuntimeError(
            "opencv-python is not installed. Run `pip install opencv-python` "
            "on the bridge host."
        )

    # OpenCV accepts an int index or a string path. Normalize for /dev/videoN.
    target: int | str
    if device.isdigit():
        target = int(device)
    elif device.startswith("/dev/video"):
        try:
            target = int(device.replace("/dev/video", ""))
        except ValueError:
            target = device
    else:
        target = device

    cap = cv2.VideoCapture(target, cv2.CAP_V4L2)
    if not cap.isOpened():
        # Fall back to default backend on non-Linux hosts.
        cap = cv2.VideoCapture(target)

    if not cap.isOpened():
        raise RuntimeError(f"Could not open capture device '{device}'.")

    # Request capture resolution; actual size may differ (fallback to native).
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def grab_frame(
    cap, resize: tuple[int, int], quality: int
) -> tuple[bytes, str]:
    """Read one frame -> resize -> JPEG bytes + hash."""
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError("Capture device returned no frame")

    # OpenCV frames are BGR; convert to RGB before Pillow encode.
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
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
    client = mqtt.Client(
        client_id="gaming_assistant_capture_bridge", clean_session=True
    )

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
                    "online",
                    qos=1,
                    retain=True,
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
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – HDMI Bridge Capture Agent (Thin Client)"
    )
    parser.add_argument("--broker", required=True, help="MQTT broker IP/hostname")
    parser.add_argument(
        "--device", default="/dev/video0",
        help="V4L2 device path or index (default: /dev/video0)",
    )
    parser.add_argument("--port", type=int, default=1883, help="MQTT port")
    parser.add_argument("--user", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=f"bridge-{platform.node()}",
        help="Unique client ID (default: bridge-hostname)",
    )
    parser.add_argument("--interval", type=int, default=2, help="Seconds between captures")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality 1-100")
    parser.add_argument("--resize", default="960x540", help="Image size WxH")
    parser.add_argument(
        "--capture-resolution", default="1280x720",
        help="Requested capture resolution WxH (default: 1280x720)",
    )
    parser.add_argument(
        "--game-hint", default="",
        help="Fixed game name (recommended for consoles without title detection)",
    )
    parser.add_argument(
        "--client-type", default="console",
        choices=["console", "pc", "tabletop"],
        help="Source type reported to HA (default: console)",
    )
    parser.add_argument(
        "--detect-change", action="store_true",
        help="Skip sending if frame has not changed",
    )
    args = parser.parse_args()

    try:
        w, h = args.resize.lower().split("x")
        resize = (int(w), int(h))
        cw, ch = args.capture_resolution.lower().split("x")
        capture_size = (int(cw), int(ch))
    except ValueError:
        log.error("Invalid --resize / --capture-resolution format. Use WxH, e.g. 960x540")
        return

    client_id = args.client_id
    topic_image = f"gaming_assistant/{client_id}/image"
    topic_meta = f"gaming_assistant/{client_id}/meta"

    log.info("=== Gaming Assistant – HDMI Bridge Capture Agent ===")
    log.info("Broker     : %s:%d", args.broker, args.port)
    log.info("Client ID  : %s", client_id)
    log.info("Device     : %s", args.device)
    log.info("Capture    : %dx%d -> Send: %dx%d @ q=%d",
             capture_size[0], capture_size[1], resize[0], resize[1], args.quality)
    log.info("Interval   : %ds", args.interval)
    log.info("Client type: %s", args.client_type)
    log.info("Game hint  : %s", args.game_hint or "(none)")
    log.info("Change det.: %s", "ON" if args.detect_change else "OFF")

    try:
        cap = open_device(args.device, capture_size[0], capture_size[1])
    except RuntimeError as err:
        log.error("Cannot start: %s", err)
        return

    client, running = build_mqtt_client(
        args.broker, args.port, args.user, args.password, client_id
    )
    time.sleep(1)

    last_hash = ""
    consecutive_errors = 0
    max_errors = 20
    backoff_base = 2
    backoff_cap = 60

    try:
        while True:
            if not running["active"]:
                log.info("Agent paused – waiting for start command...")
                time.sleep(5)
                continue

            had_error = False
            try:
                jpeg_bytes, frame_hash = grab_frame(cap, resize, args.quality)

                if args.detect_change and frame_hash == last_hash:
                    log.debug("Frame unchanged, skipping")
                    time.sleep(args.interval)
                    continue
                last_hash = frame_hash

                client.publish(topic_image, jpeg_bytes)

                meta = {
                    "client_type": args.client_type,
                    "window_title": args.game_hint,
                    "resolution": f"{resize[0]}x{resize[1]}",
                    "timestamp": int(time.time()),
                    "source_device": args.device,
                    "detector": "hdmi-bridge",
                }
                client.publish(topic_meta, json.dumps(meta))

                log.info(
                    "Sent frame (%d KB) game=%s",
                    len(jpeg_bytes) // 1024,
                    args.game_hint or "(hint not set)",
                )
                consecutive_errors = 0

            except RuntimeError as err:
                log.warning("Capture failed: %s", err)
                consecutive_errors += 1
                had_error = True
            except Exception as err:  # noqa: BLE001 - log anything unexpected
                log.exception("Unexpected capture error: %s", err)
                consecutive_errors += 1
                had_error = True

            if consecutive_errors >= max_errors:
                log.error(
                    "Too many consecutive errors (%d). Exiting.", max_errors
                )
                break

            if had_error:
                backoff = min(backoff_base ** consecutive_errors, backoff_cap)
                sleep_for = max(backoff, args.interval)
                log.info(
                    "Backing off %.1fs after %d consecutive errors",
                    sleep_for, consecutive_errors,
                )
                time.sleep(sleep_for)
            else:
                time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Stopping agent...")
    finally:
        try:
            cap.release()
        except Exception:  # noqa: BLE001
            pass
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":  # pragma: no cover
    main()
