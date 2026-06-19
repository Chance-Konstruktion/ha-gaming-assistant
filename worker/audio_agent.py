#!/usr/bin/env python3
"""Game-audio Worker for Gaming Assistant.

An OPTIONAL external service that runs **on the gaming PC** (where the sound
is actually produced), listens to the game's audio, derives a few cheap
high-level signals — loudness, intensity class, and sudden onsets like
gunshots / explosions / stingers — and publishes them to Home Assistant.

Why client-side: the whole project is designed to run Home Assistant on
modest hardware (a Raspberry Pi / small NUC), without a high-end server.
Streaming raw audio to HA and analysing it there would be wasteful and
heavy. So the audio is captured and analysed locally on the PC, and only a
tiny JSON of *measured signals* travels over MQTT. The analysis itself is
deliberately light: plain RMS / peak / onset detection (no model, no GPU),
so it adds negligible load to the gaming machine.

Architecture:
    Gaming PC audio → audio_agent.py (local DSP) → MQTT (audio) → Home Assistant

These feed Tier 1 (perception) just like the YOLO and OCR workers: HA only
*fuses* the signals into the game state, it does not do the heavy lifting.

MQTT Topics:
  Publishes:
    gaming_assistant/{client_id}/audio   — measured audio signals (JSON)
    gaming_assistant/{worker_id}/register — worker registration (retained)
    gaming_assistant/{worker_id}/status   — worker status (retained)
  Subscribes:
    gaming_assistant/audio/command       — runtime commands (JSON)

To keep HA quiet, the worker publishes only when something noteworthy
happens — a sudden onset, or an intensity-class change — plus a slow
heartbeat so a steady scene still refreshes.

Requirements:
  pip install -r worker/requirements-audio.txt

Capturing *system* audio (the game's output, not a microphone) depends on
the OS:
  * Windows: pick a WASAPI loopback / "Stereo Mix" device, or a virtual
    cable. Run with --list-devices to see what's available.
  * Linux (PulseAudio/PipeWire): select a ``.monitor`` source.
  * macOS: install a loopback driver (e.g. BlackHole) and select it.

Usage:
  python audio_agent.py --broker 192.168.1.100 --client-id gaming-pc
  python audio_agent.py --list-devices
  python audio_agent.py --broker 192.168.1.100 --device 7
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import sys
import time
from dataclasses import dataclass
from typing import Any, Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("audio_agent")

# Lazy imports — only fail if actually used without installing.
try:
    import paho.mqtt.client as mqtt_client

    _MQTT_AVAILABLE = True
except ImportError:
    _MQTT_AVAILABLE = False


DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_CLIENT_ID = "gaming-pc"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_BLOCK = 2048  # samples per analysis block (~0.13s at 16 kHz)
DEFAULT_HEARTBEAT = 30.0  # seconds; refresh even when nothing changes

# Intensity thresholds on RMS level (float audio in [-1, 1]).
QUIET_BELOW = 0.02
INTENSE_ABOVE = 0.2
# Onset: the block's level jumps well above the rolling baseline.
ONSET_FACTOR = 3.0
ONSET_FLOOR = 0.05  # absolute floor so silence->faint noise isn't an "onset"
BASELINE_ALPHA = 0.1  # EMA weight for the rolling-quiet baseline

COMMAND_TOPIC = "gaming_assistant/audio/command"
AUDIO_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/audio"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/register"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/status"


# ---------------------------------------------------------------------------
# Pure DSP helpers (no numpy / sounddevice needed — unit tested)
# ---------------------------------------------------------------------------

def rms(samples: Sequence[float]) -> float:
    """Root-mean-square loudness of a block of samples in [-1, 1]."""
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def peak(samples: Sequence[float]) -> float:
    """Peak absolute amplitude of a block of samples."""
    if not samples:
        return 0.0
    return max(abs(s) for s in samples)


def to_db(level: float, floor_db: float = -80.0) -> float:
    """Convert a linear 0..1 level to dBFS, clamped at ``floor_db``."""
    if level <= 0.0:
        return floor_db
    return max(floor_db, 20.0 * math.log10(level))


def classify_intensity(
    level: float, quiet_below: float = QUIET_BELOW,
    intense_above: float = INTENSE_ABOVE,
) -> str:
    """Bucket a loudness level into quiet / moderate / intense."""
    if level < quiet_below:
        return "quiet"
    if level >= intense_above:
        return "intense"
    return "moderate"


@dataclass(frozen=True)
class AudioReading:
    """The signals derived from a single analysis block."""

    rms: float
    peak: float
    db: float
    intensity: str
    onset: bool
    intensity_changed: bool


def event_for(reading: AudioReading) -> str | None:
    """Pick the noteworthy event for a reading, or ``None`` if routine."""
    if reading.onset:
        return "onset"
    if reading.intensity_changed:
        return "intensity_change"
    return None


def build_payload(
    worker_id: str, reading: AudioReading, event: str | None
) -> dict[str, Any]:
    """Build the audio MQTT payload from a reading."""
    payload: dict[str, Any] = {
        "worker_id": worker_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "signals": {
            "audio_db": round(reading.db, 1),
            "audio_level": round(reading.rms, 4),
            "audio_peak": round(reading.peak, 4),
            "audio_intensity": reading.intensity,
        },
    }
    if event:
        payload["event"] = event
        payload["signals"]["audio_event"] = event
    return payload


class AudioAnalyzer:
    """Stateful, cheap analyser: tracks a baseline and flags onsets.

    Pure Python and tiny — it only keeps a running EMA of the recent quiet
    level and the previous intensity class, so it can flag a *sudden* jump
    (onset) and an intensity-class change. No model, no GPU.
    """

    def __init__(
        self,
        quiet_below: float = QUIET_BELOW,
        intense_above: float = INTENSE_ABOVE,
        onset_factor: float = ONSET_FACTOR,
        onset_floor: float = ONSET_FLOOR,
        baseline_alpha: float = BASELINE_ALPHA,
    ) -> None:
        self.quiet_below = quiet_below
        self.intense_above = intense_above
        self.onset_factor = onset_factor
        self.onset_floor = onset_floor
        self.baseline_alpha = baseline_alpha
        self._baseline = 0.0
        self._prev_intensity: str | None = None

    def process(self, samples: Sequence[float]) -> AudioReading:
        """Analyse one block and update internal state."""
        level = rms(samples)
        pk = peak(samples)

        # Onset: a clear jump above both the rolling baseline and a floor.
        threshold = max(self.onset_floor, self._baseline * self.onset_factor)
        onset = level >= threshold and level >= self.onset_floor

        # Update the rolling-quiet baseline (EMA) *after* the onset test.
        if self._baseline <= 0.0:
            self._baseline = level
        else:
            self._baseline = (
                (1.0 - self.baseline_alpha) * self._baseline
                + self.baseline_alpha * level
            )

        intensity = classify_intensity(
            level, self.quiet_below, self.intense_above
        )
        changed = (
            self._prev_intensity is not None
            and intensity != self._prev_intensity
        )
        self._prev_intensity = intensity

        return AudioReading(
            rms=level, peak=pk, db=to_db(level),
            intensity=intensity, onset=onset, intensity_changed=changed,
        )

    def reset(self) -> None:
        self._baseline = 0.0
        self._prev_intensity = None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class AudioWorker:
    """MQTT-connected game-audio worker (runs on the gaming PC)."""

    def __init__(
        self,
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
        client_id: str = DEFAULT_CLIENT_ID,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        block: int = DEFAULT_BLOCK,
        device: Any = None,
        heartbeat: float = DEFAULT_HEARTBEAT,
        username: str = "",
        password: str = "",
        worker_id: str = "audio_worker",
    ) -> None:
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.sample_rate = sample_rate
        self.block = block
        self.device = device
        self.heartbeat = heartbeat
        self.worker_id = worker_id
        self._username = username
        self._password = password

        self._client: Any = None
        self._analyzer = AudioAnalyzer()
        self._running = False
        self._last_publish = 0.0

        self._blocks_processed = 0
        self._events_published = 0
        self._start_time = 0.0

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
        client.subscribe(COMMAND_TOPIC, qos=1)

        register_topic = REGISTER_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        client.publish(
            register_topic,
            json.dumps({
                "name": "Game Audio Worker",
                "type": "audio_worker",
                "client_id": self.client_id,
                "sample_rate": self.sample_rate,
            }),
            retain=True,
        )
        self._publish_status("online")

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic == COMMAND_TOPIC:
            self._handle_command(msg.payload)

    def _handle_command(self, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.warning("Invalid command payload")
            return
        cmd = data.get("command", "")
        if cmd == "status":
            self._publish_status("online")
        elif cmd == "reset":
            self._analyzer.reset()
            _LOGGER.info("Analyzer baseline reset")
        else:
            _LOGGER.warning("Unknown command: %s", cmd)

    def _publish_reading(self, reading: AudioReading, event: str | None) -> None:
        if not self._client:
            return
        audio_topic = AUDIO_TOPIC_TEMPLATE.format(client_id=self.client_id)
        self._client.publish(
            audio_topic,
            json.dumps(build_payload(self.worker_id, reading, event)),
            qos=0,
        )
        self._events_published += 1
        self._last_publish = time.time()

    def _publish_status(self, status: str) -> None:
        if not self._client:
            return
        uptime = time.time() - self._start_time if self._start_time else 0
        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.publish(
            status_topic,
            json.dumps({
                "status": status,
                "type": "audio_worker",
                "client_id": self.client_id,
                "blocks_processed": self._blocks_processed,
                "events_published": self._events_published,
                "uptime_s": round(uptime),
            }),
            retain=True,
        )

    # -- audio capture -------------------------------------------------------

    def _handle_block(self, samples: Sequence[float]) -> None:
        """Analyse one captured block and publish if noteworthy."""
        reading = self._analyzer.process(samples)
        self._blocks_processed += 1
        event = event_for(reading)
        due = (time.time() - self._last_publish) >= self.heartbeat
        if event or due:
            self._publish_reading(reading, event)
            if event:
                _LOGGER.info(
                    "[%s] %s — %s (%.1f dB)",
                    self.client_id, event, reading.intensity, reading.db,
                )

    def _capture_loop(self) -> None:
        """Blocking capture loop — reads blocks and feeds the analyzer."""
        try:
            import sounddevice as sd
        except ImportError:
            _LOGGER.error(
                "sounddevice is not installed. Install it with: "
                "pip install sounddevice  (see requirements-audio.txt)"
            )
            sys.exit(1)

        _LOGGER.info(
            "Capturing audio: device=%s, %d Hz, block=%d",
            self.device if self.device is not None else "default",
            self.sample_rate, self.block,
        )
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            blocksize=self.block,
            device=self.device,
            dtype="float32",
        ) as stream:
            while self._running:
                data, _overflow = stream.read(self.block)
                # data is an (N, 1) float32 array in [-1, 1]; flatten to floats.
                samples = [float(row[0]) for row in data]
                self._handle_block(samples)

    def run(self) -> None:
        self._setup_mqtt()
        self._start_time = time.time()
        self._running = True

        def _signal_handler(sig, frame):
            _LOGGER.info("Shutting down audio worker...")
            self._running = False
            self._publish_status("offline")
            if self._client:
                self._client.disconnect()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        _LOGGER.info(
            "Audio Worker starting — client_id=%s, heartbeat=%.0fs",
            self.client_id, self.heartbeat,
        )
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_start()
            self._capture_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            if self._client:
                self._client.loop_stop()
            _LOGGER.info(
                "Audio Worker stopped. %d blocks, %d events published.",
                self._blocks_processed, self._events_published,
            )


def _list_devices() -> None:
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice is not installed. pip install sounddevice")
        return
    print(sd.query_devices())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Game Audio Worker for Gaming Assistant",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username")
    parser.add_argument("--password", default="", help="MQTT password")
    parser.add_argument(
        "--client-id", default=DEFAULT_CLIENT_ID,
        help="Capture client this audio belongs to (matches the capture agent)",
    )
    parser.add_argument(
        "--worker-id", default="audio_worker", help="Worker ID"
    )
    parser.add_argument(
        "--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE,
        help="Capture sample rate in Hz (default: 16000)",
    )
    parser.add_argument(
        "--block", type=int, default=DEFAULT_BLOCK,
        help="Samples per analysis block (default: 2048)",
    )
    parser.add_argument(
        "--device", default=None,
        help="Input device index or name (default: system default)",
    )
    parser.add_argument(
        "--heartbeat", type=float, default=DEFAULT_HEARTBEAT,
        help="Seconds between refreshes when nothing changes (default: 30)",
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List available audio devices and exit",
    )
    args = parser.parse_args()

    if args.list_devices:
        _list_devices()
        return

    # A numeric --device is an index; otherwise pass the name through.
    device: Any = args.device
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    worker = AudioWorker(
        broker=args.broker,
        port=args.port,
        client_id=args.client_id,
        sample_rate=args.sample_rate,
        block=args.block,
        device=device,
        heartbeat=args.heartbeat,
        username=args.username,
        password=args.password,
        worker_id=args.worker_id,
    )
    worker.run()


if __name__ == "__main__":
    main()
