"""
Gaming Assistant – Android Worker
==================================
Captures screenshots from an Android device via ADB, analyzes them with a
local Vision LLM (Ollama), and publishes tips to Home Assistant via MQTT.

Requirements:
    pip install -r requirements-android.txt

Prerequisites:
    - ADB installed and in PATH (comes with Android SDK Platform Tools)
    - Android device connected via USB or Wi-Fi with USB debugging enabled
    - Ollama running with a vision model

Usage:
    python android_worker.py --broker 192.168.1.10 --model qwen2.5vl

    # Connect to a specific device (if multiple connected)
    python android_worker.py --broker 192.168.1.10 --device 192.168.1.42:5555

    # Connect via Wi-Fi ADB (device must be paired first)
    adb tcpip 5555
    adb connect 192.168.1.42:5555
    python android_worker.py --broker 192.168.1.10 --device 192.168.1.42:5555
"""

import argparse
import base64
import hashlib
import logging
import subprocess
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
log = logging.getLogger("gaming_assistant_android")

# ---------------------------------------------------------------------------
# MQTT Topics (same as desktop worker)
# ---------------------------------------------------------------------------
TOPIC_TIP = "gaming_assistant/tip"
TOPIC_MODE = "gaming_assistant/gaming_mode"
TOPIC_STATUS = "gaming_assistant/status"
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
    device: str | None = None, resize: tuple[int, int] = (960, 540)
) -> tuple[str, str]:
    """Capture a screenshot from the Android device via ADB.

    Returns (base64_string, frame_hash).
    """
    # screencap -p outputs a PNG directly to stdout
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
    img.save(buffer, format="JPEG", quality=85)
    raw = buffer.getvalue()

    img_b64 = base64.b64encode(raw).decode("utf-8")
    img_hash = hashlib.md5(raw).hexdigest()

    return img_b64, img_hash


def detect_foreground_app(device: str | None = None) -> str:
    """Detect the foreground app on the Android device.

    Returns the game name if a known game is running, or empty string.
    """
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
# Ollama analysis (shared logic with desktop worker)
# ---------------------------------------------------------------------------
def analyze_screenshot(img_b64: str, host: str, model: str, game_hint: str = "") -> str:
    """Send screenshot to Ollama and return the tip."""
    game_context = f" The player is playing {game_hint} on a mobile device." if game_hint else ""
    prompt = (
        f"You are a helpful mobile gaming coach.{game_context} "
        "Look at this game screenshot and give exactly ONE short, "
        "specific, actionable gameplay tip in one sentence. "
        "No introduction, no emojis, just the tip."
    )

    response = requests.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": 60,
            },
        },
        timeout=45,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def build_mqtt_client(broker: str, port: int, username: str, password: str):
    """Create and connect the MQTT client."""
    client = mqtt.Client(client_id="gaming_assistant_android", clean_session=True)

    if username:
        client.username_pw_set(username, password)

    running = {"active": True}

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connected to %s:%d", broker, port)
            c.publish(TOPIC_STATUS, "connected", retain=True)
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
    parser = argparse.ArgumentParser(description="Gaming Assistant – Android Worker")
    parser.add_argument("--broker", default="homeassistant.local",
                        help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=1883,
                        help="MQTT port")
    parser.add_argument("--user", default="",
                        help="MQTT username (optional)")
    parser.add_argument("--password", default="",
                        help="MQTT password (optional)")
    parser.add_argument("--ollama", default="http://localhost:11434",
                        help="Ollama base URL")
    parser.add_argument("--model", default="qwen2.5vl",
                        help="Ollama vision model")
    parser.add_argument("--interval", type=int, default=10,
                        help="Seconds between analyses")
    parser.add_argument("--device", default=None,
                        help="ADB device serial or IP:port (optional)")
    args = parser.parse_args()

    log.info("=== Gaming Assistant – Android Worker ===")
    log.info("Broker  : %s:%d", args.broker, args.port)
    log.info("Ollama  : %s  model=%s", args.ollama, args.model)
    log.info("Interval: %ds", args.interval)
    log.info("Device  : %s", args.device or "default (first connected)")

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

    client, running = build_mqtt_client(args.broker, args.port, args.user, args.password)
    time.sleep(1)  # Let MQTT connect

    last_hash = ""
    consecutive_errors = 0
    MAX_ERRORS = 5

    try:
        while True:
            if not running["active"]:
                log.info("Worker paused – waiting for start command...")
                client.publish(TOPIC_STATUS, "paused")
                client.publish(TOPIC_MODE, "OFF")
                time.sleep(5)
                continue

            try:
                # 1. Detect foreground game
                game = detect_foreground_app(args.device)
                if game:
                    log.info("Game detected: %s", game)
                    client.publish(TOPIC_MODE, "ON")
                else:
                    client.publish(TOPIC_MODE, "OFF")

                # 2. Capture screenshot via ADB
                img_b64, img_hash = capture_android_screen(args.device)

                # 3. Frame change detection – skip if screen hasn't changed
                if img_hash == last_hash:
                    log.debug("Frame unchanged, skipping analysis")
                    time.sleep(args.interval)
                    continue
                last_hash = img_hash

                # 4. Analyze with Vision LLM
                client.publish(TOPIC_STATUS, "analyzing")
                tip = analyze_screenshot(img_b64, args.ollama, args.model, game)
                log.info("TIP: %s", tip)

                # 5. Publish tip
                client.publish(TOPIC_TIP, tip, retain=True)
                client.publish(TOPIC_MODE, "ON" if game else "OFF", retain=True)
                client.publish(TOPIC_STATUS, "idle")

                consecutive_errors = 0

            except requests.exceptions.Timeout:
                log.warning("Ollama timeout – model may be loading, retrying...")
                client.publish(TOPIC_STATUS, "timeout")
                consecutive_errors += 1

            except requests.exceptions.ConnectionError:
                log.error("Cannot reach Ollama at %s", args.ollama)
                client.publish(TOPIC_STATUS, "ollama_offline")
                consecutive_errors += 1

            except RuntimeError as e:
                log.error("ADB error: %s", e)
                client.publish(TOPIC_STATUS, "adb_error")
                consecutive_errors += 1

            except Exception as e:
                log.exception("Unexpected error: %s", e)
                client.publish(TOPIC_STATUS, "error")
                consecutive_errors += 1

            if consecutive_errors >= MAX_ERRORS:
                log.error("Too many consecutive errors (%d). Exiting.", MAX_ERRORS)
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Shutting down...")

    finally:
        client.publish(TOPIC_STATUS, "offline", retain=True)
        client.publish(TOPIC_MODE, "OFF")
        client.loop_stop()
        client.disconnect()
        log.info("Android worker stopped.")


if __name__ == "__main__":
    main()
