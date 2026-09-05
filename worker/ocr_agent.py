#!/usr/bin/env python3
"""HUD OCR Worker for Gaming Assistant.

An OPTIONAL external service that subscribes to game frames via MQTT,
reads numeric HUD fields (health, ammo, score, timer, …) straight off
configured screen regions with OCR, and publishes them back to Home
Assistant as structured numbers.

Why: the integration's game-state engine is far more useful with *measured*
numbers than with values scraped out of the LLM's prose. These OCR'd
fields feed Tier 1 (perception) directly and override any guessed values.

Architecture:
    Capture Agent → MQTT (image) → OCR Worker → MQTT (hud) → Home Assistant

MQTT Topics:
  Subscribes:
    gaming_assistant/+/image            — raw JPEG bytes from capture agents
    gaming_assistant/ocr/command        — runtime commands (JSON)
  Publishes:
    gaming_assistant/{client_id}/hud    — measured HUD numbers (JSON)
    gaming_assistant/{worker_id}/register — worker registration (retained)
    gaming_assistant/{worker_id}/status   — worker status (retained)

Regions are given as fractions of the frame (0..1) so they are resolution
independent::

    --regions "health:0.04,0.90,0.10,0.05;ammo:0.86,0.90,0.10,0.05"

or in a JSON file (``--regions-file regions.json``)::

    {"health": [0.04, 0.90, 0.10, 0.05], "ammo": [0.86, 0.90, 0.10, 0.05]}

Requirements:
  pip install -r worker/requirements-ocr.txt
  Tesseract engine: the default backend needs the system ``tesseract``
  binary (e.g. ``apt install tesseract-ocr``). Use ``--engine easyocr`` for
  a pure-pip alternative (heavier, downloads a model on first run).

Usage:
  python ocr_agent.py --broker 192.168.1.100 \
      --regions "health:0.04,0.90,0.10,0.05;ammo:0.86,0.90,0.10,0.05"
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import signal
import sys
import time
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("ocr_agent")

# Lazy imports — only fail if actually used without installing.
try:
    import paho.mqtt.client as mqtt_client

    _MQTT_AVAILABLE = True
except ImportError:
    _MQTT_AVAILABLE = False


DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_MAX_FPS = 1.0
DEFAULT_ENGINE = "tesseract"

SUBSCRIBE_TOPIC = "gaming_assistant/+/image"
COMMAND_TOPIC = "gaming_assistant/ocr/command"
HUD_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/hud"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/register"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/status"

# A region is (x, y, w, h) as fractions of the frame, in [0, 1].
Region = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Pure helpers (no cv2 / tesseract needed — unit tested)
# ---------------------------------------------------------------------------

def parse_number(text: str) -> int | None:
    """Extract the first integer from raw OCR text, or ``None``.

    Tolerates thousands separators and trailing units::

        "1,500" -> 1500   "80%" -> 80   "HP 42" -> 42   "12/30" -> 12
    """
    if not text:
        return None
    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return None
    digits = re.sub(r"[.,]", "", match.group(0))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def parse_regions(spec: str) -> dict[str, Region]:
    """Parse ``name:x,y,w,h;name2:...`` into a validated region map."""
    regions: dict[str, Region] = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"Region '{chunk}' must look like name:x,y,w,h")
        name, coords = chunk.split(":", 1)
        name = name.strip()
        try:
            parts = [float(p) for p in coords.split(",")]
        except ValueError as err:
            raise ValueError(f"Region '{name}' has non-numeric bounds") from err
        if len(parts) != 4:
            raise ValueError(f"Region '{name}' needs exactly x,y,w,h")
        x, y, w, h = parts
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(f"Region '{name}' x/y must be in [0,1]")
        if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0):
            raise ValueError(f"Region '{name}' w/h must be in (0,1]")
        if x + w > 1.0001 or y + h > 1.0001:
            raise ValueError(f"Region '{name}' extends past the frame edge")
        regions[name] = (x, y, w, h)
    if not regions:
        raise ValueError("No regions parsed")
    return regions


def regions_from_file(path: str) -> dict[str, Region]:
    """Load a region map from a JSON file of ``name: [x, y, w, h]``."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    spec = ";".join(
        f"{name}:{','.join(str(v) for v in box)}" for name, box in raw.items()
    )
    return parse_regions(spec)


def crop_box(img_w: int, img_h: int, region: Region) -> tuple[int, int, int, int]:
    """Convert a fractional region to a clamped ``(left, top, right, bottom)``."""
    x, y, w, h = region
    left = max(0, min(img_w, int(round(x * img_w))))
    top = max(0, min(img_h, int(round(y * img_h))))
    right = max(left + 1, min(img_w, int(round((x + w) * img_w))))
    bottom = max(top + 1, min(img_h, int(round((y + h) * img_h))))
    return left, top, right, bottom


def build_payload(
    worker_id: str, fields: dict[str, int], ocr_ms: float
) -> dict[str, Any]:
    """Build the HUD MQTT payload."""
    return {
        "worker_id": worker_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fields": fields,
        "ocr_ms": round(ocr_ms, 1),
    }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class OCRWorker:
    """MQTT-connected HUD OCR worker."""

    def __init__(
        self,
        regions: dict[str, Region],
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
        max_fps: float = DEFAULT_MAX_FPS,
        username: str = "",
        password: str = "",
        worker_id: str = "ocr_worker",
        engine: str = DEFAULT_ENGINE,
    ) -> None:
        self.regions = regions
        self.broker = broker
        self.port = port
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 1.0
        self.worker_id = worker_id
        self.engine = engine

        self._client: Any = None
        self._reader: Any = None  # lazily-built OCR callable
        self._last_process: dict[str, float] = {}
        self._username = username
        self._password = password

        self._frames_processed = 0
        self._fields_read = 0
        self._avg_ocr_ms = 0.0
        self._start_time = 0.0

    # -- OCR engine ----------------------------------------------------------

    def _ensure_reader(self) -> None:
        """Build the OCR callable for the chosen engine (lazy import)."""
        if self._reader is not None:
            return
        if self.engine == "easyocr":
            self._reader = self._build_easyocr()
        else:
            self._reader = self._build_tesseract()

    @staticmethod
    def _build_tesseract():
        try:
            import pytesseract
        except ImportError:
            _LOGGER.error(
                "pytesseract is not installed and the system 'tesseract' "
                "binary is required. Install both, or use --engine easyocr."
            )
            sys.exit(1)

        config = "--psm 7 -c tessedit_char_whitelist=0123456789,./%"

        def _read(gray) -> str:
            return pytesseract.image_to_string(gray, config=config)

        return _read

    @staticmethod
    def _build_easyocr():
        try:
            import easyocr
        except ImportError:
            _LOGGER.error(
                "easyocr is not installed. Install it with: pip install easyocr"
            )
            sys.exit(1)
        reader = easyocr.Reader(["en"], gpu=False)

        def _read(gray) -> str:
            results = reader.readtext(gray, detail=0, allowlist="0123456789,./%")
            return " ".join(results)

        return _read

    # -- frame processing ----------------------------------------------------

    def read_fields(self, image_bytes: bytes) -> dict[str, int]:
        """OCR every configured region of a frame into ``name -> number``."""
        import cv2
        import numpy as np

        self._ensure_reader()
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return {}
        h, w = frame.shape[:2]

        fields: dict[str, int] = {}
        for name, region in self.regions.items():
            left, top, right, bottom = crop_box(w, h, region)
            crop = frame[top:bottom, left:right]
            if crop.size == 0:
                continue
            gray = self._preprocess(crop, cv2)
            text = self._reader(gray)
            value = parse_number(text)
            if value is not None:
                fields[name] = value
        return fields

    @staticmethod
    def _preprocess(crop, cv2):
        """Upscale + threshold a region crop to help the OCR engine."""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        return thresh

    # -- MQTT ----------------------------------------------------------------

    def _setup_mqtt(self) -> None:
        if not _MQTT_AVAILABLE:
            _LOGGER.error(
                "paho-mqtt is not installed. Install it with: pip install paho-mqtt"
            )
            sys.exit(1)

        self._client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION1,
            client_id=self.worker_id,
            protocol=mqtt_client.MQTTv311,
        )
        if self._username:
            self._client.username_pw_set(self._username, self._password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.will_set(
            status_topic, json.dumps({"status": "offline"}), retain=True
        )

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            _LOGGER.error("MQTT connection failed with code %d", rc)
            return
        _LOGGER.info("Connected to MQTT broker at %s:%d", self.broker, self.port)
        client.subscribe(SUBSCRIBE_TOPIC, qos=0)
        client.subscribe(COMMAND_TOPIC, qos=1)

        register_topic = REGISTER_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        client.publish(
            register_topic,
            json.dumps({
                "name": "HUD OCR Worker",
                "type": "ocr_worker",
                "engine": self.engine,
                "fields": list(self.regions.keys()),
            }),
            retain=True,
        )
        self._publish_status("online")

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic == COMMAND_TOPIC:
            self._handle_command(msg.payload)
            return
        try:
            parts = msg.topic.split("/")
            if len(parts) < 3:
                return
            client_id = parts[1]

            now = time.time()
            if now - self._last_process.get(client_id, 0) < self.min_interval:
                return
            self._last_process[client_id] = now

            start = time.time()
            fields = self.read_fields(msg.payload)
            ocr_ms = (time.time() - start) * 1000.0

            if not fields:
                _LOGGER.debug("[%s] no HUD numbers read", client_id)
                return

            hud_topic = HUD_TOPIC_TEMPLATE.format(client_id=client_id)
            client.publish(
                hud_topic,
                json.dumps(build_payload(self.worker_id, fields, ocr_ms)),
                qos=0,
            )

            self._frames_processed += 1
            self._fields_read += len(fields)
            self._avg_ocr_ms = (
                self._avg_ocr_ms * 0.9 + ocr_ms * 0.1
                if self._avg_ocr_ms > 0 else ocr_ms
            )
            _LOGGER.info("[%s] HUD %s (%.0fms)", client_id, fields, ocr_ms)
        except Exception as err:  # noqa: BLE001 - worker must keep running
            _LOGGER.exception("Error processing frame: %s", err)

    def _handle_command(self, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.warning("Invalid command payload")
            return
        cmd = data.get("command", "")
        if cmd == "set_max_fps":
            fps = data.get("value", 1.0)
            if fps > 0:
                self.min_interval = 1.0 / fps
                _LOGGER.info("Max FPS updated to %.1f", fps)
        elif cmd == "status":
            self._publish_status("online")
        else:
            _LOGGER.warning("Unknown command: %s", cmd)

    def _publish_status(self, status: str) -> None:
        if not self._client:
            return
        uptime = time.time() - self._start_time if self._start_time else 0
        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.publish(
            status_topic,
            json.dumps({
                "status": status,
                "engine": self.engine,
                "fields": list(self.regions.keys()),
                "frames_processed": self._frames_processed,
                "fields_read": self._fields_read,
                "avg_ocr_ms": round(self._avg_ocr_ms, 1),
                "uptime_s": round(uptime),
            }),
            retain=True,
        )

    def run(self) -> None:
        self._setup_mqtt()
        self._start_time = time.time()

        def _signal_handler(sig, frame):
            _LOGGER.info("Shutting down OCR worker...")
            self._publish_status("offline")
            if self._client:
                self._client.disconnect()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        _LOGGER.info(
            "OCR Worker starting — engine=%s, fields=%s, max_fps=%.1f",
            self.engine, list(self.regions.keys()),
            1.0 / self.min_interval if self.min_interval > 0 else 0,
        )
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_forever()
        except KeyboardInterrupt:
            pass
        finally:
            _LOGGER.info(
                "OCR Worker stopped. Processed %d frames, %d fields read.",
                self._frames_processed, self._fields_read,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HUD OCR Worker for Gaming Assistant",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username")
    parser.add_argument("--password", default="", help="MQTT password")
    parser.add_argument(
        "--worker-id", default="ocr_worker", help="Worker ID"
    )
    parser.add_argument(
        "--engine", default=DEFAULT_ENGINE, choices=["tesseract", "easyocr"],
        help="OCR engine (default: tesseract)",
    )
    parser.add_argument(
        "--max-fps", type=float, default=DEFAULT_MAX_FPS,
        help="Maximum frames per second to OCR (default: 1.0)",
    )
    parser.add_argument(
        "--regions", default="",
        help="Regions as name:x,y,w,h;... (fractions of the frame, 0..1)",
    )
    parser.add_argument(
        "--regions-file", default="",
        help="JSON file mapping name -> [x, y, w, h]",
    )
    args = parser.parse_args()

    try:
        if args.regions_file:
            regions = regions_from_file(args.regions_file)
        elif args.regions:
            regions = parse_regions(args.regions)
        else:
            parser.error("Provide --regions or --regions-file")
    except (ValueError, OSError, json.JSONDecodeError) as err:
        parser.error(f"Invalid regions: {err}")

    worker = OCRWorker(
        regions=regions,
        broker=args.broker,
        port=args.port,
        max_fps=args.max_fps,
        username=args.username,
        password=args.password,
        worker_id=args.worker_id,
        engine=args.engine,
    )
    worker.run()


if __name__ == "__main__":
    main()
