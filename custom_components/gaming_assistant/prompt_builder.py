"""Dynamic prompt construction for Gaming Assistant."""
from __future__ import annotations

import re

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

        # 2b. Tabletop context
        if client_type == "tabletop":
            parts.append(_TABLETOP_CONTEXT_COMPACT if compact else _TABLETOP_CONTEXT)

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
