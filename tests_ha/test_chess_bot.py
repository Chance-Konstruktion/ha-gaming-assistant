"""The chess bot (GA-110) against a real Home Assistant.

The unit suite drives the bot and the coordinator with stubs; this test goes
through the real service registry, event bus and entity platforms: the bot is
configured by service or by its entities, a board arrives via
``analyze_board``, and the reply shows up as an event, an MQTT message and
sensor attributes.
"""

from __future__ import annotations

import json

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gaming_assistant.const import (
    CHESS_START_FEN,
    DOMAIN,
    EVENT_CHESS_MOVE,
    MQTT_BOARD_COMMAND_TOPIC,
)
from ha_helpers import entity_id, published

# Black to move after 1.e4; White to move after 1.e4 e5.
AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"


def _bot_moves(hass: HomeAssistant) -> list:
    events = []
    hass.bus.async_listen(EVENT_CHESS_MOVE, lambda e: events.append(e.data))
    return events


async def _board(hass: HomeAssistant, fen: str, client_id: str = "cam1") -> None:
    await hass.services.async_call(
        DOMAIN, "analyze_board", {"fen": fen, "client_id": client_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_bot_answers_a_board(hass: HomeAssistant, integration, mqtt_mock) -> None:
    moves = _bot_moves(hass)
    await hass.services.async_call(
        DOMAIN, "set_chess_bot", {"enabled": True, "color": "black", "strength": 2},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "switch", "gaming_assistant_chess_bot")).state == "on"
    color = hass.states.get(entity_id(hass, "select", "gaming_assistant_chess_bot_color"))
    assert color.state == "black"
    strength = hass.states.get(entity_id(hass, "number", "gaming_assistant_chess_bot_strength"))
    assert float(strength.state) == 2

    await _board(hass, AFTER_E4)

    assert len(moves) == 1
    move = moves[0]
    assert (move["kind"], move["client_id"], move["bot_color"]) == ("move", "cam1", "black")
    assert move["speech"].startswith("I ")  # Home Assistant's language is English here
    [payload] = published(mqtt_mock, "gaming_assistant/cam1/chess_move")
    assert json.loads(payload)["uci"] == move["uci"]
    chess = hass.states.get(entity_id(hass, "sensor", "gaming_assistant_chess"))
    assert chess.attributes["bot_move"] == move["san"]
    assert chess.attributes["bot_speech"] == move["speech"]

    # The same position again (a worker repeating itself) is answered once.
    await _board(hass, AFTER_E4)
    assert len(moves) == 1


async def test_new_game_resets_workers_and_white_opens(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    hass.config.language = "de"
    moves = _bot_moves(hass)

    await hass.services.async_call(
        DOMAIN, "set_chess_bot", {"enabled": True, "color": "white", "new_game": True},
        blocking=True,
    )
    await hass.async_block_till_done()

    resets = published(mqtt_mock, MQTT_BOARD_COMMAND_TOPIC)
    assert [json.loads(p) for p in resets] == [{"command": "reset"}]
    assert len(moves) == 1
    assert moves[0]["fen"] == CHESS_START_FEN
    assert moves[0]["speech"].startswith("Ich ")
    assert published(mqtt_mock, "gaming_assistant/chess_bot/chess_move")


async def test_entities_drive_the_bot(hass: HomeAssistant, integration) -> None:
    _, coordinator = integration
    moves = _bot_moves(hass)
    switch = entity_id(hass, "switch", "gaming_assistant_chess_bot")

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": entity_id(hass, "select", "gaming_assistant_chess_bot_color"),
         "option": "white"},
        blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": entity_id(hass, "number", "gaming_assistant_chess_bot_strength"),
         "value": 1},
        blocking=True,
    )
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert coordinator.chess_bot_enabled
    assert (coordinator.chess_bot_color, coordinator.chess_bot_strength) == ("white", 1)

    await _board(hass, CHESS_START_FEN)
    assert len(moves) == 1

    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await _board(hass, AFTER_E4_E5)
    assert len(moves) == 1  # switched off: White to move, but no answer


async def test_bad_input_is_rejected(hass: HomeAssistant, integration) -> None:
    _, coordinator = integration
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "set_chess_bot", {"enabled": True, "color": "green"}, blocking=True
        )
    assert not coordinator.chess_bot_enabled
