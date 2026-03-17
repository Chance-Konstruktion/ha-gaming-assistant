#!/usr/bin/env python3
"""YOLO Object Detection Worker for Gaming Assistant.

An OPTIONAL external service that subscribes to game images via MQTT,
runs YOLO object detection, and publishes structured detections back
to Home Assistant.

Supports multiple inference backends:
  - ultralytics (GPU/CPU) — best for desktop/server with NVIDIA GPU
  - NCNN (ARM-optimized) — best for Raspberry Pi 3/4/5 (CPU)
  - Hailo (NPU) — best for Raspberry Pi 5 + AI Kit (13 TOPS)
  - TFLite (ARM-optimized) — lightweight alternative for RPi

Architecture:
    Capture Agent → MQTT (image) → YOLO Worker → MQTT (detections) → HA

Requirements (pick ONE):
  Desktop/GPU:  pip install ultralytics paho-mqtt Pillow
  RPi (NCNN):   pip install ultralytics paho-mqtt Pillow ncnn
  RPi (Hailo):  pip install ultralytics paho-mqtt Pillow hailo-platform
  RPi (TFLite): pip install ultralytics paho-mqtt Pillow tflite-runtime

Usage:
  Desktop:  python yolo_worker.py --broker 192.168.1.100 --model yolov8n
  RPi CPU:  python yolo_worker.py --broker 192.168.1.100 --model yolov8n --backend ncnn
  RPi NPU:  python yolo_worker.py --broker 192.168.1.100 --model yolov8n --backend hailo
  RPi Lite: python yolo_worker.py --broker 192.168.1.100 --model yolov8n --backend tflite

MQTT Topics:
  Subscribes:
    gaming_assistant/+/image          — raw JPEG bytes from capture agents
    gaming_assistant/yolo/command      — runtime commands (JSON)
  Publishes:
    gaming_assistant/{client_id}/detections — structured detection results
    gaming_assistant/{worker_id}/register   — worker registration (retained)
    gaming_assistant/{worker_id}/status     — worker status (retained)

Command format (gaming_assistant/yolo/command):
    {"command": "set_confidence", "value": 0.5}
    {"command": "set_model", "model": "yolov8s"}
    {"command": "set_max_fps", "value": 2.0}
    {"command": "status"}    — triggers a status publish
    {"command": "restart"}   — reloads the model
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import platform
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
DEFAULT_BACKEND = "auto"
DEFAULT_IMGSZ = 640

# MQTT topics
SUBSCRIBE_TOPIC = "gaming_assistant/+/image"
COMMAND_TOPIC = "gaming_assistant/yolo/command"
DETECTION_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/detections"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/register"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/status"

# RPi detection
_IS_ARM = platform.machine().startswith(("arm", "aarch64"))
_IS_RPI = _IS_ARM and os.path.exists("/proc/device-tree/model")

# Backend options and their export formats for ultralytics
BACKEND_EXPORT_FORMATS = {
    "auto": None,       # ultralytics picks the best
    "pytorch": None,    # native, no export needed
    "ncnn": "ncnn",     # ARM NCNN — optimized for RPi CPU
    "tflite": "tflite", # TensorFlow Lite — lightweight RPi
    "hailo": None,      # Hailo NPU — uses HailoRT API
    "onnx": "onnx",     # ONNX Runtime — cross-platform
}

# Recommended settings per platform
PLATFORM_PRESETS = {
    "rpi3": {"model": "yolov8n", "imgsz": 320, "backend": "ncnn", "max_fps": 0.2},
    "rpi4": {"model": "yolov8n", "imgsz": 416, "backend": "ncnn", "max_fps": 0.5},
    "rpi5": {"model": "yolov8n", "imgsz": 480, "backend": "ncnn", "max_fps": 1.0},
    "rpi5_hailo": {"model": "yolov8n", "imgsz": 640, "backend": "hailo", "max_fps": 5.0},
    "desktop_cpu": {"model": "yolov8n", "imgsz": 640, "backend": "pytorch", "max_fps": 2.0},
    "desktop_gpu": {"model": "yolov8s", "imgsz": 640, "backend": "pytorch", "max_fps": 10.0},
}


def _detect_platform() -> str:
    """Auto-detect the best platform preset."""
    if not _IS_ARM:
        # Check for CUDA GPU
        try:
            import torch
            if torch.cuda.is_available():
                return "desktop_gpu"
        except ImportError:
            pass
        return "desktop_cpu"

    # ARM — check for RPi variant
    if not _IS_RPI:
        return "rpi4"  # generic ARM fallback

    try:
        with open("/proc/device-tree/model", "r") as f:
            model_str = f.read().lower()
    except OSError:
        return "rpi4"

    # Check for Hailo NPU
    has_hailo = os.path.exists("/dev/hailo0")

    if "raspberry pi 5" in model_str:
        return "rpi5_hailo" if has_hailo else "rpi5"
    elif "raspberry pi 4" in model_str:
        return "rpi4"
    elif "raspberry pi 3" in model_str:
        return "rpi3"

    return "rpi4"


class YOLOWorker:
    """MQTT-connected YOLO inference worker with multi-backend support."""

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
        backend: str = DEFAULT_BACKEND,
        imgsz: int = DEFAULT_IMGSZ,
    ) -> None:
        self.broker = broker
        self.port = port
        self.model_name = model_name
        self.confidence = confidence
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 1.0
        self.worker_id = worker_id
        self.backend = backend
        self.imgsz = imgsz

        self._model: Any = None
        self._client: Any = None
        self._last_process: dict[str, float] = {}
        self._running = False
        self._username = username
        self._password = password
        self._platform = ""

        # Stats
        self._frames_processed = 0
        self._total_detections = 0
        self._avg_inference_ms = 0.0
        self._start_time = 0.0

    def _apply_platform_defaults(self) -> None:
        """Apply platform-specific defaults if backend is 'auto'."""
        if self.backend != "auto":
            return

        self._platform = _detect_platform()
        preset = PLATFORM_PRESETS.get(self._platform, {})

        if preset:
            _LOGGER.info(
                "Auto-detected platform: %s → backend=%s, imgsz=%d, max_fps=%.1f",
                self._platform,
                preset.get("backend", "pytorch"),
                preset.get("imgsz", 640),
                preset.get("max_fps", 1.0),
            )
            self.backend = preset.get("backend", "pytorch")
            self.imgsz = preset.get("imgsz", self.imgsz)
            # Only override max_fps if user didn't explicitly set it
            suggested_fps = preset.get("max_fps", 1.0)
            if self.min_interval == 1.0:  # default
                self.min_interval = 1.0 / suggested_fps if suggested_fps > 0 else 1.0

    def _load_model(self) -> None:
        """Load the YOLO model with the appropriate backend."""
        if not _YOLO_AVAILABLE:
            _LOGGER.error(
                "ultralytics is not installed. "
                "Install it with: pip install ultralytics"
            )
            sys.exit(1)

        self._apply_platform_defaults()

        _LOGGER.info(
            "Loading YOLO model: %s (backend=%s, imgsz=%d) ...",
            self.model_name,
            self.backend,
            self.imgsz,
        )

        # Load base model
        model = YOLO(self.model_name)

        # Export to optimized format if needed
        export_fmt = BACKEND_EXPORT_FORMATS.get(self.backend)
        if export_fmt:
            _LOGGER.info("Exporting model to %s format (first run may take a while)...", export_fmt)
            exported_path = model.export(format=export_fmt, imgsz=self.imgsz)
            self._model = YOLO(exported_path)
            _LOGGER.info("Model exported and loaded from: %s", exported_path)
        elif self.backend == "hailo":
            self._load_hailo_model()
        else:
            self._model = model

        _LOGGER.info("YOLO model loaded successfully (backend=%s)", self.backend)

    def _load_hailo_model(self) -> None:
        """Load model for Hailo NPU (RPi 5 AI Kit)."""
        # Hailo uses pre-compiled HEF files
        hef_path = self.model_name
        if not hef_path.endswith(".hef"):
            # Try to find a pre-compiled HEF in common locations
            search_paths = [
                f"/usr/share/hailo-models/{self.model_name}.hef",
                f"/opt/hailo/models/{self.model_name}.hef",
                f"./{self.model_name}.hef",
            ]
            for path in search_paths:
                if os.path.exists(path):
                    hef_path = path
                    break
            else:
                _LOGGER.warning(
                    "No pre-compiled HEF found for %s. "
                    "Falling back to NCNN backend. "
                    "To use Hailo, export your model: "
                    "hailo_sdk model_convert %s.onnx --hw-arch hailo8l",
                    self.model_name,
                    self.model_name,
                )
                self.backend = "ncnn"
                exported_path = YOLO(self.model_name).export(
                    format="ncnn", imgsz=self.imgsz
                )
                self._model = YOLO(exported_path)
                return

        self._model = YOLO(hef_path)
        _LOGGER.info("Hailo model loaded from: %s", hef_path)

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

        # Set Last Will for offline status
        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.will_set(
            status_topic,
            json.dumps({"status": "offline"}),
            retain=True,
        )

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            _LOGGER.info("Connected to MQTT broker at %s:%d", self.broker, self.port)
            client.subscribe(SUBSCRIBE_TOPIC, qos=0)
            client.subscribe(COMMAND_TOPIC, qos=1)
            _LOGGER.info("Subscribed to: %s, %s", SUBSCRIBE_TOPIC, COMMAND_TOPIC)

            # Register as worker
            register_topic = REGISTER_TOPIC_TEMPLATE.format(
                worker_id=self.worker_id
            )
            register_payload = json.dumps(
                {
                    "name": f"YOLO Worker ({self.model_name})",
                    "type": "yolo_worker",
                    "model": self.model_name,
                    "backend": self.backend,
                    "confidence": self.confidence,
                    "imgsz": self.imgsz,
                    "platform": self._platform or _detect_platform(),
                    "arch": platform.machine(),
                }
            )
            client.publish(register_topic, register_payload, retain=True)

            # Publish online status
            self._publish_status("online")
        else:
            _LOGGER.error("MQTT connection failed with code %d", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        if rc != 0:
            _LOGGER.warning("Unexpected MQTT disconnect (rc=%d), reconnecting...", rc)

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming messages (images + commands)."""
        # Handle commands
        if msg.topic == COMMAND_TOPIC:
            self._handle_command(msg.payload)
            return

        # Handle images
        try:
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

            # Rolling average inference time
            ms = detections.get("inference_ms", 0)
            self._avg_inference_ms = (
                self._avg_inference_ms * 0.9 + ms * 0.1
                if self._avg_inference_ms > 0
                else ms
            )

            if det_count > 0:
                _LOGGER.info(
                    "[%s] %d objects detected (%.0fms, avg %.0fms)",
                    client_id,
                    det_count,
                    ms,
                    self._avg_inference_ms,
                )
            else:
                _LOGGER.debug("[%s] No objects detected", client_id)

        except Exception as err:
            _LOGGER.exception("Error processing image: %s", err)

    def _handle_command(self, payload: bytes) -> None:
        """Handle runtime commands from MQTT."""
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.warning("Invalid command payload")
            return

        cmd = data.get("command", "")
        _LOGGER.info("Received command: %s", cmd)

        if cmd == "set_confidence":
            new_conf = data.get("value", self.confidence)
            if 0.0 < new_conf < 1.0:
                self.confidence = new_conf
                _LOGGER.info("Confidence updated to %.2f", self.confidence)

        elif cmd == "set_max_fps":
            new_fps = data.get("value", 1.0)
            if new_fps > 0:
                self.min_interval = 1.0 / new_fps
                _LOGGER.info("Max FPS updated to %.1f", new_fps)

        elif cmd == "status":
            self._publish_status("online")

        elif cmd == "restart":
            _LOGGER.info("Restarting model...")
            model_name = data.get("model", self.model_name)
            self.model_name = model_name
            self._load_model()
            _LOGGER.info("Model restarted: %s", self.model_name)

        else:
            _LOGGER.warning("Unknown command: %s", cmd)

    def _publish_status(self, status: str) -> None:
        """Publish worker status to MQTT."""
        if not self._client:
            return

        uptime = time.time() - self._start_time if self._start_time else 0
        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.publish(
            status_topic,
            json.dumps(
                {
                    "status": status,
                    "model": self.model_name,
                    "backend": self.backend,
                    "platform": self._platform or _detect_platform(),
                    "confidence": self.confidence,
                    "imgsz": self.imgsz,
                    "frames_processed": self._frames_processed,
                    "total_detections": self._total_detections,
                    "avg_inference_ms": round(self._avg_inference_ms, 1),
                    "uptime_s": round(uptime),
                }
            ),
            retain=True,
        )

    def _run_inference(self, image_bytes: bytes) -> dict[str, Any]:
        """Run YOLO inference on image bytes."""
        from PIL import Image

        start = time.time()

        # Decode image
        image = Image.open(io.BytesIO(image_bytes))
        img_size = list(image.size)  # [width, height]

        # Run YOLO with configured imgsz
        results = self._model(
            image,
            conf=self.confidence,
            imgsz=self.imgsz,
            verbose=False,
        )

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
            "backend": self.backend,
            "detections": detections,
            "inference_ms": inference_ms,
            "image_size": img_size,
        }

    def run(self) -> None:
        """Start the YOLO worker (blocking)."""
        self._load_model()
        self._setup_mqtt()
        self._start_time = time.time()

        # Graceful shutdown
        def _signal_handler(sig, frame):
            _LOGGER.info("Shutting down YOLO worker...")
            self._running = False
            self._publish_status("offline")
            if self._client:
                self._client.disconnect()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        self._running = True
        max_fps = 1.0 / self.min_interval if self.min_interval > 0 else 0

        _LOGGER.info(
            "YOLO Worker starting — model=%s, backend=%s, imgsz=%d, "
            "confidence=%.2f, max_fps=%.1f",
            self.model_name,
            self.backend,
            self.imgsz,
            self.confidence,
            max_fps,
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
    # Build platform list for help text
    platform_list = ", ".join(PLATFORM_PRESETS.keys())

    parser = argparse.ArgumentParser(
        description="YOLO Object Detection Worker for Gaming Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Platform presets: {platform_list}

Examples:
  Desktop (GPU):
    %(prog)s --broker 192.168.1.100
    %(prog)s --broker 192.168.1.100 --model yolov8s --backend pytorch

  Raspberry Pi 5 + AI Kit (Hailo NPU, ~30 FPS):
    %(prog)s --broker 192.168.1.100 --backend hailo

  Raspberry Pi 5 (CPU via NCNN, ~3-5 FPS):
    %(prog)s --broker 192.168.1.100 --backend ncnn

  Raspberry Pi 4 (CPU via NCNN, ~1-2 FPS):
    %(prog)s --broker 192.168.1.100 --backend ncnn --imgsz 416

  Raspberry Pi 3 (minimal, ~0.2 FPS):
    %(prog)s --broker 192.168.1.100 --backend ncnn --imgsz 320 --max-fps 0.2

  Auto-detect (recommended):
    %(prog)s --broker 192.168.1.100 --backend auto
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
        help="YOLO model name (default: yolov8n). Options: yolov8n, yolov8s, yolov8m, yolov8n.hef",
    )
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND,
        choices=list(BACKEND_EXPORT_FORMATS.keys()),
        help="Inference backend (default: auto). "
        "'auto' detects your hardware and picks the best option.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=DEFAULT_IMGSZ,
        help="Input image size for inference (default: 640). "
        "Lower = faster but less accurate. RPi: try 320-480.",
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
    parser.add_argument(
        "--platform-info",
        action="store_true",
        help="Print detected platform info and exit",
    )

    args = parser.parse_args()

    if args.platform_info:
        plat = _detect_platform()
        preset = PLATFORM_PRESETS.get(plat, {})
        print(f"Detected platform: {plat}")
        print(f"Architecture: {platform.machine()}")
        print(f"Is ARM: {_IS_ARM}")
        print(f"Is RPi: {_IS_RPI}")
        if _IS_RPI:
            try:
                with open("/proc/device-tree/model", "r") as f:
                    print(f"RPi Model: {f.read().strip()}")
            except OSError:
                pass
            print(f"Hailo NPU: {os.path.exists('/dev/hailo0')}")
        print(f"Recommended preset: {json.dumps(preset, indent=2)}")
        return

    worker = YOLOWorker(
        broker=args.broker,
        port=args.port,
        model_name=args.model,
        confidence=args.confidence,
        max_fps=args.max_fps,
        username=args.username,
        password=args.password,
        worker_id=args.worker_id,
        backend=args.backend,
        imgsz=args.imgsz,
    )
    worker.run()


if __name__ == "__main__":
    main()
