"""Dynamic prompt construction for Gaming Assistant."""
from __future__ import annotations


# Extra context injected when the source is a physical tabletop game.
_TABLETOP_CONTEXT = (
    "The game is being played physically on a real table, captured by a camera. "
    "Analyze what you see on the board/table: pieces, cards, tokens, dice, etc. "
    "Give tactical advice about the current visible game state. "
    "If the image is unclear or partially obscured, say what you can identify "
    "and base your tip on that."
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


class PromptBuilder:
    """Builds the final prompt from all components."""

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
    ) -> str:
        """Assemble the full prompt in the correct order."""
        parts: list[str] = []

        # 0. Language instruction (if set)
        if language:
            parts.append(f"IMPORTANT: Always respond in {language}.")

        # 1. System role (mode-dependent)
        parts.append(_MODE_ROLES.get(assistant_mode, _MODE_ROLES["coach"]))

        # 2. Game context
        if game:
            parts.append(f"The player is playing {game} on {client_type}.")

        # 2b. Tabletop context
        if client_type == "tabletop":
            parts.append(_TABLETOP_CONTEXT)

        # 3. Prompt pack system prompt
        if prompt_pack:
            if prompt_pack.get("system_prompt"):
                parts.append(prompt_pack["system_prompt"])
            if prompt_pack.get("additional_context"):
                parts.append(prompt_pack["additional_context"])

        # 4. Spoiler rules
        if spoiler_block:
            parts.append(spoiler_block)

        # 5. History context
        if history_context:
            parts.append(history_context)

        # 6. User question (ask-mode) or mode-specific instruction
        if user_question:
            parts.append(f"The player asks: {user_question}")
            parts.append("Answer the question directly and concisely.")
        else:
            parts.append(
                _MODE_INSTRUCTIONS.get(assistant_mode, _MODE_INSTRUCTIONS["coach"])
            )

        # 7. Anti-repetition
        if history_context:
            parts.append("Do NOT repeat any previous tips. Give a NEW insight.")

        return "\n\n".join(parts)
