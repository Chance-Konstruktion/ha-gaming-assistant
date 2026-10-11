"""
Unit tests for the ViZDoom hybrid agent (worker/vizdoom_agent.py, GA-111).

None of these need ViZDoom: the reflexes and the action mapping are pure
functions, the game loop runs against a small fake arena, and the ViZDoom
setup is checked against a stand-in module.
"""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import numpy as np

from worker.vizdoom_agent import (
    CONTROLS_HINT,
    DOOM_BUTTONS,
    HybridAgent,
    HomeAssistantLink,
    StrategyInput,
    action_vector,
    encode_jpeg,
    frame_meta,
    hud_fields,
    is_enemy,
    main,
    make_game,
    ms_to_tics,
    pick_target,
    play_episode,
    reflex_buttons,
)

WIDTH = 640


def _label(name="ZombieMan", category="Monster", x=310, width=20, height=50):
    return SimpleNamespace(
        object_name=name, object_category=category, x=x, y=200, width=width, height=height
    )


def _action(**fields):
    return json.dumps(fields)


# ===========================================================================
# Reflexes
# ===========================================================================

class TestEnemies(unittest.TestCase):
    def test_category_decides(self):
        self.assertTrue(is_enemy(_label()))
        self.assertFalse(is_enemy(_label("Medikit", "Health")))
        self.assertFalse(is_enemy(_label("DoomPlayer", "Self")))

    def test_corpses_never_count(self):
        # ViZDoom renames dead actors to "Dead<Class>" (category "Gore").
        self.assertFalse(is_enemy(_label("DeadZombieMan", "Gore")))
        self.assertFalse(is_enemy(_label("DeadZombieMan", "Monster")))

    def test_older_vizdoom_without_categories_uses_names(self):
        self.assertTrue(is_enemy(_label("DoomImp", None)))
        self.assertFalse(is_enemy(_label("Clip", None)))

    def test_own_list_overrides_categories(self):
        names = frozenset({"cacodemon"})
        self.assertTrue(is_enemy(_label("Cacodemon"), names))
        self.assertFalse(is_enemy(_label("ZombieMan"), names))

    def test_biggest_enemy_is_the_target(self):
        far = _label(x=100, width=10, height=25)
        near = _label("DoomImp", x=400, width=40, height=80)
        item = _label("Medikit", "Health", x=300, width=90, height=90)
        self.assertIs(pick_target([far, item, near]), near)
        self.assertIsNone(pick_target([item]))
        self.assertIsNone(pick_target(None))


class TestReflexButtons(unittest.TestCase):
    def test_no_enemy_no_reflex(self):
        self.assertIsNone(reflex_buttons([], WIDTH))

    def test_turns_toward_and_fires_when_on_target(self):
        self.assertEqual(reflex_buttons([_label(x=500)], WIDTH), {"TURN_RIGHT"})
        self.assertEqual(reflex_buttons([_label(x=50)], WIDTH), {"TURN_LEFT"})
        self.assertEqual(reflex_buttons([_label(x=310, width=20)], WIDTH), {"ATTACK"})

    def test_far_enemy_gets_a_little_slack(self):
        # 2 px wide, centre 3 px right of the crosshair: close enough.
        self.assertEqual(reflex_buttons([_label(x=322, width=2)], WIDTH), {"ATTACK"})
        self.assertEqual(reflex_buttons([_label(x=330, width=2)], WIDTH), {"TURN_RIGHT"})


# ===========================================================================
# Strategy input (Home Assistant's actions)
# ===========================================================================

class TestStrategyInput(unittest.TestCase):
    def setUp(self):
        self.s = StrategyInput(tap_ms=80, stick_hold_ms=1000, max_hold_ms=2000)

    def test_tap_holds_for_its_duration(self):
        self.s.apply({"action": "tap_button", "button": "RT"}, tic=10)
        self.assertEqual(self.s.held(10), {"ATTACK"})
        self.assertEqual(self.s.held(10 + ms_to_tics(80)), set())
        self.s.apply({"action": "tap_button", "button": "A", "duration_ms": 500}, tic=0)
        self.assertEqual(self.s.held(17), {"USE"})
        self.assertEqual(self.s.held(18), set())

    def test_left_stick_walks_and_strafes(self):
        self.s.apply({"action": "move_stick", "stick": "left", "x": -0.8, "y": 0.9}, tic=0)
        self.assertEqual(self.s.held(0), {"MOVE_FORWARD", "MOVE_LEFT"})
        self.assertEqual(self.s.held(34), {"MOVE_FORWARD", "MOVE_LEFT"})
        self.assertEqual(self.s.held(35), set())  # 1 s = 35 tics

    def test_stick_back_to_centre_stops(self):
        self.s.apply({"action": "move_stick", "stick": "left", "x": 0.0, "y": 1.0}, tic=0)
        self.s.apply({"action": "move_stick", "stick": "left", "x": 0.0, "y": 0.1}, tic=5)
        self.assertEqual(self.s.held(5), set())

    def test_right_stick_turns(self):
        self.s.apply({"action": "move_stick", "stick": "right", "x": 1.0, "y": 0.5}, tic=0)
        self.assertEqual(self.s.held(0), {"TURN_RIGHT"})

    def test_weapon_switch_is_one_press(self):
        self.s.apply({"action": "tap_button", "button": "RB", "duration_ms": 1000}, tic=3)
        self.assertEqual(self.s.held(3), {"SELECT_NEXT_WEAPON"})
        self.assertEqual(self.s.held(4), set())

    def test_press_is_capped_and_release_ends_it(self):
        self.s.apply({"action": "press_button", "button": "LT"}, tic=0)
        self.assertEqual(self.s.held(69), {"SPEED"})
        self.assertEqual(self.s.held(70), set())  # max 2 s
        self.s.apply({"action": "press_button", "button": "RT"}, tic=100)
        self.s.apply({"action": "release_button", "button": "RT"}, tic=101)
        self.assertEqual(self.s.held(101), set())

    def test_buttons_without_a_job_are_ignored(self):
        for button in ("B", "START", "BACK"):
            with self.subTest(button=button):
                why = self.s.apply({"action": "tap_button", "button": button}, tic=0)
                self.assertIn("no use in Doom", why)
        self.assertIsNone(self.s.apply({"action": "wait", "duration_ms": 100}, tic=0))
        self.assertIsNone(self.s.apply({"action": "no_op"}, tic=0))
        self.assertEqual(self.s.held(0), set())


# ===========================================================================
# The hybrid
# ===========================================================================

class TestHybridAgent(unittest.TestCase):
    def setUp(self):
        self.entries = []
        self.agent = HybridAgent(audit=self.entries.append, client_id="doom")

    def test_reflexes_aim_while_the_strategy_keeps_walking(self):
        self.agent.submit(_action(action="move_stick", stick="left", x=0.0, y=1.0))
        self.agent.submit(_action(action="move_stick", stick="right", x=-1.0, y=0.0))
        buttons = self.agent.step([_label(x=500)], WIDTH, tic=0)
        # The strategy's turn gives way to the aim; its walking stays.
        self.assertEqual(buttons, {"TURN_RIGHT", "MOVE_FORWARD"})

    def test_strategy_steers_when_no_enemy_is_in_view(self):
        self.agent.submit(_action(action="tap_button", button="A", duration_ms=200))
        self.assertEqual(self.agent.step([], WIDTH, tic=0), {"USE"})

    def test_idle_scan_or_still(self):
        self.assertEqual(self.agent.step([], WIDTH, tic=0), {"TURN_LEFT"})
        still = HybridAgent(idle="still")
        self.assertEqual(still.step([], WIDTH, tic=0), set())

    def test_without_reflexes_only_the_strategy_plays(self):
        agent = HybridAgent(reflexes=False, idle="still")
        self.assertEqual(agent.step([_label(x=310)], WIDTH, tic=0), set())

    def test_actions_are_validated_and_audited(self):
        self.agent.submit(b"not json")
        self.agent.submit(_action(action="tap_button", button="B"))
        self.agent.submit(_action(action="tap_button", button="RT"))
        self.agent.step([], WIDTH, tic=0)
        self.assertEqual([e["result"] for e in self.entries], ["rejected", "ignored", "accepted"])
        self.assertEqual(self.agent.counts["accepted"], 1)
        self.assertTrue(all(e["client_id"] == "doom" and e["tic"] == 0 for e in self.entries))

    def test_whitelist_applies(self):
        agent = HybridAgent(allowed_buttons=["A"], audit=self.entries.append)
        agent.submit(_action(action="tap_button", button="RT"))
        agent.step([], WIDTH, tic=0)
        self.assertEqual(self.entries[0]["result"], "rejected")
        self.assertIn("not whitelisted", self.entries[0]["reason"])

    def test_emergency_stop_means_no_input_at_all(self):
        self.agent.submit(_action(action="press_button", button="RT"))
        self.agent.step([], WIDTH, tic=0)
        self.agent.pause()
        self.agent.submit(_action(action="tap_button", button="A"))
        self.assertEqual(self.agent.step([_label(x=310)], WIDTH, tic=1), set())
        self.assertEqual(self.entries[-1]["result"], "skipped")
        self.agent.resume()
        # The held fire button was dropped by the stop.
        self.assertEqual(self.agent.step([], WIDTH, tic=2), {"TURN_LEFT"})


# ===========================================================================
# Helpers
# ===========================================================================

class TestHelpers(unittest.TestCase):
    def test_action_vector_follows_the_button_order(self):
        vector = action_vector({"ATTACK", "MOVE_FORWARD"})
        self.assertEqual(len(vector), len(DOOM_BUTTONS))
        self.assertEqual(
            [name for name, on in zip(DOOM_BUTTONS, vector) if on], ["MOVE_FORWARD", "ATTACK"]
        )

    def test_ms_to_tics(self):
        self.assertEqual(ms_to_tics(1000), 35)
        self.assertEqual(ms_to_tics(0), 1)
        self.assertEqual(ms_to_tics(80), 3)

    def test_hud_and_meta(self):
        self.assertEqual(
            hud_fields(np.array([87.0, 25.0, 40.0, 3.0])),
            {"health": 87, "armor": 25, "ammo": 40, "kills": 3},
        )
        meta = frame_meta(640, 480, "deathmatch")
        self.assertEqual(meta["window_title"], "Doom")
        self.assertEqual(meta["resolution"], "640x480")
        self.assertEqual(meta["controls"], CONTROLS_HINT)

    def test_encode_jpeg(self):
        jpeg = encode_jpeg(np.zeros((48, 64, 3), dtype=np.uint8))
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))


# ===========================================================================
# Home Assistant link
# ===========================================================================

def _state(kills=0, labels=()):
    return SimpleNamespace(
        labels=list(labels),
        game_variables=[100.0, 0.0, 50.0, float(kills)],
        screen_buffer=np.zeros((480, 640, 3), dtype=np.uint8),
    )


class TestHomeAssistantLink(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.link = HomeAssistantLink(
            self.client, "doom", interval_s=1.0, scenario="basic",
            encode=lambda screen, quality: b"jpeg",
        )

    def test_meta_then_frame_then_hud(self):
        self.link.on_tic(_state(kills=2), tic=0)
        topics = [c.args[0] for c in self.client.publish.call_args_list]
        self.assertEqual(
            topics,
            ["gaming_assistant/doom/meta", "gaming_assistant/doom/image", "gaming_assistant/doom/hud"],
        )
        self.assertEqual(self.client.publish.call_args_list[1], call("gaming_assistant/doom/image", b"jpeg"))
        hud = json.loads(self.client.publish.call_args_list[2].args[1])
        self.assertEqual(hud["fields"]["kills"], 2)

    def test_interval_and_new_episode(self):
        self.link.on_tic(_state(), tic=0)
        self.link.on_tic(_state(), tic=34)  # within the 1 s interval
        self.link.on_tic(_state(), tic=35)
        self.assertEqual(self.link.frames_sent, 2)
        self.link.new_episode()
        self.link.on_tic(_state(), tic=0)
        self.assertEqual(self.link.frames_sent, 3)
        self.link.on_tic(None, tic=200)
        self.assertEqual(self.link.frames_sent, 3)


# ===========================================================================
# Game loop against a fake arena
# ===========================================================================

class FakeGame:
    """One zombie in front of the player; turning moves it across the screen."""

    def __init__(self, enemy_x=520, max_tics=80, turn_px=20):
        self.start_x, self.max_tics, self.turn_px = enemy_x, max_tics, turn_px
        self.pressed = []

    def new_episode(self):
        self.t, self.enemy_x, self.kills = 0, self.start_x, 0

    def get_screen_width(self):
        return WIDTH

    def is_episode_finished(self):
        return self.t >= self.max_tics or self.kills > 0

    def get_state(self):
        if self.is_episode_finished():
            return None
        return _state(self.kills, [_label(x=self.enemy_x - 10, width=20)])

    def get_episode_time(self):
        return self.t

    def make_action(self, vector):
        pressed = {name for name, on in zip(DOOM_BUTTONS, vector) if on}
        self.pressed.append(pressed)
        if "TURN_RIGHT" in pressed:
            self.enemy_x -= self.turn_px
        if "TURN_LEFT" in pressed:
            self.enemy_x += self.turn_px
        if "ATTACK" in pressed and abs(self.enemy_x - WIDTH / 2) <= 10:
            self.kills += 1
        self.t += 1
        return float(self.kills)

    def get_game_variable(self, variable):
        assert variable == "KILLCOUNT"
        return float(self.kills)

    def get_total_reward(self):
        return float(self.kills)

    def is_player_dead(self):
        return False


class TestPlayEpisode(unittest.TestCase):
    def test_reflexes_find_and_kill_the_enemy(self):
        game = FakeGame()
        result = play_episode(game, HybridAgent(), kill_variable="KILLCOUNT")
        self.assertEqual(result.kills, 1)  # the kill on the last tic counts
        self.assertEqual(result.reward, 1.0)
        self.assertFalse(result.died)
        self.assertEqual(game.pressed[0], {"TURN_RIGHT"})
        self.assertEqual(game.pressed[-1], {"ATTACK"})

    def test_without_reflexes_nothing_happens(self):
        game = FakeGame(max_tics=20)
        result = play_episode(game, HybridAgent(reflexes=False, idle="still"))
        self.assertEqual((result.kills, result.tics), (0, 20))

    def test_frames_go_to_home_assistant(self):
        link = MagicMock()
        play_episode(FakeGame(max_tics=5), HybridAgent(reflexes=False), link)
        link.new_episode.assert_called_once()
        self.assertEqual(link.on_tic.call_count, 5)


# ===========================================================================
# ViZDoom setup and entry point
# ===========================================================================

class TestMakeGame(unittest.TestCase):
    def _vzd(self, loads=True):
        vzd = MagicMock()
        vzd.scenarios_path = "/scenarios"
        vzd.DoomGame.return_value.load_config.return_value = loads
        return vzd

    def test_configures_buttons_buffers_and_mode(self):
        vzd = self._vzd()
        game = make_game(vzd, scenario="basic", realtime=False, seed=7)
        game.load_config.assert_called_once()
        self.assertTrue(game.load_config.call_args.args[0].endswith("basic.cfg"))
        buttons = game.set_available_buttons.call_args.args[0]
        self.assertEqual(buttons, [getattr(vzd.Button, name) for name in DOOM_BUTTONS])
        game.set_labels_buffer_enabled.assert_called_once_with(True)
        game.set_mode.assert_called_once_with(vzd.Mode.PLAYER)
        game.set_seed.assert_called_once_with(7)
        game.init.assert_called_once()

    def test_realtime_and_own_config(self):
        vzd = self._vzd()
        game = make_game(vzd, scenario="basic", config="my.cfg", show=True)
        game.load_config.assert_called_once_with("my.cfg")
        game.set_mode.assert_called_once_with(vzd.Mode.ASYNC_PLAYER)
        game.set_window_visible.assert_called_once_with(True)

    def test_broken_config_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            make_game(self._vzd(loads=False), scenario="nope")

    def test_main_without_vizdoom(self):
        with patch.dict(sys.modules, {"vizdoom": None}):
            self.assertEqual(main(["--offline"]), 1)


if __name__ == "__main__":
    unittest.main()
