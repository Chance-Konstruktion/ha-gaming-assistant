#!/usr/bin/env python3
"""YOLO Object Detection Worker for Gaming Assistant.

An OPTIONAL external service that subscribes to game images via MQTT,
runs YOLO object detection (requires GPU for best performance), and
publishes structured detections back to Home Assistant.

Architecture:
    Capture Agent → MQTT (image) → YOLO Worker → MQTT (detections) → HA

This worker is designed to run on a separate machine with a GPU.
It is NOT part of the HACS integration — it's a standalone service.

Requirements:
    pip install ultralytics paho-mqtt Pillow

Usage:
    python yolo_worker.py --broker 192.168.1.100 --model yolov8n
    python yolo_worker.py --broker homeassistant.local --model yolov8s --confidence 0.4

MQTT Topics:
    Subscribes: gaming_assistant/+/image (raw JPEG bytes)
    Publishes:  gaming_assistant/{client_id}/detections (JSON)

Detection JSON format:
    {
        "client_id": "desktop_01",
        "timestamp": "2025-01-15T14:30:00",
        "model": "yolov8n",
        "detections": [
            {
                "class": "person",
                "confidence": 0.95,
                "bbox": [100, 200, 300, 400],
                "label": "person"
            }
        ],
        "inference_ms": 45,
        "image_size": [640, 480]
    }
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import signal
import sys
import time
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("yolo_worker")

# Lazy imports — only fail if actually used without installing
_YOLO_AVAILABLE = False
_MQTT_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt_client

    _MQTT_AVAILABLE = True
except ImportError:
    pass

try:
    from ultralytics import YOLO

    _YOLO_AVAILABLE = True
except ImportError:
    pass


DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_MODEL = "yolov8n"
DEFAULT_CONFIDENCE = 0.3
DEFAULT_MAX_FPS = 1.0

SUBSCRIBE_TOPIC = "gaming_assistant/+/image"
DETECTION_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/detections"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/register"


class YOLOWorker:
    """MQTT-connected YOLO inference worker."""

    def __init__(
        self,
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
        model_name: str = DEFAULT_MODEL,
        confidence: float = DEFAULT_CONFIDENCE,
        max_fps: float = DEFAULT_MAX_FPS,
        username: str = "",
        password: str = "",
        worker_id: str = "yolo_worker",
    ) -> None:
        self.broker = broker
        self.port = port
        self.model_name = model_name
        self.confidence = confidence
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 1.0
        self.worker_id = worker_id

        self._model: Any = None
        self._client: Any = None
        self._last_process: dict[str, float] = {}
        self._running = False
        self._username = username
        self._password = password

        # Stats
        self._frames_processed = 0
        self._total_detections = 0

    def _load_model(self) -> None:
        """Load the YOLO model."""
        if not _YOLO_AVAILABLE:
            _LOGGER.error(
                "ultralytics is not installed. "
                "Install it with: pip install ultralytics"
            )
            sys.exit(1)

        _LOGGER.info("Loading YOLO model: %s ...", self.model_name)
        self._model = YOLO(self.model_name)
        _LOGGER.info("YOLO model loaded successfully")

    def _setup_mqtt(self) -> None:
        """Set up MQTT client and subscriptions."""
        if not _MQTT_AVAILABLE:
            _LOGGER.error(
                "paho-mqtt is not installed. "
                "Install it with: pip install paho-mqtt"
            )
            sys.exit(1)

        self._client = mqtt_client.Client(
            client_id=self.worker_id,
            protocol=mqtt_client.MQTTv311,
        )

        if self._username:
            self._client.username_pw_set(self._username, self._password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            _LOGGER.info("Connected to MQTT broker at %s:%d", self.broker, self.port)
            client.subscribe(SUBSCRIBE_TOPIC, qos=0)
            _LOGGER.info("Subscribed to: %s", SUBSCRIBE_TOPIC)

            # Register as worker
            register_topic = REGISTER_TOPIC_TEMPLATE.format(
                worker_id=self.worker_id
            )
            register_payload = json.dumps(
                {
                    "name": f"YOLO Worker ({self.model_name})",
                    "type": "yolo_worker",
                    "model": self.model_name,
                    "confidence": self.confidence,
                    "platform": sys.platform,
                }
            )
            client.publish(register_topic, register_payload, retain=True)
        else:
            _LOGGER.error("MQTT connection failed with code %d", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        if rc != 0:
            _LOGGER.warning("Unexpected MQTT disconnect (rc=%d), reconnecting...", rc)

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming image message."""
        try:
            # Extract client_id from topic: gaming_assistant/{client_id}/image
            parts = msg.topic.split("/")
            if len(parts) < 3:
                return
            client_id = parts[1]

            # Rate limiting per client
            now = time.time()
            last = self._last_process.get(client_id, 0)
            if now - last < self.min_interval:
                return
            self._last_process[client_id] = now

            # Run inference
            image_bytes = msg.payload
            detections = self._run_inference(image_bytes)

            # Publish detections
            detection_topic = DETECTION_TOPIC_TEMPLATE.format(
                client_id=client_id
            )
            payload = json.dumps(detections, ensure_ascii=False)
            client.publish(detection_topic, payload, qos=0)

            self._frames_processed += 1
            det_count = len(detections.get("detections", []))
            self._total_detections += det_count

            if det_count > 0:
                _LOGGER.info(
                    "[%s] %d objects detected (%.0fms)",
                    client_id,
                    det_count,
                    detections.get("inference_ms", 0),
                )
            else:
                _LOGGER.debug("[%s] No objects detected", client_id)

        except Exception as err:
            _LOGGER.exception("Error processing image: %s", err)

    def _run_inference(self, image_bytes: bytes) -> dict[str, Any]:
        """Run YOLO inference on image bytes."""
        from PIL import Image

        start = time.time()

        # Decode image
        image = Image.open(io.BytesIO(image_bytes))
        img_size = list(image.size)  # [width, height]

        # Run YOLO
        results = self._model(image, conf=self.confidence, verbose=False)

        detections = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                cls_name = result.names[cls_id]
                conf = float(box.conf[0])
                bbox = [int(x) for x in box.xyxy[0].tolist()]

                detections.append(
                    {
                        "class": cls_name,
                        "confidence": round(conf, 3),
                        "bbox": bbox,
                        "label": cls_name,
                    }
                )

        inference_ms = round((time.time() - start) * 1000, 1)

        return {
            "worker_id": self.worker_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": self.model_name,
            "detections": detections,
            "inference_ms": inference_ms,
            "image_size": img_size,
        }

    def run(self) -> None:
        """Start the YOLO worker (blocking)."""
        self._load_model()
        self._setup_mqtt()

        # Graceful shutdown
        def _signal_handler(sig, frame):
            _LOGGER.info("Shutting down YOLO worker...")
            self._running = False
            if self._client:
                self._client.disconnect()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        self._running = True
        _LOGGER.info(
            "YOLO Worker starting — model=%s, confidence=%.2f, max_fps=%.1f",
            self.model_name,
            self.confidence,
            1.0 / self.min_interval if self.min_interval > 0 else 0,
        )

        try:
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_forever()
        except KeyboardInterrupt:
            pass
        finally:
            _LOGGER.info(
                "YOLO Worker stopped. Processed %d frames, %d total detections.",
                self._frames_processed,
                self._total_detections,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YOLO Object Detection Worker for Gaming Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --broker 192.168.1.100
  %(prog)s --broker homeassistant.local --model yolov8s --confidence 0.4
  %(prog)s --broker 192.168.1.100 --username mqtt_user --password secret
        """,
    )
    parser.add_argument(
        "--broker",
        default=DEFAULT_BROKER,
        help="MQTT broker address (default: localhost)",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="MQTT port (default: 1883)"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="YOLO model name (default: yolov8n). Options: yolov8n, yolov8s, yolov8m",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=DEFAULT_CONFIDENCE,
        help="Minimum detection confidence (default: 0.3)",
    )
    parser.add_argument(
        "--max-fps",
        type=float,
        default=DEFAULT_MAX_FPS,
        help="Maximum frames per second to process (default: 1.0)",
    )
    parser.add_argument("--username", default="", help="MQTT username")
    parser.add_argument("--password", default="", help="MQTT password")
    parser.add_argument(
        "--worker-id", default="yolo_worker", help="Worker ID (default: yolo_worker)"
    )

    args = parser.parse_args()

    worker = YOLOWorker(
        broker=args.broker,
        port=args.port,
        model_name=args.model,
        confidence=args.confidence,
        max_fps=args.max_fps,
        username=args.username,
        password=args.password,
        worker_id=args.worker_id,
    )
    worker.run()


if __name__ == "__main__":
    main()
