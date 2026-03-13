"""Spoiler level management for Gaming Assistant."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .const import SPOILER_CATEGORIES, SPOILER_LEVELS, DEFAULT_SPOILER_LEVEL

_LOGGER = logging.getLogger(__name__)

# Human-readable descriptions for each category at each level
_LEVEL_DESCRIPTIONS = {
    "story": {
        "none": "Do NOT reveal any story elements, plot points, or narrative details.",
        "low": "You may confirm general story progress, but do not spoil upcoming events.",
        "medium": "You may reference current story context, but avoid major reveals.",
        "high": "You may discuss story details freely.",
    },
    "items": {
        "none": "Do NOT mention specific item names, locations, or stats.",
        "low": "You may hint that useful items exist nearby without naming them.",
        "medium": "You may name items and give general location hints.",
        "high": "You may mention specific item names, locations, and stats.",
    },
    "enemies": {
        "none": "Do NOT describe enemy types or strategies.",
        "low": "You may warn about danger ahead without specifics.",
        "medium": "You may describe enemy types and general strategies, but do not reveal boss mechanics.",
        "high": "You may describe all enemies and their strategies in detail.",
    },
    "bosses": {
        "none": "Do NOT reveal anything about bosses.",
        "low": "You may confirm a boss exists, but do not describe attacks or weaknesses.",
        "medium": "You may give general boss strategy tips without detailing all mechanics.",
        "high": "You may discuss boss attacks, phases, and weaknesses freely.",
    },
    "locations": {
        "none": "Do NOT reveal area names or directions to hidden locations.",
        "low": "You may give vague directional hints.",
        "medium": "You may name areas and give general directions.",
        "high": "You may describe exact paths and hidden locations.",
    },
    "lore": {
        "none": "Do not discuss world lore or backstory.",
        "low": "You may reference surface-level lore without deep details.",
        "medium": "You may discuss moderate lore context.",
        "high": "You may discuss lore freely.",
    },
    "mechanics": {
        "none": "Do NOT explain game mechanics beyond what is obvious on screen.",
        "low": "You may hint at mechanics the player seems to be struggling with.",
        "medium": "You may explain relevant game mechanics.",
        "high": "You may explain any game mechanic in detail.",
    },
}


class SpoilerManager:
    """Manages spoiler settings and generates prompt blocks."""

    def __init__(self, storage_path: str | None = None) -> None:
        # Global defaults (all categories start at the configured default level)
        self._global_settings: dict[str, str] = {}
        # Per-game overrides
        self._game_settings: dict[str, dict[str, str]] = {}
        self._storage_path = Path(storage_path) if storage_path else None

    def initialize(self, default_level: str = DEFAULT_SPOILER_LEVEL) -> None:
        """Set all categories to the default level."""
        if default_level not in SPOILER_LEVELS:
            default_level = DEFAULT_SPOILER_LEVEL
        self._global_settings = {cat: default_level for cat in SPOILER_CATEGORIES}

    def get_settings(self, game: str | None = None) -> dict[str, str]:
        """Return spoiler settings, game-specific overrides merged on top of global."""
        settings = dict(self._global_settings)
        if game and game in self._game_settings:
            settings.update(self._game_settings[game])
        return settings

    def get_game_profiles(self) -> dict[str, dict[str, str]]:
        """Return all per-game profiles."""
        return self._game_settings

    def set_level(
        self, category: str, level: str, game: str | None = None
    ) -> None:
        """Set spoiler level for a category (globally or per game)."""
        if level not in SPOILER_LEVELS:
            _LOGGER.warning("Invalid spoiler level '%s', ignoring", level)
            return

        if category == "all":
            targets = SPOILER_CATEGORIES
        elif category in SPOILER_CATEGORIES:
            targets = [category]
        else:
            _LOGGER.warning("Unknown spoiler category '%s', ignoring", category)
            return

        if game:
            self._game_settings.setdefault(game, {})
            for cat in targets:
                self._game_settings[game][cat] = level
        else:
            for cat in targets:
                self._global_settings[cat] = level

        self.save()

    def set_game_profile(self, game: str, level: str) -> None:
        """Set all categories for a game profile with one level."""
        if level not in SPOILER_LEVELS:
            _LOGGER.warning("Invalid spoiler level '%s', ignoring", level)
            return
        self._game_settings[game] = {cat: level for cat in SPOILER_CATEGORIES}
        self.save()

    def clear_game_profile(self, game: str) -> None:
        """Remove game-specific profile so globals apply again."""
        self._game_settings.pop(game, None)
        self.save()

    def apply_pack_defaults(self, game: str, spoiler_defaults: dict[str, str]) -> None:
        """Apply prompt pack spoiler defaults as a baseline for a game.

        Only sets values that haven't been explicitly overridden by the user.
        """
        if game not in self._game_settings:
            self._game_settings[game] = {}
        for cat, level in spoiler_defaults.items():
            if cat in SPOILER_CATEGORIES and cat not in self._game_settings[game]:
                self._game_settings[game][cat] = level

    def load(self) -> None:
        """Load spoiler profile settings from disk if available."""
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            global_settings = data.get("global", {})
            game_settings = data.get("games", {})

            # validate keys/values
            for cat in SPOILER_CATEGORIES:
                level = global_settings.get(cat)
                if level in SPOILER_LEVELS:
                    self._global_settings[cat] = level

            clean_games: dict[str, dict[str, str]] = {}
            for game, settings in game_settings.items():
                if not isinstance(settings, dict):
                    continue
                clean_games[game] = {
                    cat: level
                    for cat, level in settings.items()
                    if cat in SPOILER_CATEGORIES and level in SPOILER_LEVELS
                }
            self._game_settings = clean_games
        except (json.JSONDecodeError, OSError) as err:
            _LOGGER.warning("Could not load spoiler profiles: %s", err)

    def save(self) -> None:
        """Persist spoiler profile settings to disk."""
        if not self._storage_path:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "global": self._global_settings,
                "games": self._game_settings,
            }
            self._storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as err:
            _LOGGER.warning("Could not save spoiler profiles: %s", err)

    @staticmethod
    def generate_prompt_block(settings: dict[str, str]) -> str:
        """Generate the spoiler rules section of the prompt."""
        lines = ["SPOILER RULES (you MUST follow these strictly):"]
        label_map = {
            "story": "Story/Plot",
            "items": "Items/Equipment",
            "enemies": "Enemies",
            "bosses": "Bosses",
            "locations": "Locations",
            "lore": "Lore",
            "mechanics": "Mechanics",
        }
        for cat in SPOILER_CATEGORIES:
            level = settings.get(cat, DEFAULT_SPOILER_LEVEL)
            label = label_map.get(cat, cat.title())
            desc = _LEVEL_DESCRIPTIONS.get(cat, {}).get(level, "")
            lines.append(f"- {label}: {level.upper()} -> {desc}")
        return "\n".join(lines)
