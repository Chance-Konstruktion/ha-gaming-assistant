#!/usr/bin/env python3
"""Gaming Assistant – companion listener (Phase 8, GA-121).

Turns a few named commands from Home Assistant into key presses where you
play: pause the game when the doorbell rings, mute when a call comes in,
play/pause the music on the TV. It complements RustDesk, which can open a
session but cannot be scripted.

Only commands defined on this machine run. Home Assistant sends a *name*
("pause"), never a key, so a compromised broker can at worst press one of the
keys you listed here. The AI's Agent Mode never uses this channel.

Built in (no configuration needed), as media keys of this machine:
    play_pause, pause, stop, next, previous, mute, volume_up, volume_down

Your own, in a JSON file (``--commands``):

    {
      "game_pause": {"key": "escape"},
      "tablet_pause": {"adb": "KEYCODE_MEDIA_PAUSE", "serial": "R58N12345"},
      "tv_home": {"adb": "KEYCODE_HOME", "serial": "192.168.1.50:5555"}
    }

``key`` is one of: the media keys above, escape, space, enter, tab, p,
f1 … f12. ``adb`` is any Android ``KEYCODE_…`` name, sent with
``adb shell input keyevent`` to the device ``serial`` (optional with a
single device), so an Android tablet or TV needs no app, just ADB from this
machine, like the ADB capture agents.

How keys are pressed: Windows via the user32 API, Linux via ``xdotool``
(X11), macOS via ``osascript`` (plain keys only, no media keys).

Requirements:
    pip install paho-mqtt     # Linux also needs xdotool; Android needs adb

Usage:
    python companion_listener.py --broker 192.168.1.10 --client-id gaming-pc
    python companion_listener.py --broker 192.168.1.10 --client-id gaming-pc \\
        --commands companion_commands.json --dry-run

MQTT topics:
  Subscribes:
    gaming_assistant/{client_id}/companion         — "pause" or {"command": "pause"}
  Publishes:
    gaming_assistant/{client_id}/companion_result  — outcome of each command (JSON)
    gaming_assistant/{client_id}/register          — registration (retained)
    gaming_assistant/{client_id}/status            — online/offline (retained, LWT)
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("companion_listener")

COMPANION_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/companion"
RESULT_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/companion_result"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/status"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/register"

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_MIN_INTERVAL_S = 0.5

# key name -> (Windows virtual-key code, extended key, xdotool name, macOS key code)
_MEDIA_KEYS = {
    "play_pause": (0xB3, True, "XF86AudioPlay", None),
    "stop": (0xB2, True, "XF86AudioStop", None),
    "next": (0xB0, True, "XF86AudioNext", None),
    "previous": (0xB1, True, "XF86AudioPrev", None),
    "mute": (0xAD, True, "XF86AudioMute", None),
    "volume_up": (0xAF, True, "XF86AudioRaiseVolume", None),
    "volume_down": (0xAE, True, "XF86AudioLowerVolume", None),
}
_MAC_FKEYS = (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111)
KEYS = {
    **_MEDIA_KEYS,
    "escape": (0x1B, False, "Escape", 53),
    "space": (0x20, False, "space", 49),
    "enter": (0x0D, False, "Return", 36),
    "tab": (0x09, False, "Tab", 48),
    "p": (0x50, False, "p", 35),
    **{f"f{i}": (0x6F + i, False, f"F{i}", _MAC_FKEYS[i - 1]) for i in range(1, 13)},
}

# Ready to use without a commands file.
BUILTIN_COMMANDS = {
    **{name: {"key": name} for name in _MEDIA_KEYS},
    "pause": {"key": "play_pause"},
}

_ADB_KEYCODE = re.compile(r"^KEYCODE_[A-Z0-9_]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_commands(data: Any) -> dict[str, dict[str, str]]:
    """Validate a commands mapping: name -> {"key": ...} or {"adb": ..., "serial": ...}.

    Raises ValueError on anything that could not be run.
    """
    if not isinstance(data, dict):
        raise ValueError("commands must be a JSON object of name -> action")
    commands: dict[str, dict[str, str]] = {}
    for name, action in data.items():
        if not isinstance(action, dict):
            raise ValueError(f"command {name!r} must be an object")
        if "key" in action:
            key = str(action["key"]).strip().lower()
            if key not in KEYS:
                raise ValueError(f"command {name!r}: unknown key {key!r}")
            commands[str(name).strip().lower()] = {"key": key}
        elif "adb" in action:
            keycode = str(action["adb"]).strip().upper()
            if not _ADB_KEYCODE.match(keycode):
                raise ValueError(f"command {name!r}: adb needs a KEYCODE_… name, got {keycode!r}")
            entry = {"adb": keycode}
            if action.get("serial"):
                entry["serial"] = str(action["serial"]).strip()
            commands[str(name).strip().lower()] = entry
        else:
            raise ValueError(f"command {name!r} needs 'key' or 'adb'")
    return commands


class KeyPresser:
    """Presses one key on this machine, the platform's way."""

    def __init__(
        self,
        system: str | None = None,
        run: Callable[..., Any] = subprocess.run,
        user32: Any = None,
    ) -> None:
        self.system = system or platform.system()
        self._run = run
        self._user32 = user32

    def press(self, key: str) -> None:
        vk, extended, xdotool_name, mac_code = KEYS[key]
        if self.system == "Windows":
            user32 = self._user32
            if user32 is None:
                import ctypes

                user32 = ctypes.windll.user32
            flags = 0x1 if extended else 0x0  # KEYEVENTF_EXTENDEDKEY
            user32.keybd_event(vk, 0, flags, 0)
            user32.keybd_event(vk, 0, flags | 0x2, 0)  # KEYEVENTF_KEYUP
        elif self.system == "Linux":
            if not shutil.which("xdotool"):
                raise RuntimeError("xdotool is not installed (needed for key presses on Linux)")
            self._run(["xdotool", "key", xdotool_name], check=True, timeout=5)
        elif self.system == "Darwin":
            if mac_code is None:
                raise RuntimeError(f"{key} cannot be pressed on macOS")
            script = f'tell application "System Events" to key code {mac_code}'
            self._run(["osascript", "-e", script], check=True, timeout=5)
        else:
            raise RuntimeError(f"key presses are not supported on {self.system}")


class CompanionListener:
    """Runs the named commands Home Assistant sends."""

    def __init__(
        self,
        commands: dict[str, dict[str, str]],
        *,
        client_id: str = "",
        presser: KeyPresser | None = None,
        adb: str = "adb",
        run: Callable[..., Any] = subprocess.run,
        dry_run: bool = False,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.commands = commands
        self.client_id = client_id
        self.presser = presser or KeyPresser()
        self.adb = adb
        self._run = run
        self.dry_run = dry_run
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._last: float | None = None

    def handle(self, raw) -> dict:
        """Run one command; return a result for Home Assistant."""
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        result: dict[str, Any] = {"time": _now_iso(), "client_id": self.client_id}
        try:
            name = self._parse(text)
        except ValueError as err:
            result.update(result="rejected", reason=str(err))
            log.warning("Rejected command: %s", err)
            return result
        result["command"] = name

        now = self._clock()
        if self._last is not None and now - self._last < self.min_interval_s:
            result.update(result="skipped", reason="too soon after the last command")
            return result
        self._last = now

        action = self.commands[name]
        if self.dry_run:
            result.update(result="dry_run", action=action)
            log.info("[dry-run] %s -> %s", name, action)
            return result
        try:
            if "key" in action:
                self.presser.press(action["key"])
            else:
                args = [self.adb]
                if action.get("serial"):
                    args += ["-s", action["serial"]]
                args += ["shell", "input", "keyevent", action["adb"]]
                self._run(args, check=True, timeout=10, capture_output=True)
        except (OSError, RuntimeError, subprocess.SubprocessError) as err:
            result.update(result="error", reason=str(err))
            log.error("Command %s failed: %s", name, err)
            return result
        result["result"] = "done"
        log.info("Ran %s", name)
        return result

    def _parse(self, text: str) -> str:
        text = text.strip()
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as err:
                raise ValueError(f"not valid JSON: {err}") from err
            if not isinstance(payload, dict):
                raise ValueError("request must be a JSON object")
            text = str(payload.get("command") or "")
        name = text.strip().lower()
        if not name:
            raise ValueError("no command given")
        if name not in self.commands:
            raise ValueError(f"unknown command {name!r} (define it on this machine)")
        return name


# ---------------------------------------------------------------------------
# MQTT runner
# ---------------------------------------------------------------------------
def run(args) -> int:
    try:
        import paho.mqtt.client as mqtt_client
    except ImportError:
        log.error("paho-mqtt is not installed: pip install paho-mqtt")
        return 1

    commands = dict(BUILTIN_COMMANDS)
    if args.commands:
        try:
            with open(args.commands, encoding="utf-8") as fh:
                commands.update(parse_commands(json.load(fh)))
        except (OSError, ValueError) as err:
            log.error("Commands: %s", err)
            return 1
    listener = CompanionListener(
        commands,
        client_id=args.client_id,
        adb=args.adb,
        dry_run=args.dry_run,
        min_interval_s=args.min_interval,
    )

    command_topic = COMPANION_TOPIC_TEMPLATE.format(client_id=args.client_id)
    result_topic = RESULT_TOPIC_TEMPLATE.format(client_id=args.client_id)
    status_topic = STATUS_TOPIC_TEMPLATE.format(client_id=args.client_id)
    register_topic = REGISTER_TOPIC_TEMPLATE.format(client_id=args.client_id)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION1,
        client_id=f"gaming_assistant_companion_{args.client_id}",
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
        c.subscribe(command_topic, qos=1)
        c.publish(
            register_topic,
            json.dumps(
                {
                    "name": f"Companion ({args.client_id})",
                    "type": "companion_listener",
                    "commands": sorted(commands),
                    "dry_run": args.dry_run,
                    "platform": platform.system(),
                }
            ),
            qos=1,
            retain=True,
        )
        c.publish(status_topic, "online", qos=1, retain=True)

    def on_message(c, userdata, msg):
        c.publish(result_topic, json.dumps(listener.handle(msg.payload)), qos=1)

    client.on_connect = on_connect
    client.on_message = on_message

    log.info("=== Gaming Assistant – companion listener ===")
    log.info("Commands: %s", ", ".join(sorted(commands)))
    if args.dry_run:
        log.info("DRY-RUN: commands are logged, no key is pressed.")
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
        description="Gaming Assistant – run named commands (media keys, keys, adb) from HA",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument(
        "--client-id", default=platform.node(),
        help="Client ID in Home Assistant (default: hostname)",
    )
    parser.add_argument("--commands", default="", help="JSON file with your own commands")
    parser.add_argument("--adb", default="adb", help="Path to adb (for adb commands)")
    parser.add_argument("--dry-run", action="store_true", help="Log commands, press nothing")
    parser.add_argument(
        "--min-interval", type=float, default=DEFAULT_MIN_INTERVAL_S,
        help="Seconds between two commands (protects against floods)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
