"""Dynamic prompt construction for Gaming Assistant."""
from __future__ import annotations


class PromptBuilder:
    """Builds the final prompt from all components."""

    @staticmethod
    def build(
        game: str = "",
        spoiler_block: str = "",
        history_context: str = "",
        prompt_pack: dict | None = None,
        client_type: str = "pc",
    ) -> str:
        """Assemble the full prompt in the correct order."""
        parts: list[str] = []

        # 1. System role
        parts.append("You are a helpful gaming coach.")

        # 2. Game context
        if game:
            parts.append(f"The player is playing {game} on {client_type}.")

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

        # 6. Instruction
        parts.append(
            "Give exactly ONE short, specific, actionable tip. "
            "No introduction, no emojis, just the tip."
        )

        # 7. Anti-repetition
        if history_context:
            parts.append("Do NOT repeat any previous tips. Give a NEW insight.")

        return "\n\n".join(parts)
