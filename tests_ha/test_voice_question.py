"""Voice questions with the current screen (GA-IMV) against a real Home Assistant.

A question goes through Home Assistant's own conversation API to the Gaming
Assistant agent, the way Assist delivers it. The LLM backend is the only thing
patched: the test checks that it receives the latest frame, the game and the
last tip along with the question.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant

from ha_helpers import entity_id


async def _ask(hass: HomeAssistant, entry, text: str):
    agent = entity_id(hass, "conversation", f"{entry.entry_id}_conversation")
    return await conversation.async_converse(hass, text, None, Context(), agent_id=agent)


async def test_voice_question_sees_the_current_screen(hass: HomeAssistant, integration) -> None:
    entry, coordinator = integration
    coordinator._client_metadata["rig1"] = {"client_type": "pc", "window_title": "Doom"}
    coordinator._record_last_image("rig1", b"live-frame")
    coordinator._tip = "Circle-strafe the Cyberdemon."
    backend = coordinator._image_processor._backend
    answer = SimpleNamespace(text="Aim for its rocket launcher arm.")

    with patch.object(backend, "generate", AsyncMock(return_value=answer)) as generate:
        result = await _ask(hass, entry, "How do I beat this boss?")

    assert result.response.speech["plain"]["speech"] == "Aim for its rocket launcher arm."
    prompt, image_b64 = generate.await_args.args[:2]
    assert base64.b64decode(image_b64) == b"live-frame"
    assert "Doom" in prompt
    assert "screen right now" in prompt
    assert "Circle-strafe the Cyberdemon." in prompt
    assert "How do I beat this boss?" in prompt


async def test_without_a_frame_the_question_is_text_only(
    hass: HomeAssistant, integration
) -> None:
    entry, coordinator = integration
    backend = coordinator._image_processor._backend
    answer = SimpleNamespace(text="Save often.")

    with patch.object(backend, "generate", AsyncMock()) as generate, patch.object(
        backend, "generate_text", AsyncMock(return_value=answer)
    ) as generate_text:
        result = await _ask(hass, entry, "Any general advice?")

    assert result.response.speech["plain"]["speech"] == "Save often."
    generate.assert_not_awaited()
    assert "screen right now" not in generate_text.await_args.args[0]
