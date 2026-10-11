#!/usr/bin/env python3
"""Gaming Assistant – RustDesk controller (Phase 8, GA-119).

Opens RustDesk remote sessions on command from Home Assistant, on the machine
where a person will use them (usually the gaming PC): "open the tablet" from a
dashboard button, a voice command or an automation.

RustDesk has no API for scripted *input*. What can be automated is starting a
connection, and that is all this worker does: it runs the installed RustDesk
client as a separate process (``rustdesk --connect <id>``). No RustDesk code is
imported or linked, so this project stays MIT-licensed. The person then works
in the RustDesk window as usual. RustDesk cannot close a session from the
command line either, so there is no "close": the session ends in its window.

Peers are configured on this machine, by name. Home Assistant only ever says
"open tablet" and never sees an ID or a password (``--peers``, JSON):

    {
      "tablet": {"id": "123 456 789"},
      "laptop": {"id": "987654321", "password": "only if you must"}
    }

Without a password, RustDesk uses the one it remembered for that peer or asks.
Prefer that: a password given here reaches RustDesk on its command line and is
visible to local process listings for a moment.

Requirements:
    pip install paho-mqtt        # and the RustDesk client, installed as usual

Usage:
    python rustdesk_controller.py --broker 192.168.1.10 --client-id gaming-pc \\
        --peers rustdesk_peers.json

MQTT topics:
  Subscribes:
    gaming_assistant/{client_id}/remote         — {"peer": "tablet", "mode": "control"}
  Publishes:
    gaming_assistant/{client_id}/remote_result  — outcome of each request (JSON)
    gaming_assistant/{client_id}/register       — registration (retained)
    gaming_assistant/{client_id}/status         — online/offline (retained, LWT)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("rustdesk_controller")

REMOTE_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/remote"
RESULT_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/remote_result"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/status"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/register"

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_COOLDOWN_S = 10.0

# How each mode starts a session (RustDesk command-line flags).
MODES = {
    "control": "--connect",
    "file_transfer": "--file-transfer",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_rustdesk() -> str | None:
    """Path of the installed RustDesk client, or None."""
    candidates = []
    on_path = shutil.which("rustdesk")
    if on_path:
        candidates.append(on_path)
    system = platform.system()
    if system == "Windows":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                candidates.append(os.path.join(base, "RustDesk", "rustdesk.exe"))
    elif system == "Darwin":
        candidates.append("/Applications/RustDesk.app/Contents/MacOS/RustDesk")
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def parse_peers(data: Any) -> dict[str, dict[str, str]]:
    """Validate a peers mapping: name -> {"id": ..., "password": optional}.

    IDs may be written as RustDesk shows them ("123 456 789"); spaces are
    removed. Raises ValueError on anything malformed.
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("peers must be a non-empty JSON object of name -> {id, password}")
    peers: dict[str, dict[str, str]] = {}
    for name, entry in data.items():
        if isinstance(entry, (str, int)):
            entry = {"id": entry}
        if not isinstance(entry, dict):
            raise ValueError(f"peer {name!r} must be an object with an 'id'")
        peer_id = "".join(str(entry.get("id", "")).split())
        if not peer_id:
            raise ValueError(f"peer {name!r} has no id")
        peer = {"id": peer_id}
        password = entry.get("password")
        if password:
            peer["password"] = str(password)
        peers[str(name).strip().lower()] = peer
    return peers


def parse_peer_args(values: list[str]) -> dict[str, dict[str, str]]:
    """``--peer tablet=123456789`` (repeatable; no passwords on purpose)."""
    data = {}
    for value in values:
        name, sep, peer_id = value.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"--peer expects NAME=ID, got {value!r}")
        data[name] = {"id": peer_id}
    return parse_peers(data) if data else {}


class RemoteController:
    """Turns requests from Home Assistant into RustDesk launches."""

    def __init__(
        self,
        rustdesk: str | None,
        peers: dict[str, dict[str, str]],
        *,
        client_id: str = "",
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        launch: Callable[..., Any] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rustdesk = rustdesk
        self.peers = peers
        self.client_id = client_id
        self.cooldown_s = cooldown_s
        self._launch = launch
        self._clock = clock
        self._last_open: dict[str, float] = {}

    def handle(self, raw) -> dict:
        """Open the requested session; return a result safe to publish.

        The result names the peer and mode, never its ID or password.
        """
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        result: dict[str, Any] = {"time": _now_iso(), "client_id": self.client_id}
        try:
            peer_name, mode = self._parse(text)
        except ValueError as err:
            result.update(result="rejected", reason=str(err))
            log.warning("Rejected remote request: %s", err)
            return result
        result.update(peer=peer_name, mode=mode)

        now = self._clock()
        last = self._last_open.get(peer_name)
        if last is not None and now - last < self.cooldown_s:
            result.update(result="skipped", reason=f"opened less than {self.cooldown_s:g} s ago")
            log.info("Skipped %s: cooldown", peer_name)
            return result
        if not self.rustdesk:
            result.update(result="error", reason="RustDesk client not found (use --rustdesk)")
            log.error("RustDesk client not found")
            return result

        peer = self.peers[peer_name]
        args = [self.rustdesk, MODES[mode], peer["id"]]
        if peer.get("password"):
            args += ["--password", peer["password"]]
        try:
            self._launch(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as err:
            result.update(result="error", reason=f"could not start RustDesk: {err.strerror or err}")
            log.error("Could not start RustDesk for %s: %s", peer_name, err)
            return result
        self._last_open[peer_name] = now
        result["result"] = "opened"
        log.info("Opened RustDesk %s session to %s", mode, peer_name)
        return result

    def _parse(self, text: str) -> tuple[str, str]:
        text = text.strip()
        if not text:
            raise ValueError("empty request")
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as err:
                raise ValueError(f"not valid JSON: {err}") from err
            if not isinstance(payload, dict):
                raise ValueError("request must be a JSON object")
            peer = str(payload.get("peer") or "").strip().lower()
            mode = str(payload.get("mode") or "control").strip().lower()
        else:  # plain peer name
            peer, mode = text.lower(), "control"
        if not peer:
            raise ValueError("request names no peer")
        if peer not in self.peers:
            raise ValueError(f"unknown peer {peer!r} (configure it on this machine)")
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}, expected one of {sorted(MODES)}")
        return peer, mode


# ---------------------------------------------------------------------------
# MQTT runner
# ---------------------------------------------------------------------------
def run(args) -> int:
    try:
        import paho.mqtt.client as mqtt_client
    except ImportError:
        log.error("paho-mqtt is not installed: pip install paho-mqtt")
        return 1

    try:
        peers: dict[str, dict[str, str]] = {}
        if args.peers:
            with open(args.peers, encoding="utf-8") as fh:
                peers.update(parse_peers(json.load(fh)))
        peers.update(parse_peer_args(args.peer))
    except (OSError, ValueError) as err:
        log.error("Peers: %s", err)
        return 1
    if not peers:
        log.error("No peers configured: use --peers FILE or --peer NAME=ID")
        return 1

    rustdesk = args.rustdesk or find_rustdesk()
    if not rustdesk:
        log.warning("RustDesk client not found; requests will fail until --rustdesk is set.")
    controller = RemoteController(
        rustdesk, peers, client_id=args.client_id, cooldown_s=args.cooldown
    )

    remote_topic = REMOTE_TOPIC_TEMPLATE.format(client_id=args.client_id)
    result_topic = RESULT_TOPIC_TEMPLATE.format(client_id=args.client_id)
    status_topic = STATUS_TOPIC_TEMPLATE.format(client_id=args.client_id)
    register_topic = REGISTER_TOPIC_TEMPLATE.format(client_id=args.client_id)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION1,
        client_id=f"gaming_assistant_rustdesk_{args.client_id}",
        protocol=mqtt_client.MQTTv311,
    )
    if args.username:
        client.username_pw_set(args.username, args.password)
    client.will_set(status_topic, "offline", qos=1, retain=True)

    def on_connect(c, userdata, flags, rc):
        if rc != 0:
            log.error("MQTT connection failed (rc=%d)", rc)
            return
        log.info("MQTT connected to %s:%d", args.broker, args.port)
        c.subscribe(remote_topic, qos=1)
        c.publish(
            register_topic,
            json.dumps(
                {
                    "name": f"RustDesk Controller ({args.client_id})",
                    "type": "rustdesk_controller",
                    "peers": sorted(peers),
                    "rustdesk_found": bool(rustdesk),
                    "platform": platform.system(),
                }
            ),
            qos=1,
            retain=True,
        )
        c.publish(status_topic, "online", qos=1, retain=True)

    def on_message(c, userdata, msg):
        result = controller.handle(msg.payload)
        c.publish(result_topic, json.dumps(result), qos=1)

    client.on_connect = on_connect
    client.on_message = on_message

    log.info("=== Gaming Assistant – RustDesk controller ===")
    log.info("Peers   : %s", ", ".join(sorted(peers)))
    log.info("RustDesk: %s", rustdesk or "(not found)")
    client.connect(args.broker, args.port, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("Stopping.")
    finally:
        client.publish(status_topic, "offline", qos=1, retain=True)
        client.disconnect()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – open RustDesk sessions on command from Home Assistant",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=platform.node(),
        help="Client ID in Home Assistant (default: hostname)",
    )
    parser.add_argument("--peers", default="", help="JSON file: name -> {id, password}")
    parser.add_argument(
        "--peer", action="append", default=[], help="NAME=ID, repeatable (no password)"
    )
    parser.add_argument("--rustdesk", default="", help="Path to the RustDesk client")
    parser.add_argument(
        "--cooldown", type=float, default=DEFAULT_COOLDOWN_S,
        help="Seconds before the same peer can be opened again",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
