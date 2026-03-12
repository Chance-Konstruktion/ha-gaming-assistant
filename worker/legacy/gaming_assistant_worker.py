"""
Gaming Assistant Worker
=======================
Runs on the Gaming PC. Captures screenshots, analyzes them with a
local Vision LLM (Ollama), and publishes tips to Home Assistant via MQTT.

Requirements:
    pip install mss pillow requests paho-mqtt

Optional (game detection on Windows):
    pip install pywin32

Usage:
    python gaming_assistant_worker.py --broker 192.168.1.10 --model qwen2.5vl
"""

import argparse
import base64
import collections
import hashlib
import logging
import time
from io import BytesIO

import paho.mqtt.client as mqtt
import requests
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
log = logging.getLogger("gaming_assistant")

# ---------------------------------------------------------------------------
# MQTT Topics
# ---------------------------------------------------------------------------
TOPIC_TIP    = "gaming_assistant/tip"
TOPIC_MODE   = "gaming_assistant/gaming_mode"
TOPIC_STATUS = "gaming_assistant/status"
TOPIC_CMD    = "gaming_assistant/command"

# ---------------------------------------------------------------------------
# Known games for auto-detection (extend as needed)
# ---------------------------------------------------------------------------
KNOWN_GAMES = [
    "Wolfenstein", "Doom", "Cyberpunk", "Elden Ring",
    "Dark Souls", "Minecraft", "Counter-Strike", "Valorant",
    "Overwatch", "Baldur's Gate", "Starfield", "The Witcher",
]


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------
def capture_screen(monitor_index: int = 1, resize: tuple = (960, 540)) -> tuple[str, str]:
    """Capture a screenshot and return (base64_string, frame_hash)."""
    with mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 1
        shot = sct.grab(monitors[monitor_index])
        img = Image.frombytes("RGB", shot.size, shot.rgb)

    img = img.resize(resize, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    raw = buffer.getvalue()

    img_b64  = base64.b64encode(raw).decode("utf-8")
    img_hash = hashlib.md5(raw).hexdigest()

    return img_b64, img_hash


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------
MAX_HISTORY = 10  # number of previous tips to remember


class TipHistory:
    """Keeps a rolling window of previous tips so the LLM can build on them."""

    def __init__(self, maxlen: int = MAX_HISTORY) -> None:
        self._tips: collections.deque[str] = collections.deque(maxlen=maxlen)

    def add(self, tip: str) -> None:
        self._tips.append(tip)

    def clear(self) -> None:
        self._tips.clear()

    def format_for_prompt(self) -> str:
        """Return previous tips as a numbered list for the LLM prompt."""
        if not self._tips:
            return ""
        lines = [f"  {i}. {t}" for i, t in enumerate(list(self._tips), 1)]
        return (
            "\n\nHere are your previous tips from this session (oldest first):\n"
            + "\n".join(lines)
            + "\n\nDo NOT repeat any of these tips. Build on them and give a NEW "
            "insight the player hasn't heard yet."
        )


# ---------------------------------------------------------------------------
# Ollama analysis
# ---------------------------------------------------------------------------
def analyze_screenshot(
    img_b64: str, host: str, model: str,
    game_hint: str = "", history: TipHistory | None = None,
) -> str:
    """Send screenshot to Ollama and return the tip."""
    game_context = f" The player is playing {game_hint}." if game_hint else ""
    history_context = history.format_for_prompt() if history else ""
    prompt = (
        f"You are a helpful gaming coach.{game_context} "
        "Look at this game screenshot and give exactly ONE short, "
        "specific, actionable gameplay tip in one sentence. "
        f"No introduction, no emojis, just the tip.{history_context}"
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
# Game detection (Windows only, graceful fallback)
# ---------------------------------------------------------------------------
def detect_active_game() -> str:
    """Return the name of the active game window, or empty string."""
    try:
        import win32gui
        window_title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
        for game in KNOWN_GAMES:
            if game.lower() in window_title.lower():
                return game
    except ImportError:
        pass  # pywin32 not available (Linux/macOS)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def build_mqtt_client(broker: str, port: int, username: str, password: str):
    """Create and connect the MQTT client."""
    client = mqtt.Client(client_id="gaming_assistant_worker", clean_session=True)

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
    parser = argparse.ArgumentParser(description="Gaming Assistant Worker")
    parser.add_argument("--broker",   default="homeassistant.local", help="MQTT broker IP/hostname")
    parser.add_argument("--port",     type=int, default=1883,         help="MQTT port")
    parser.add_argument("--user",     default="",                     help="MQTT username (optional)")
    parser.add_argument("--password", default="",                     help="MQTT password (optional)")
    parser.add_argument("--ollama",   default="http://localhost:11434",help="Ollama base URL")
    parser.add_argument("--model",    default="qwen2.5vl",            help="Ollama vision model")
    parser.add_argument("--interval", type=int, default=10,           help="Seconds between analyses")
    parser.add_argument("--monitor",  type=int, default=1,            help="Monitor index (1=primary)")
    parser.add_argument("--history",  type=int, default=MAX_HISTORY,  help="Number of previous tips to remember (0 to disable)")
    args = parser.parse_args()

    log.info("=== Gaming Assistant Worker ===")
    log.info("Broker  : %s:%d", args.broker, args.port)
    log.info("Ollama  : %s  model=%s", args.ollama, args.model)
    log.info("Interval: %ds", args.interval)

    client, running = build_mqtt_client(args.broker, args.port, args.user, args.password)
    time.sleep(1)  # Let MQTT connect

    tip_history = TipHistory(maxlen=args.history) if args.history > 0 else None
    if tip_history:
        log.info("Tip history enabled (remembering last %d tips)", args.history)

    last_hash = ""
    last_game = ""
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
                # 1. Detect active game
                game = detect_active_game()
                if game:
                    log.info("Game detected: %s", game)
                    client.publish(TOPIC_MODE, "ON")
                    # Clear history when switching to a different game
                    if game != last_game and tip_history:
                        log.info("Game changed (%s -> %s), clearing tip history",
                                 last_game or "none", game)
                        tip_history.clear()
                    last_game = game
                else:
                    client.publish(TOPIC_MODE, "OFF")

                # 2. Capture screenshot
                img_b64, img_hash = capture_screen(args.monitor)

                # 3. Frame change detection – skip if screen hasn't changed
                if img_hash == last_hash:
                    log.debug("Frame unchanged, skipping analysis")
                    time.sleep(args.interval)
                    continue
                last_hash = img_hash

                # 4. Analyze with Vision LLM (with conversation history)
                client.publish(TOPIC_STATUS, "analyzing")
                tip = analyze_screenshot(
                    img_b64, args.ollama, args.model, game, tip_history,
                )
                log.info("TIP: %s", tip)

                # 5. Remember tip for future context
                if tip_history:
                    tip_history.add(tip)

                # 6. Publish tip (retain=True so HA keeps state after restart)
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
        log.info("Worker stopped.")


if __name__ == "__main__":
    main()
