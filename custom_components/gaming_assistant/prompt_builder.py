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
    ) -> str:
        """Assemble the full prompt in the correct order."""
        parts: list[str] = []

        # 1. System role
        parts.append("You are a helpful gaming coach.")

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

        # 6. User question (ask-mode) or default tip instruction
        if user_question:
            parts.append(f"The player asks: {user_question}")
            parts.append("Answer the question directly and concisely.")
        else:
            parts.append(
                "Give exactly ONE short, specific, actionable tip. "
                "No introduction, no emojis, just the tip."
            )

        # 7. Anti-repetition
        if history_context:
            parts.append("Do NOT repeat any previous tips. Give a NEW insight.")

        return "\n\n".join(parts)
