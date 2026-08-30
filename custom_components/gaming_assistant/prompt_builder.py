"""Dynamic prompt construction for Gaming Assistant."""
from __future__ import annotations

import json
import re

# Extra context injected when the source is a console game captured via camera.
_CONSOLE_CONTEXT = (
    "The game is running on a console or handheld (e.g. Switch, Wii, "
    "PlayStation, Dreamcast, Game Boy) and is captured by a camera pointed "
    "at the screen. Analyze the on-screen game state: HUD, health bars, "
    "map, inventory, menus, etc. Ignore any glare, bezels, or camera "
    "artifacts — focus on the game content shown on screen."
)

_CONSOLE_CONTEXT_COMPACT = (
    "Console/handheld game captured by camera on screen. "
    "Analyze on-screen HUD, menus, game state. Ignore glare/bezels."
)

# Extra context injected when the source is a physical tabletop game.
_TABLETOP_CONTEXT = (
    "The game is being played physically on a real table, captured by a camera. "
    "Analyze what you see on the board/table: pieces, cards, tokens, dice, etc. "
    "Give tactical advice about the current visible game state. "
    "If the image is unclear or partially obscured, say what you can identify "
    "and base your tip on that."
)

_TABLETOP_CONTEXT_COMPACT = (
    "Physical board game on a table, captured by camera. "
    "Analyze visible pieces/cards/tokens. Give tactical advice."
)

# System role per assistant mode.
_MODE_ROLES = {
    "coach": (
        "You are a helpful gaming coach. "
        "Your job is to observe the game and give the player tips, "
        "strategies, and advice to help them improve and win."
    ),
    "coplay": (
        "You are a cooperative teammate playing alongside the player. "
        "Analyze the current game state and suggest your next collaborative move. "
        "Think as a partner: coordinate strategy, warn about threats, "
        "and propose combined tactics. Speak as 'we' — you are on the same team."
    ),
    "opponent": (
        "You are the player's opponent in this game. "
        "Analyze the board from YOUR perspective and announce your next move. "
        "Play competitively but fairly. State your move clearly "
        "(e.g. 'I move my knight to f3' or 'I play the red 7'). "
        "Briefly explain your reasoning. Play to win."
    ),
    "analyst": (
        "You are a neutral game analyst and commentator. "
        "Do NOT take sides or give strategic advice to either player. "
        "Objectively describe the current game state: who has the advantage, "
        "what the key positions are, and what critical decisions lie ahead. "
        "Speak like a sports commentator providing expert analysis."
    ),
}

# Compact roles for small models (3B etc.)
_MODE_ROLES_COMPACT = {
    "coach": "You are a gaming coach. Give tips to help the player win.",
    "coplay": "You are the player's teammate. Suggest your next joint move.",
    "opponent": "You are the opponent. Announce your next move. Play to win.",
    "analyst": "You are a neutral analyst. Describe the game state objectively.",
}

# Tip instruction per mode (replaces the default "give ONE tip" instruction).
_MODE_INSTRUCTIONS = {
    "coach": (
        "Give exactly ONE short, specific, actionable tip. "
        "No introduction, no emojis, just the tip."
    ),
    "coplay": (
        "Suggest exactly ONE concrete move or action we should take together. "
        "Be specific about what to do and why. No introduction, no emojis."
    ),
    "opponent": (
        "Announce your ONE next move. Be specific and clear. "
        "Briefly explain your reasoning in one sentence. No emojis."
    ),
    "analyst": (
        "Give a brief, neutral analysis of the current game state. "
        "Who has the advantage and why? What is the critical factor right now? "
        "Keep it concise — two to three sentences max. No emojis."
    ),
}

_MODE_INSTRUCTIONS_COMPACT = {
    "coach": "Give ONE short tip. No intro, no emojis.",
    "coplay": "Suggest ONE move we should do together. No emojis.",
    "opponent": "Announce your ONE move. Brief reasoning. No emojis.",
    "analyst": "Brief neutral analysis. Who has advantage? No emojis.",
}

# Regex to detect small model names (1B-4B parameter models)
_SMALL_MODEL_PATTERN = re.compile(r"[:\-_]([1-4])b", re.IGNORECASE)


class PromptBuilder:
    """Builds the final prompt from all components."""

    @staticmethod
    def is_small_model(model: str) -> bool:
        """Return True if the model is a small model (1B-4B parameters)."""
        return bool(_SMALL_MODEL_PATTERN.search(model))

    @staticmethod
    def build(
        game: str = "",
        spoiler_block: str = "",
        history_context: str = "",
        prompt_pack: dict | None = None,
        client_type: str = "pc",
        user_question: str = "",
        assistant_mode: str = "coach",
        language: str = "",
        compact: bool = False,
        state_context: str = "",
    ) -> str:
        """Assemble the full prompt in the correct order.

        When *compact* is True (recommended for small models like 3B),
        prompts are significantly shorter to fit within limited context
        and improve instruction-following.
        """
        parts: list[str] = []

        roles = _MODE_ROLES_COMPACT if compact else _MODE_ROLES
        instructions = _MODE_INSTRUCTIONS_COMPACT if compact else _MODE_INSTRUCTIONS

        # 0. Language instruction (if set)
        if language:
            if compact:
                parts.append(f"Respond in {language}.")
            else:
                parts.append(f"IMPORTANT: Always respond in {language}.")

        # 1. System role (mode-dependent)
        parts.append(roles.get(assistant_mode, roles["coach"]))

        # 2. Game context
        if game:
            parts.append(f"Game: {game} ({client_type})." if compact
                         else f"The player is playing {game} on {client_type}.")

        # 2b. Source-specific context
        if client_type == "tabletop":
            parts.append(_TABLETOP_CONTEXT_COMPACT if compact else _TABLETOP_CONTEXT)
        elif client_type == "console":
            parts.append(_CONSOLE_CONTEXT_COMPACT if compact else _CONSOLE_CONTEXT)

        # 3. Prompt pack system prompt
        if prompt_pack:
            if prompt_pack.get("system_prompt"):
                parts.append(prompt_pack["system_prompt"])
            if not compact and prompt_pack.get("additional_context"):
                parts.append(prompt_pack["additional_context"])

        # 4. Spoiler rules
        if spoiler_block:
            parts.append(spoiler_block)

        # 5. History context (limited for compact mode)
        if history_context:
            if compact:
                # Only include the last 2 tips for small models
                lines = history_context.strip().split("\n")
                parts.append("\n".join(lines[-2:]) if len(lines) > 2 else history_context)
            else:
                parts.append(history_context)

        # 5b. Game state context (from state engine)
        if state_context:
            parts.append(state_context)

        # 6. User question (ask-mode) or mode-specific instruction
        if user_question:
            parts.append(f"The player asks: {user_question}")
            if not compact:
                parts.append("Answer the question directly and concisely.")
        else:
            parts.append(
                instructions.get(assistant_mode, instructions["coach"])
            )

        # 7. Anti-repetition
        if history_context:
            if compact:
                parts.append("Give a NEW tip, not a repeat.")
            else:
                parts.append("Do NOT repeat any previous tips. Give a NEW insight.")

        return "\n\n".join(parts)

    # -- Phase 5.1: Action mode (structured JSON output) ---------------------

    ACTION_SCHEMA: dict = {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "press_button",
                    "release_button",
                    "tap_button",
                    "move_stick",
                    "wait",
                    "no_op",
                ],
            },
            "button": {
                "type": "string",
                "description": "Xbox button name: A, B, X, Y, LB, RB, LT, RT, DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT, START, BACK",
            },
            "stick": {"type": "string", "enum": ["left", "right"]},
            "x": {"type": "number", "minimum": -1.0, "maximum": 1.0},
            "y": {"type": "number", "minimum": -1.0, "maximum": 1.0},
            "duration_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
            "reason": {"type": "string"},
        },
    }

    _ACTION_SYSTEM = (
        "You are controlling a virtual game controller (Xbox layout). "
        "Respond with ONE JSON object describing your single next action. "
        "Do NOT output prose or markdown – only raw JSON. "
        "Valid actions: press_button, release_button, tap_button, "
        "move_stick, wait, no_op. "
        "Include a short 'reason' field explaining the choice."
    )

    _ACTION_SYSTEM_COMPACT = (
        "Control a game controller. Output ONE JSON object only. "
        "Actions: press_button|tap_button|move_stick|wait|no_op. "
        "Fields: action, button?, stick?, x?, y?, duration_ms?, reason."
    )

    @classmethod
    def build_action(
        cls,
        game: str = "",
        allowed_buttons: list[str] | None = None,
        history_context: str = "",
        state_context: str = "",
        compact: bool = False,
    ) -> str:
        """Build a prompt that asks the LLM for a structured controller action.

        The caller is expected to validate the resulting JSON against
        :attr:`ACTION_SCHEMA` *before* forwarding it to any executor.
        """
        parts: list[str] = []
        parts.append(cls._ACTION_SYSTEM_COMPACT if compact else cls._ACTION_SYSTEM)

        if game:
            parts.append(f"Game: {game}.")

        if allowed_buttons:
            allowed = ", ".join(sorted(set(allowed_buttons)))
            parts.append(
                f"Only these buttons are permitted: {allowed}. "
                "Refuse with no_op if no permitted action makes sense."
            )

        if state_context:
            parts.append(state_context)

        if history_context:
            parts.append(history_context)

        parts.append("Schema:\n" + json.dumps(cls.ACTION_SCHEMA, indent=2))
        parts.append(
            'Example: {"action":"tap_button","button":"A","duration_ms":80,'
            '"reason":"confirm menu prompt"}'
        )
        parts.append("Return ONLY the JSON object.")

        return "\n\n".join(parts)

    @staticmethod
    def parse_action(text: str, allowed_buttons: list[str] | None = None) -> dict:
        """Parse an LLM response into a validated action dict.

        Raises ``ValueError`` when the output is missing, not JSON, or
        violates the schema / whitelist. Unknown fields are stripped.
        """
        if not text or not text.strip():
            raise ValueError("empty action response")

        # Strip ```json fences if the model added them anyway.
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as err:
            raise ValueError(f"not valid JSON: {err}") from err

        if not isinstance(payload, dict):
            raise ValueError("action must be a JSON object")

        allowed_actions = set(
            PromptBuilder.ACTION_SCHEMA["properties"]["action"]["enum"]
        )
        action = payload.get("action")
        if action not in allowed_actions:
            raise ValueError(f"unknown action {action!r}")

        if action in ("press_button", "release_button", "tap_button"):
            button = payload.get("button")
            if not isinstance(button, str) or not button:
                raise ValueError(f"{action} requires a 'button' string")
            button_up = button.upper()
            if allowed_buttons and button_up not in {
                b.upper() for b in allowed_buttons
            }:
                raise ValueError(f"button '{button}' is not whitelisted")
            payload["button"] = button_up

        if action == "move_stick":
            stick = payload.get("stick")
            if stick not in ("left", "right"):
                raise ValueError("move_stick requires stick in {left, right}")
            for axis in ("x", "y"):
                val = payload.get(axis, 0.0)
                if not isinstance(val, (int, float)) or not -1.0 <= val <= 1.0:
                    raise ValueError(
                        f"move_stick axis '{axis}' must be in [-1.0, 1.0]"
                    )

        duration = payload.get("duration_ms")
        if duration is not None:
            if not isinstance(duration, int) or duration < 0 or duration > 5000:
                raise ValueError("duration_ms must be an int in [0, 5000]")

        # Drop unknown keys to keep the downstream executor minimal.
        allowed_keys = set(PromptBuilder.ACTION_SCHEMA["properties"])
        return {k: v for k, v in payload.items() if k in allowed_keys}

    @staticmethod
    def build_summary(
        game: str,
        tips: list[str],
        language: str = "",
        compact: bool = False,
    ) -> str:
        """Build a prompt for summarizing a gaming session."""
        parts: list[str] = []

        if language:
            parts.append(
                f"Respond in {language}." if compact
                else f"IMPORTANT: Always respond in {language}."
            )

        if compact:
            parts.append(
                f"Summarize this {game} session in 2-3 sentences. "
                "Focus on patterns and improvement areas."
            )
        else:
            parts.append(
                f"Summarize the key insights from this {game} gaming session "
                "in 2-3 concise sentences. Focus on recurring patterns, "
                "good decisions, and areas for improvement."
            )

        tip_list = "\n".join(f"- {t}" for t in tips)
        parts.append(f"Tips given during the session:\n{tip_list}")

        if compact:
            parts.append("Be brief and actionable.")
        else:
            parts.append(
                "Create a helpful, encouraging summary the player can learn from."
            )

        return "\n\n".join(parts)
