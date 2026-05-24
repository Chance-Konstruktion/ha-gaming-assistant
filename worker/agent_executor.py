#!/usr/bin/env python3
"""Gaming Assistant – Agent Mode Executor (Player 2).

An OPTIONAL external worker that lets the AI *play* a game by replaying
controller inputs on a **virtual Xbox gamepad** (`vgamepad`). It subscribes
to structured JSON actions published by Home Assistant, validates every
action against a button whitelist, writes an audit log, and only then
forwards it to the virtual controller.

Why a virtual gamepad (and not keyboard/mouse injection)? A virtual
controller can only send game-controller inputs — it can never move the
mouse, alt-tab, or type system commands. The AI is sandboxed to "press
buttons", which is the whole safety premise of Agent Mode.

Safety model
------------
- **Whitelist:** only buttons in ``--allow-buttons`` (default: all Xbox
  buttons) are ever forwarded; anything else is rejected and audited.
- **Dry-run:** ``--dry-run`` (and the implicit fallback when ``vgamepad``
  is not installed) validates + audits actions without touching the
  controller. Great for a first run.
- **Audit log:** every action — accepted, rejected, or skipped — is
  appended as one JSON line to ``--audit-log``.
- **Emergency stop:** publishing ``stop`` to ``gaming_assistant/command``
  pauses execution and releases all inputs; ``start`` resumes. Inputs are
  also released on disconnect and shutdown so nothing stays stuck.

Requirements:
    pip install -r requirements-player2.txt   # vgamepad + paho-mqtt

Usage:
    # Safe first run — validates + logs, sends nothing:
    python agent_executor.py --broker 192.168.1.10 --dry-run

    # Live, restricted to face buttons + D-pad:
    python agent_executor.py --broker 192.168.1.10 \\
      --client-id gaming-pc \\
      --allow-buttons A,B,X,Y,DPAD_UP,DPAD_DOWN,DPAD_LEFT,DPAD_RIGHT

MQTT Topics:
  Subscribes:
    gaming_assistant/{client_id}/action   — structured JSON action
    gaming_assistant/command              — global start/stop (emergency)
  Publishes:
    gaming_assistant/{client_id}/register — executor registration (retained)
    gaming_assistant/{client_id}/status   — online/offline (retained, LWT)

Action JSON (matches PromptBuilder.ACTION_SCHEMA in the integration):
    {"action": "tap_button", "button": "A", "duration_ms": 80, "reason": "..."}
    {"action": "press_button", "button": "RB"}
    {"action": "release_button", "button": "RB"}
    {"action": "move_stick", "stick": "left", "x": 0.5, "y": -0.3}
    {"action": "wait", "duration_ms": 200}
    {"action": "no_op", "reason": "nothing useful to do"}
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import re
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Callable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("agent_executor")

# Lazy imports — only fail if actually used without installing.
_MQTT_AVAILABLE = False
_VGAMEPAD_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt_client

    _MQTT_AVAILABLE = True
except ImportError:
    pass

try:
    import vgamepad

    _VGAMEPAD_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host (Windows + ViGEmBus)
    vgamepad = None

# ---------------------------------------------------------------------------
# MQTT topics
# ---------------------------------------------------------------------------
ACTION_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/action"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/status"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/register"
COMMAND_TOPIC = "gaming_assistant/command"

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_TAP_MS = 80
MAX_DURATION_MS = 5000

# ---------------------------------------------------------------------------
# Action contract (kept in sync with PromptBuilder.ACTION_SCHEMA in the
# integration). The executor re-validates defensively: it is the last line
# of defence before a real input is emitted, so it never trusts the payload.
# ---------------------------------------------------------------------------
VALID_ACTIONS = frozenset(
    {
        "press_button",
        "release_button",
        "tap_button",
        "move_stick",
        "wait",
        "no_op",
    }
)
BUTTON_ACTIONS = frozenset({"press_button", "release_button", "tap_button"})

# Analog triggers are not digital XUSB buttons — handled via *_trigger_float.
TRIGGER_BUTTONS = frozenset({"LT", "RT"})

# Digital button name -> vgamepad XUSB_BUTTON enum member name.
_BUTTON_TO_XUSB = {
    "A": "XUSB_GAMEPAD_A",
    "B": "XUSB_GAMEPAD_B",
    "X": "XUSB_GAMEPAD_X",
    "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
    "START": "XUSB_GAMEPAD_START",
    "BACK": "XUSB_GAMEPAD_BACK",
}

VALID_BUTTONS = frozenset(_BUTTON_TO_XUSB) | TRIGGER_BUTTONS
ACTION_KEYS = frozenset(
    {"action", "button", "stick", "x", "y", "duration_ms", "reason"}
)


def parse_action(text, allowed_buttons: list[str] | None = None) -> dict:
    """Decode and validate one action, returning a sanitized dict.

    Mirrors ``PromptBuilder.parse_action`` in the integration. Raises
    ``ValueError`` when the payload is missing, not JSON, violates the
    schema, or names a button outside the whitelist. Unknown keys are
    stripped. ``allowed_buttons=None`` means "all valid buttons".
    """
    if not text or not str(text).strip():
        raise ValueError("empty action response")

    stripped = str(text).strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise ValueError(f"not valid JSON: {err}") from err

    if not isinstance(payload, dict):
        raise ValueError("action must be a JSON object")

    action = payload.get("action")
    if action not in VALID_ACTIONS:
        raise ValueError(f"unknown action {action!r}")

    allowed = {
        b.upper()
        for b in (allowed_buttons if allowed_buttons is not None else VALID_BUTTONS)
    }

    if action in BUTTON_ACTIONS:
        button = payload.get("button")
        if not isinstance(button, str) or not button:
            raise ValueError(f"{action} requires a 'button' string")
        button_up = button.upper()
        if button_up not in VALID_BUTTONS:
            raise ValueError(f"unknown button '{button}'")
        if button_up not in allowed:
            raise ValueError(f"button '{button}' is not whitelisted")
        payload["button"] = button_up

    if action == "move_stick":
        stick = payload.get("stick")
        if stick not in ("left", "right"):
            raise ValueError("move_stick requires stick in {left, right}")
        for axis in ("x", "y"):
            val = payload.get(axis, 0.0)
            if (
                isinstance(val, bool)
                or not isinstance(val, (int, float))
                or not -1.0 <= val <= 1.0
            ):
                raise ValueError(f"move_stick axis '{axis}' must be in [-1.0, 1.0]")

    duration = payload.get("duration_ms")
    if duration is not None:
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 0
            or duration > MAX_DURATION_MS
        ):
            raise ValueError(f"duration_ms must be an int in [0, {MAX_DURATION_MS}]")

    return {k: v for k, v in payload.items() if k in ACTION_KEYS}


# ---------------------------------------------------------------------------
# Virtual gamepad wrapper (isolates the vgamepad-specific calls)
# ---------------------------------------------------------------------------
class GamepadController:
    """Thin semantic wrapper over a ``vgamepad`` virtual Xbox controller.

    Keeping the vgamepad specifics here lets the executor be unit-tested
    with a plain mock controller (no Windows / ViGEmBus required).
    """

    def __init__(self, gamepad, xusb_enum):
        self._pad = gamepad
        self._xusb = xusb_enum

    @classmethod
    def create(cls) -> "GamepadController":
        if not _VGAMEPAD_AVAILABLE:
            raise RuntimeError(
                "vgamepad is not installed. Install worker/requirements-player2.txt "
                "(and the ViGEmBus driver on Windows), or run with --dry-run."
            )
        return cls(vgamepad.VX360Gamepad(), vgamepad.XUSB_BUTTON)

    def _enum(self, name: str):
        return getattr(self._xusb, _BUTTON_TO_XUSB[name])

    def press(self, name: str) -> None:
        self._pad.press_button(button=self._enum(name))

    def release(self, name: str) -> None:
        self._pad.release_button(button=self._enum(name))

    def trigger(self, name: str, value: float) -> None:
        if name == "LT":
            self._pad.left_trigger_float(value_float=value)
        else:
            self._pad.right_trigger_float(value_float=value)

    def stick(self, side: str, x: float, y: float) -> None:
        if side == "left":
            self._pad.left_joystick_float(x_value_float=x, y_value_float=y)
        else:
            self._pad.right_joystick_float(x_value_float=x, y_value_float=y)

    def update(self) -> None:
        self._pad.update()

    def reset(self) -> None:
        self._pad.reset()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def make_file_audit(path: str) -> Callable[[dict], None]:
    """Return an audit hook that appends each entry as one JSON line."""

    def _write(entry: dict) -> None:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as err:
            log.error("Audit write failed: %s", err)

    return _write


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------
class AgentExecutor:
    """Validates actions and replays accepted ones on the gamepad."""

    def __init__(
        self,
        controller: GamepadController | None,
        *,
        client_id: str = "",
        allowed_buttons: list[str] | None = None,
        dry_run: bool = False,
        default_tap_ms: int = DEFAULT_TAP_MS,
        audit: Callable[[dict], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.controller = controller
        self.client_id = client_id
        self.allowed_buttons = sorted(
            {
                b.upper()
                for b in (
                    allowed_buttons if allowed_buttons is not None else VALID_BUTTONS
                )
            }
        )
        # No controller -> always dry-run, so we never pretend to send input.
        self.dry_run = dry_run or controller is None
        self.default_tap_ms = default_tap_ms
        self.audit = audit
        self._sleep = sleep
        self.paused = False

    # -- public API ---------------------------------------------------------
    def handle(self, raw) -> dict:
        """Parse, validate, audit and (unless dry-run/paused) execute."""
        text = (
            raw.decode("utf-8", "replace")
            if isinstance(raw, (bytes, bytearray))
            else str(raw)
        )
        entry = {"time": _now_iso(), "client_id": self.client_id}

        try:
            action = parse_action(text, self.allowed_buttons)
        except ValueError as err:
            entry.update(result="rejected", reason=str(err), payload=text[:500])
            log.warning("Rejected action: %s", err)
            self._record(entry)
            return entry

        entry["action"] = action

        if self.paused:
            entry.update(result="skipped", reason="executor paused (emergency stop)")
            log.info("Skipped (paused): %s", action)
            self._record(entry)
            return entry

        if self.dry_run:
            entry["result"] = "dry_run"
            log.info("[dry-run] %s", action)
            self._record(entry)
            return entry

        try:
            self.execute(action)
            entry["result"] = "executed"
            log.info("Executed: %s", action)
        except Exception as err:  # pragma: no cover - depends on real device
            entry.update(result="error", reason=str(err))
            log.exception("Execution failed: %s", err)

        self._record(entry)
        return entry

    def execute(self, action: dict) -> None:
        """Forward a *validated* action to the controller."""
        kind = action["action"]
        if kind == "no_op":
            return
        if kind == "wait":
            self._do_sleep(action.get("duration_ms", 0))
            return
        if kind == "move_stick":
            self.controller.stick(
                action["stick"],
                float(action.get("x", 0.0)),
                float(action.get("y", 0.0)),
            )
            self.controller.update()
            return

        button = action["button"]
        if kind == "press_button":
            self._press(button)
        elif kind == "release_button":
            self._release(button)
        elif kind == "tap_button":
            duration = action.get("duration_ms")
            duration = self.default_tap_ms if duration is None else duration
            self._press(button)
            self._do_sleep(duration)
            self._release(button)

    def pause(self) -> None:
        """Emergency stop: release everything and ignore further actions."""
        self.paused = True
        self.reset()
        log.warning("Executor PAUSED — inputs released, actions will be skipped.")

    def resume(self) -> None:
        self.paused = False
        log.info("Executor RESUMED.")

    def reset(self) -> None:
        """Return the controller to neutral (no buttons / sticks held)."""
        if self.controller is None:
            return
        self.controller.reset()
        self.controller.update()

    # -- internals ----------------------------------------------------------
    def _press(self, button: str) -> None:
        if button in TRIGGER_BUTTONS:
            self.controller.trigger(button, 1.0)
        else:
            self.controller.press(button)
        self.controller.update()

    def _release(self, button: str) -> None:
        if button in TRIGGER_BUTTONS:
            self.controller.trigger(button, 0.0)
        else:
            self.controller.release(button)
        self.controller.update()

    def _do_sleep(self, ms) -> None:
        if ms and ms > 0:
            self._sleep(ms / 1000.0)

    def _record(self, entry: dict) -> None:
        if self.audit is None:
            return
        try:
            self.audit(entry)
        except Exception:  # pragma: no cover - audit must never crash handling
            log.exception("Audit hook failed")


# ---------------------------------------------------------------------------
# MQTT runner
# ---------------------------------------------------------------------------
def _handle_command(executor: AgentExecutor, payload: bytes) -> None:
    cmd = payload.decode("utf-8", "replace").strip().lower()
    if cmd in ("stop", "pause"):
        executor.pause()
    elif cmd in ("start", "resume"):
        executor.resume()


def run(args) -> None:
    if not _MQTT_AVAILABLE:
        log.error("paho-mqtt is not installed. Install: pip install paho-mqtt")
        sys.exit(1)

    allowed = _parse_allow_buttons(args.allow_buttons)

    controller: GamepadController | None = None
    if args.dry_run:
        log.info("DRY-RUN mode: actions are validated and logged, never sent.")
    elif _VGAMEPAD_AVAILABLE:
        try:
            controller = GamepadController.create()
            log.info("Virtual Xbox controller ready.")
        except Exception as err:
            log.error("Could not init virtual gamepad (%s); falling back to dry-run.", err)
    else:
        log.warning(
            "vgamepad not installed — running DRY-RUN (no inputs sent). "
            "Install worker/requirements-player2.txt to enable Agent Mode."
        )

    audit = make_file_audit(args.audit_log) if args.audit_log else None
    executor = AgentExecutor(
        controller,
        client_id=args.client_id,
        allowed_buttons=allowed,
        dry_run=args.dry_run,
        default_tap_ms=args.tap_ms,
        audit=audit,
    )

    action_topic = ACTION_TOPIC_TEMPLATE.format(client_id=args.client_id)
    status_topic = STATUS_TOPIC_TEMPLATE.format(client_id=args.client_id)
    register_topic = REGISTER_TOPIC_TEMPLATE.format(client_id=args.client_id)

    client = mqtt_client.Client(
        client_id=f"gaming_assistant_executor_{args.client_id}",
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
        c.subscribe(action_topic, qos=1)
        c.subscribe(COMMAND_TOPIC, qos=1)
        log.info("Subscribed to %s and %s", action_topic, COMMAND_TOPIC)
        c.publish(
            register_topic,
            json.dumps(
                {
                    "name": f"Agent Executor ({args.client_id})",
                    "type": "agent_executor",
                    "dry_run": executor.dry_run,
                    "allowed_buttons": executor.allowed_buttons,
                    "platform": platform.system(),
                }
            ),
            qos=1,
            retain=True,
        )
        c.publish(status_topic, "online", qos=1, retain=True)

    def on_message(c, userdata, msg):
        if msg.topic == COMMAND_TOPIC:
            _handle_command(executor, msg.payload)
            return
        if msg.topic == action_topic:
            executor.handle(msg.payload)

    def on_disconnect(c, userdata, rc):
        # Release any held inputs if the broker drops us unexpectedly.
        executor.reset()
        if rc != 0:
            log.warning("Unexpected MQTT disconnect (rc=%d), reconnecting...", rc)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    def _shutdown(signum, frame):
        log.info("Signal %s received, shutting down.", signum)
        client.disconnect()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _shutdown)

    log.info("=== Gaming Assistant – Agent Executor (Player 2) ===")
    log.info("Broker        : %s:%d", args.broker, args.port)
    log.info("Client ID     : %s", args.client_id)
    log.info("Allowed buttons: %s", ", ".join(executor.allowed_buttons))
    log.info("Audit log     : %s", args.audit_log or "(disabled)")

    client.connect(args.broker, args.port, keepalive=60)
    try:
        client.loop_forever()
    finally:
        executor.reset()
        client.publish(status_topic, "offline", qos=1, retain=True)
        client.disconnect()
        log.info("Agent executor stopped.")


def _parse_allow_buttons(raw: str) -> list[str] | None:
    if not raw or raw.strip().lower() == "all":
        return None
    names = [b.strip().upper() for b in raw.split(",") if b.strip()]
    unknown = [b for b in names if b not in VALID_BUTTONS]
    if unknown:
        log.warning("Ignoring unknown buttons in --allow-buttons: %s", ", ".join(unknown))
    valid = [b for b in names if b in VALID_BUTTONS]
    return valid or None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – Agent Mode Executor (virtual gamepad)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id",
        default=platform.node(),
        help="Client ID — must match the capture client (default: hostname)",
    )
    parser.add_argument(
        "--allow-buttons",
        default="all",
        help=(
            "Comma-separated whitelist of buttons the AI may press "
            "(e.g. A,B,X,Y,DPAD_UP). Default 'all'."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and log actions without sending any input.",
    )
    parser.add_argument(
        "--tap-ms",
        type=int,
        default=DEFAULT_TAP_MS,
        help="Default press duration for tap_button when none is given.",
    )
    parser.add_argument(
        "--audit-log",
        default="agent_executor_audit.log",
        help="Path to the JSON-lines audit log ('' to disable).",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
