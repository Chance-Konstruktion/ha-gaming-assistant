#!/usr/bin/env python3
"""Gaming Assistant – ViZDoom hybrid agent (Player 2 experiment, GA-111).

Plays Doom inside ViZDoom (https://vizdoom.farama.org) with two layers that
work at very different speeds:

* **Reflexes (local, every tic = 35 times a second).** ViZDoom reports what is
  on screen with bounding boxes (the labels buffer). If an enemy is in view,
  the agent turns toward the biggest one and fires as soon as the crosshair is
  on it. No model and no learning: fast enough for a firefight, which an LLM
  in the loop is not.
* **Strategy (Home Assistant, every few seconds).** The agent is also a normal
  capture client: it publishes frames, HUD numbers (health, armor, ammo,
  kills) and a description of its controls. With Agent Mode on, Home
  Assistant turns a frame into one controller action, which arrives on
  ``gaming_assistant/{client_id}/action`` exactly as it would for the
  vgamepad executor. The agent maps it to Doom buttons and holds it for a
  moment: walk, turn, open a door, switch weapons. Tips, game state and the
  Tier 3 strategy work as for any other game.

How the layers share the controls: while an enemy is in view, the reflexes own
aiming and firing and the strategy keeps moving the body (strafing while
shooting). With no enemy in view, the strategy steers. With neither, the agent
slowly turns on the spot to look for enemies (``--idle scan``, the default).

Everything the AI does here happens inside the ViZDoom process: no virtual
gamepad, no keyboard or mouse, nothing outside the game. The safety rails
mirror ``agent_executor.py``: a button whitelist, an audit log of every action
from Home Assistant, and ``stop`` / ``start`` on ``gaming_assistant/command``.

Requirements:
    pip install -r requirements-vizdoom.txt   # vizdoom + paho-mqtt + Pillow

Usage:
    # Reflexes only, no Home Assistant — watch the agent fight:
    python vizdoom_agent.py --offline --show --scenario defend_the_center

    # Hybrid with Home Assistant (then turn on Agent Mode there):
    python vizdoom_agent.py --broker 192.168.1.10 --client-id doom --show

MQTT topics:
  Publishes:
    gaming_assistant/{client_id}/image     — JPEG frame every --interval s
    gaming_assistant/{client_id}/meta      — game "Doom" plus the controls hint
    gaming_assistant/{client_id}/hud       — health, armor, ammo, kills
    gaming_assistant/{client_id}/register  — registration (retained)
    gaming_assistant/{client_id}/status    — online/offline (retained, LWT)
  Subscribes:
    gaming_assistant/{client_id}/action    — Agent Mode actions from HA
    gaming_assistant/command               — stop / start (emergency)
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import os
import platform
import queue
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

try:  # run as a script from worker/
    from agent_executor import (
        VALID_BUTTONS,
        _parse_allow_buttons,
        make_file_audit,
        parse_action,
    )
except ImportError:  # imported as part of the worker package (tests)
    from worker.agent_executor import (
        VALID_BUTTONS,
        _parse_allow_buttons,
        make_file_audit,
        parse_action,
    )

log = logging.getLogger("vizdoom_agent")

# ---------------------------------------------------------------------------
# MQTT topics
# ---------------------------------------------------------------------------
ACTION_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/action"
IMAGE_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/image"
META_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/meta"
HUD_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/hud"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/status"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/register"
COMMAND_TOPIC = "gaming_assistant/command"

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883

# ---------------------------------------------------------------------------
# Doom side
# ---------------------------------------------------------------------------
TICRATE = 35  # Doom runs 35 tics per second

# The Doom buttons the agent uses, in the order of ViZDoom's action vector.
DOOM_BUTTONS = (
    "MOVE_FORWARD",
    "MOVE_BACKWARD",
    "MOVE_LEFT",
    "MOVE_RIGHT",
    "TURN_LEFT",
    "TURN_RIGHT",
    "ATTACK",
    "USE",
    "SPEED",
    "SELECT_NEXT_WEAPON",
    "SELECT_PREV_WEAPON",
)
TURN_BUTTONS = frozenset({"TURN_LEFT", "TURN_RIGHT"})
# Weapon switching reacts to a press; holding it would cycle every tic.
ONE_TIC_BUTTONS = frozenset({"SELECT_NEXT_WEAPON", "SELECT_PREV_WEAPON"})

# Agent Mode speaks Xbox: which Doom button each controller button holds.
# B, START and BACK have no job here (START would open Doom's menu).
GAMEPAD_TO_DOOM = {
    "RT": "ATTACK",
    "A": "USE",
    "X": "USE",
    "LT": "SPEED",
    "RB": "SELECT_NEXT_WEAPON",
    "Y": "SELECT_NEXT_WEAPON",
    "LB": "SELECT_PREV_WEAPON",
    "DPAD_UP": "MOVE_FORWARD",
    "DPAD_DOWN": "MOVE_BACKWARD",
    "DPAD_LEFT": "TURN_LEFT",
    "DPAD_RIGHT": "TURN_RIGHT",
}
STICK_DEADZONE = 0.3

# Sent with every frame (meta "controls"), so Agent Mode's LLM knows what the
# buttons do in this game.
CONTROLS_HINT = (
    "Left stick walks: y>0 forward, y<0 back, x strafes. Right stick x turns "
    "(x<0 left, x>0 right). RT fires, A opens doors and presses switches, "
    "RB/LB switch weapons, LT runs. Aiming at and shooting visible enemies is "
    "automatic; you decide where to go."
)

# Game variables published as HUD numbers, in ViZDoom's order.
GAME_VARIABLES = ("HEALTH", "ARMOR", "SELECTED_WEAPON_AMMO", "KILLCOUNT")
HUD_FIELDS = ("health", "armor", "ammo", "kills")

# Monsters by actor class name, for ViZDoom releases whose labels carry no
# object_category yet (newer ones say "Monster" for every living monster).
ENEMY_NAMES = frozenset(
    {
        "zombieman", "shotgunguy", "chaingunguy", "doomimp", "demon", "spectre",
        "lostsoul", "cacodemon", "hellknight", "baronofhell", "arachnotron",
        "painelemental", "revenant", "fatso", "archvile", "spidermastermind",
        "cyberdemon", "wolfensteinss", "marinechainsawvzd", "marinefist",
        "marinechainsaw", "marinepistol", "marineshotgun", "marinessg",
        "marinechaingun", "marinerocket", "marineplasma", "marinerailgun",
        "marinebfg", "marineberserk", "scriptedmarine",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ms_to_tics(ms: float) -> int:
    """Doom tics for a duration in milliseconds (at least one)."""
    return max(1, math.ceil(ms * TICRATE / 1000))


# ---------------------------------------------------------------------------
# Reflexes
# ---------------------------------------------------------------------------
def is_enemy(label: Any, names: frozenset[str] | None = None) -> bool:
    """Whether a ViZDoom label is a living enemy.

    Killed monsters drop out of ViZDoom's labels (checked with 1.3.1); should a
    release label them, it names them "Dead<Class>", so corpses never count. With
    *names* given, only those classes are enemies; otherwise the label's
    category decides ("Monster"), falling back to the built-in list on
    ViZDoom releases without categories.
    """
    name = str(getattr(label, "object_name", "") or "").lower()
    if not name or name.startswith("dead"):
        return False
    if names is not None:
        return name in names
    category = getattr(label, "object_category", None)
    if category:
        return category == "Monster"
    return name in ENEMY_NAMES


def pick_target(labels: Iterable[Any], names: frozenset[str] | None = None):
    """The enemy to deal with first: the biggest on screen, usually the closest."""
    best, best_area = None, -1.0
    for label in labels or ():
        if not is_enemy(label, names):
            continue
        area = float(label.width) * float(label.height)
        if area > best_area:
            best, best_area = label, area
    return best


def reflex_buttons(
    labels: Iterable[Any], screen_width: int, names: frozenset[str] | None = None
) -> set[str] | None:
    """Aim at and fire on the target; None when no enemy is in view."""
    target = pick_target(labels, names)
    if target is None:
        return None
    offset = (target.x + target.width / 2) - screen_width / 2
    # On target once the crosshair is inside the box; a far enemy gets a few
    # pixels of slack so the aim does not swing past a tiny sprite.
    if abs(offset) <= max(target.width / 2, 4):
        return {"ATTACK"}
    return {"TURN_RIGHT"} if offset > 0 else {"TURN_LEFT"}


# ---------------------------------------------------------------------------
# Strategy (Home Assistant's Agent Mode actions)
# ---------------------------------------------------------------------------
class StrategyInput:
    """Doom buttons that Home Assistant's actions hold, each until a tic."""

    def __init__(
        self,
        *,
        tap_ms: int = 80,
        stick_hold_ms: int = 1500,
        max_hold_ms: int = 3000,
    ) -> None:
        self.tap_tics = ms_to_tics(tap_ms)
        self.stick_tics = ms_to_tics(stick_hold_ms)
        self.max_tics = ms_to_tics(max_hold_ms)
        self._until: dict[str, int] = {}

    def apply(self, action: dict, tic: int) -> str | None:
        """Apply a validated action at *tic*; return why it was ignored, if it was."""
        kind = action["action"]
        if kind in ("wait", "no_op"):
            return None
        if kind == "move_stick":
            self._apply_stick(action, tic)
            return None
        button = GAMEPAD_TO_DOOM.get(action["button"])
        if button is None:
            return f"{action['button']} has no use in Doom"
        if kind == "release_button":
            self._until.pop(button, None)
            return None
        if button in ONE_TIC_BUTTONS:
            tics = 1
        elif kind == "tap_button":
            duration = action.get("duration_ms")
            tics = self.tap_tics if duration is None else ms_to_tics(duration)
        else:  # press_button: held until released, but never forever
            tics = self.max_tics
        self._until[button] = tic + min(tics, self.max_tics)
        return None

    def _apply_stick(self, action: dict, tic: int) -> None:
        x = float(action.get("x", 0.0))
        y = float(action.get("y", 0.0))
        if action["stick"] == "left":
            wanted = {
                "MOVE_FORWARD": y > STICK_DEADZONE,
                "MOVE_BACKWARD": y < -STICK_DEADZONE,
                "MOVE_RIGHT": x > STICK_DEADZONE,
                "MOVE_LEFT": x < -STICK_DEADZONE,
            }
        else:  # right stick: turning only, Doom has no free look here
            wanted = {
                "TURN_RIGHT": x > STICK_DEADZONE,
                "TURN_LEFT": x < -STICK_DEADZONE,
            }
        duration = action.get("duration_ms")
        tics = self.stick_tics if not duration else ms_to_tics(duration)
        for button, on in wanted.items():
            if on:
                self._until[button] = tic + min(tics, self.max_tics)
            else:
                self._until.pop(button, None)

    def held(self, tic: int) -> set[str]:
        """Buttons still held at *tic* (expired ones are dropped)."""
        self._until = {b: t for b, t in self._until.items() if t > tic}
        return set(self._until)

    def clear(self) -> None:
        self._until.clear()


# ---------------------------------------------------------------------------
# The hybrid
# ---------------------------------------------------------------------------
class HybridAgent:
    """Merges the reflexes and Home Assistant's actions into one input per tic.

    Actions arrive on the MQTT thread (:meth:`submit`) and are applied on the
    game thread at the next tic, so the game loop never shares state with the
    network thread. :meth:`pause` / :meth:`resume` only flip a flag.
    """

    def __init__(
        self,
        *,
        strategy: StrategyInput | None = None,
        reflexes: bool = True,
        idle: str = "scan",
        allowed_buttons: list[str] | None = None,
        enemy_names: frozenset[str] | None = None,
        client_id: str = "",
        audit: Callable[[dict], None] | None = None,
    ) -> None:
        self.strategy = strategy or StrategyInput()
        self.reflexes = reflexes
        self.idle = idle
        allowed = VALID_BUTTONS if allowed_buttons is None else allowed_buttons
        self.allowed_buttons = sorted({b.upper() for b in allowed})
        self.enemy_names = enemy_names
        self.client_id = client_id
        self.audit = audit
        self.paused = False
        self.counts = {"accepted": 0, "ignored": 0, "rejected": 0, "skipped": 0}
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()

    # -- MQTT thread ----------------------------------------------------------
    def submit(self, raw) -> None:
        """Queue an action payload from Home Assistant for the next tic."""
        self._inbox.put(raw)

    def pause(self) -> None:
        """Emergency stop: from the next tic on, no input at all."""
        self.paused = True
        log.warning("Agent PAUSED: no input until 'start'.")

    def resume(self) -> None:
        self.paused = False
        log.info("Agent RESUMED.")

    # -- game thread ----------------------------------------------------------
    def step(self, labels: Iterable[Any], screen_width: int, tic: int) -> set[str]:
        """The Doom buttons to hold during this tic."""
        self._drain(tic)
        if self.paused:
            self.strategy.clear()
            return set()
        planned = self.strategy.held(tic)
        fight = reflex_buttons(labels, screen_width, self.enemy_names) if self.reflexes else None
        if fight is not None:
            # Reflexes own aiming and firing; the strategy keeps moving.
            return fight | (planned - TURN_BUTTONS)
        if planned:
            return planned
        return {"TURN_LEFT"} if self.idle == "scan" else set()

    def _drain(self, tic: int) -> None:
        while True:
            try:
                raw = self._inbox.get_nowait()
            except queue.Empty:
                return
            self.handle(raw, tic)

    def handle(self, raw, tic: int) -> dict:
        """Validate, audit and apply one action payload; return the audit entry."""
        text = (
            raw.decode("utf-8", "replace")
            if isinstance(raw, (bytes, bytearray))
            else str(raw)
        )
        entry: dict[str, Any] = {"time": _now_iso(), "client_id": self.client_id, "tic": tic}
        try:
            action = parse_action(text, self.allowed_buttons)
        except ValueError as err:
            entry.update(result="rejected", reason=str(err), payload=text[:500])
            log.warning("Rejected action: %s", err)
        else:
            entry["action"] = action
            if self.paused:
                entry.update(result="skipped", reason="agent paused (emergency stop)")
            else:
                why = self.strategy.apply(action, tic)
                if why:
                    entry.update(result="ignored", reason=why)
                else:
                    entry["result"] = "accepted"
            log.info("Action %s: %s", entry["result"], action)
        self.counts[entry["result"]] += 1
        if self.audit is not None:
            try:
                self.audit(entry)
            except Exception:  # pragma: no cover - audit must never stop the game
                log.exception("Audit hook failed")
        return entry


def action_vector(buttons: set[str]) -> list[int]:
    """ViZDoom's action list for a set of Doom button names."""
    return [1 if name in buttons else 0 for name in DOOM_BUTTONS]


def hud_fields(values: Iterable[float]) -> dict[str, int]:
    """HUD numbers for Home Assistant from the state's game variables."""
    return {name: int(value) for name, value in zip(HUD_FIELDS, values)}


def frame_meta(width: int, height: int, scenario: str) -> dict:
    """Capture metadata, as the PC capture agent sends it, plus the controls."""
    return {
        "client_type": "pc",
        "window_title": "Doom",
        "resolution": f"{width}x{height}",
        "timestamp": int(time.time()),
        "detector": "vizdoom",
        "scenario": scenario,
        "controls": CONTROLS_HINT,
    }


def encode_jpeg(screen, quality: int = 75) -> bytes:
    """JPEG bytes of an RGB screen buffer (height x width x 3)."""
    from PIL import Image

    out = io.BytesIO()
    Image.fromarray(screen).save(out, format="JPEG", quality=quality)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Home Assistant link (the capture-client side)
# ---------------------------------------------------------------------------
class HomeAssistantLink:
    """Publishes frames, meta and HUD numbers to Home Assistant at an interval."""

    def __init__(
        self,
        client,
        client_id: str,
        *,
        interval_s: float = 3.0,
        quality: int = 75,
        scenario: str = "",
        encode: Callable[[Any, int], bytes] = encode_jpeg,
    ) -> None:
        self.client = client
        self.interval_tics = ms_to_tics(interval_s * 1000)
        self.quality = quality
        self.scenario = scenario
        self._encode = encode
        self._image = IMAGE_TOPIC_TEMPLATE.format(client_id=client_id)
        self._meta = META_TOPIC_TEMPLATE.format(client_id=client_id)
        self._hud = HUD_TOPIC_TEMPLATE.format(client_id=client_id)
        self._next_tic = 0
        self.frames_sent = 0

    def new_episode(self) -> None:
        self._next_tic = 0

    def on_tic(self, state, tic: int) -> None:
        if tic < self._next_tic or state is None or state.screen_buffer is None:
            return
        self._next_tic = tic + self.interval_tics
        height, width = state.screen_buffer.shape[:2]
        # Meta first, so Home Assistant knows the game when the frame arrives.
        self.client.publish(self._meta, json.dumps(frame_meta(width, height, self.scenario)))
        self.client.publish(self._image, self._encode(state.screen_buffer, self.quality))
        self.client.publish(self._hud, json.dumps({"fields": hud_fields(state.game_variables)}))
        self.frames_sent += 1


# ---------------------------------------------------------------------------
# Game loop
# ---------------------------------------------------------------------------
@dataclass
class EpisodeResult:
    kills: int
    reward: float
    tics: int
    died: bool


def play_episode(
    game,
    agent: HybridAgent,
    link: HomeAssistantLink | None = None,
    *,
    kill_variable: Any = None,
) -> EpisodeResult:
    """Play one episode to its end and report how it went.

    *kill_variable* (ViZDoom's ``GameVariable.KILLCOUNT``) is read once the
    episode is over, so a kill on the very last tic still counts; without
    it the last state's HUD numbers are used.
    """
    game.new_episode()
    if link is not None:
        link.new_episode()
    width = game.get_screen_width()
    variables: Iterable[float] = ()
    while not game.is_episode_finished():
        state = game.get_state()
        tic = game.get_episode_time()
        if state is not None:
            variables = state.game_variables
        if link is not None:
            link.on_tic(state, tic)
        labels = state.labels if state is not None else ()
        game.make_action(action_vector(agent.step(labels, width, tic)))
    kills = hud_fields(variables).get("kills", 0)
    if kill_variable is not None:
        kills = int(game.get_game_variable(kill_variable))
    return EpisodeResult(
        kills=kills,
        reward=float(game.get_total_reward()),
        tics=int(game.get_episode_time()),
        died=bool(game.is_player_dead()),
    )


def make_game(
    vzd,
    *,
    scenario: str,
    config: str = "",
    show: bool = False,
    realtime: bool = True,
    seed: int | None = None,
):
    """A configured, initialised ViZDoom game.

    The scenario's own config is loaded first; the agent then sets its own
    buttons, game variables and buffers on top, so any scenario works.
    """
    game = vzd.DoomGame()
    path = config or os.path.join(vzd.scenarios_path, f"{scenario}.cfg")
    if not game.load_config(path):
        raise RuntimeError(f"could not load ViZDoom config {path}")
    game.set_available_buttons([getattr(vzd.Button, name) for name in DOOM_BUTTONS])
    game.set_available_game_variables([getattr(vzd.GameVariable, name) for name in GAME_VARIABLES])
    game.set_labels_buffer_enabled(True)
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    game.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
    game.set_window_visible(show)
    # Scenarios like freedoom2 turn on buffers the agent never reads.
    game.set_audio_buffer_enabled(False)
    game.set_automap_buffer_enabled(False)
    game.set_sound_enabled(False)
    # Real time when someone watches or Home Assistant plays along; otherwise
    # as fast as the machine allows (benchmarks).
    game.set_mode(vzd.Mode.ASYNC_PLAYER if realtime else vzd.Mode.PLAYER)
    if seed is not None:
        game.set_seed(seed)
    game.init()
    return game


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
def connect_mqtt(args, agent: HybridAgent):
    """Connect to the broker; actions and commands are handed to *agent*."""
    import paho.mqtt.client as mqtt_client

    action_topic = ACTION_TOPIC_TEMPLATE.format(client_id=args.client_id)
    status_topic = STATUS_TOPIC_TEMPLATE.format(client_id=args.client_id)
    register_topic = REGISTER_TOPIC_TEMPLATE.format(client_id=args.client_id)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION1,
        client_id=f"gaming_assistant_vizdoom_{args.client_id}",
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
        c.publish(
            register_topic,
            json.dumps(
                {
                    "name": f"ViZDoom Agent ({args.client_id})",
                    "type": "vizdoom_agent",
                    "scenario": args.scenario,
                    "reflexes": agent.reflexes,
                    "allowed_buttons": agent.allowed_buttons,
                    "platform": platform.system(),
                }
            ),
            qos=1,
            retain=True,
        )
        c.publish(status_topic, "online", qos=1, retain=True)

    def on_message(c, userdata, msg):
        if msg.topic == COMMAND_TOPIC:
            command = msg.payload.decode("utf-8", "replace").strip().lower()
            if command in ("stop", "pause"):
                agent.pause()
            elif command in ("start", "resume"):
                agent.resume()
        elif msg.topic == action_topic:
            agent.submit(msg.payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()
    return client


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def run(args) -> int:
    try:
        import vizdoom as vzd
    except ImportError:
        log.error("vizdoom is not installed: pip install -r worker/requirements-vizdoom.txt")
        return 1

    audit = make_file_audit(args.audit_log) if args.audit_log and not args.offline else None
    names = (
        frozenset(n.strip().lower() for n in args.enemies.split(",") if n.strip())
        if args.enemies
        else None
    )
    agent = HybridAgent(
        strategy=StrategyInput(
            tap_ms=args.tap_ms, stick_hold_ms=args.hold_ms, max_hold_ms=args.max_hold_ms
        ),
        reflexes=not args.no_reflexes,
        idle=args.idle,
        allowed_buttons=_parse_allow_buttons(args.allow_buttons),
        enemy_names=names,
        client_id=args.client_id,
        audit=audit,
    )
    episodes = args.episodes if args.episodes is not None else (3 if args.offline else 0)
    game = make_game(
        vzd,
        scenario=args.scenario,
        config=args.config,
        show=args.show,
        realtime=args.show or not args.offline,
        seed=args.seed,
    )

    client = link = None
    if not args.offline:
        client = connect_mqtt(args, agent)
        link = HomeAssistantLink(
            client, args.client_id, interval_s=args.interval, quality=args.quality,
            scenario=args.scenario,
        )

    signal.signal(signal.SIGTERM, _raise_interrupt)
    log.info("=== Gaming Assistant – ViZDoom hybrid agent ===")
    log.info("Scenario : %s", args.config or args.scenario)
    log.info("Reflexes : %s, idle: %s", "on" if agent.reflexes else "off", agent.idle)
    log.info(
        "Home Assistant: %s",
        "off (--offline)" if args.offline else f"{args.broker}:{args.port}",
    )

    results: list[EpisodeResult] = []
    try:
        while not episodes or len(results) < episodes:
            result = play_episode(
                game, agent, link, kill_variable=vzd.GameVariable.KILLCOUNT
            )
            results.append(result)
            log.info(
                "Episode %d: %d kills, reward %.1f, %d tics%s",
                len(results), result.kills, result.reward, result.tics,
                ", died" if result.died else "",
            )
    except KeyboardInterrupt:
        log.info("Stopping.")
    finally:
        game.close()
        if client is not None:
            status_topic = STATUS_TOPIC_TEMPLATE.format(client_id=args.client_id)
            client.publish(status_topic, "offline", qos=1, retain=True)
            client.disconnect()
            client.loop_stop()

    if results:
        log.info(
            "%d episodes: %.1f kills and reward %.1f on average, died %d times; actions: %s",
            len(results),
            sum(r.kills for r in results) / len(results),
            sum(r.reward for r in results) / len(results),
            sum(r.died for r in results),
            agent.counts,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gaming Assistant – ViZDoom hybrid agent (reflexes + Home Assistant)",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker IP/hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username (optional)")
    parser.add_argument("--password", default="", help="MQTT password (optional)")
    parser.add_argument("--client-id", default="vizdoom", help="Client ID in Home Assistant")
    parser.add_argument(
        "--scenario", default="deathmatch",
        help="Bundled ViZDoom scenario, e.g. deathmatch, defend_the_center, basic",
    )
    parser.add_argument("--config", default="", help="Path to your own ViZDoom .cfg instead")
    parser.add_argument("--offline", action="store_true", help="Reflexes only, no Home Assistant")
    parser.add_argument("--show", action="store_true", help="Show the game window")
    parser.add_argument(
        "--episodes", type=int, default=None,
        help="Episodes to play (default: 3 offline, endless with Home Assistant)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Game seed for repeatable runs")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between frames to HA")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality of the frames")
    parser.add_argument("--no-reflexes", action="store_true", help="Let only Home Assistant play")
    parser.add_argument(
        "--idle", choices=("scan", "still"), default="scan",
        help="With no enemy and no action: turn to look around (scan) or stand still",
    )
    parser.add_argument(
        "--enemies", default="",
        help="Comma-separated actor names to shoot at (default: every monster)",
    )
    parser.add_argument(
        "--allow-buttons", default="all",
        help="Comma-separated whitelist of controller buttons HA may use. Default 'all'.",
    )
    parser.add_argument("--tap-ms", type=int, default=80, help="Default tap_button duration")
    parser.add_argument("--hold-ms", type=int, default=1500, help="How long a stick move lasts")
    parser.add_argument(
        "--max-hold-ms", type=int, default=3000, help="Longest any action is held",
    )
    parser.add_argument(
        "--audit-log", default="vizdoom_agent_audit.log",
        help="JSON-lines audit log of HA's actions ('' to disable)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
