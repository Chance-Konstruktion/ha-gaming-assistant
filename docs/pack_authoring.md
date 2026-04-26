# Prompt Pack Authoring Guide

This guide explains how to write a prompt pack for the Gaming Assistant
integration. Packs are small JSON files that teach the AI how to coach
a specific game — they tune the system prompt, anti-spoiler rules, and
optional metadata for one title.

Community packs live in a separate repository:
[**Chance-Konstruktion/ha-gaming-assistant-prompts**](https://github.com/Chance-Konstruktion/ha-gaming-assistant-prompts).
Every Home Assistant install pulls the latest packs from there at
startup and after the `gaming_assistant.refresh_prompt_packs` service
is called.

---

## 1. What a pack does

When a capture agent reports the active game (via window title, app
package, or `--game-hint`), the integration looks for a pack whose
`keywords` match that text. The matching pack contributes:

- a **system prompt** that frames the LLM as a coach for that title,
- optional **additional context** for non-compact prompts,
- **spoiler defaults** that seed the per-game spoiler profile,
- **constraints** that signal hardware/mode requirements,
- **examples** for human readers (not currently injected into prompts).

The pack does *not* override user preferences once they exist —
spoiler defaults are only applied to a game profile **the first time**
the pack is used.

---

## 2. File layout

A pack is a single JSON file with a snake_case ID:

```
packs/
├── base/
│   ├── elden_ring.json
│   └── stardew_valley.json
├── tabletop/
│   ├── chess.json
│   └── catan.json
└── card/
    └── poker.json
```

The integration walks `packs/**/*.json` in the prompts repo
recursively, so subdirectories are only for organization. Filenames
that start with `_` (like `_template.json`) are skipped, as is
`pack_manifest.json` (reserved for the schema document).

---

## 3. Minimal pack

The smallest valid pack only needs four fields:

```json
{
  "id": "snake_case_id",
  "name": "Display Name",
  "keywords": ["display name", "alternative title"],
  "system_prompt": "You are a coach for Display Name. ..."
}
```

Drop that into `packs/base/snake_case_id.json` and the integration
will pick it up on the next load. The bundled
[`_template.json`](../custom_components/gaming_assistant/prompt_packs/_template.json)
is a copy-paste-ready starting point.

---

## 4. Full schema

The complete schema lives in
[`pack_manifest.json`](../custom_components/gaming_assistant/prompt_packs/pack_manifest.json)
and is enforced at load time by `validate_pack()` in
[`prompt_packs/__init__.py`](../custom_components/gaming_assistant/prompt_packs/__init__.py).
Invalid packs are skipped with a warning, surfaced via
`PromptPackLoader.invalid_packs` for diagnostics.

| Field | Type | Required | Notes |
|-------|------|:-------:|-------|
| `id` | string | yes | Must match `^[a-z0-9_]+$`. Globally unique within the prompts repo. Cached packs override bundled packs with the same `id`. |
| `name` | string | yes | Human-readable game name shown in the panel and logs. |
| `keywords` | string[] | yes | Substrings matched (case-insensitive) against window titles, app names, or `--game-hint`. Order matters: include the most specific titles first. At least one entry. |
| `system_prompt` | string | yes | The coach role injected at the start of every prompt for this game. |
| `additional_context` | string | no | Appended in non-compact mode only — use it for long-form context that small models can't fit. |
| `spoiler_defaults` | object | no | Per-category baseline spoiler levels. Categories: `story`, `items`, `enemies`, `bosses`, `locations`, `lore`, `mechanics`. Levels: `none`, `low`, `medium`, `high`. Applied once per game profile. |
| `version` | string | no | Semantic version like `1.0` or `1.2.3`. Recommended for tracking pack updates. |
| `game_id` | string | no | Stable upstream identifier (Steam AppID, IGDB slug, etc.). Useful for analytics or future Pack-Sharing UI. |
| `constraints` | object | no | Soft requirements; see below. |
| `examples` | object[] | no | Documentation-only samples of "situation → tip". Not injected into prompts but invaluable for reviewers. |

### `constraints` sub-fields

| Field | Type | Notes |
|-------|------|-------|
| `min_model_params_b` | number | Minimum recommended model size in billions of parameters (e.g. `7` for `qwen2.5vl:7b`). |
| `requires_vision` | boolean | If `true`, refuse to run under text-only backends (DeepSeek, Groq). |
| `supported_modes` | string[] | Subset of `["coach", "coplay", "opponent", "analyst"]`. |

### `examples` entry shape

```json
{
  "situation": "Low health, dragon in second phase",
  "tip": "Disengage and use a flask before re-entering melee range."
}
```

Each entry needs both `situation` and `tip`. Keep them short — these
are author notes, not prompt content.

---

## 5. End-to-end example

A fully featured pack:

```json
{
  "id": "elden_ring_extended",
  "name": "Elden Ring (Extended)",
  "version": "1.1",
  "game_id": "1245620",
  "keywords": ["elden ring", "eldenring"],
  "system_prompt": "You are a senior FromSoftware coach. Help the player read enemy tells, manage stamina, and make builds work.",
  "additional_context": "The HUD shows HP/FP/stamina top-left, runes top-right, equipped flask + items bottom-left, weapon arts bottom-right. Hosts and summons are tagged in the top-right.",
  "spoiler_defaults": {
    "story": "none",
    "items": "medium",
    "enemies": "medium",
    "bosses": "low",
    "locations": "medium",
    "lore": "none",
    "mechanics": "high"
  },
  "constraints": {
    "min_model_params_b": 7,
    "requires_vision": true,
    "supported_modes": ["coach", "analyst"]
  },
  "examples": [
    {
      "situation": "Player at <30% HP, no flasks left, boss in phase 2",
      "tip": "Roll backwards twice and disengage. Wait for the next charged attack and re-position behind the pillar — heal up there."
    }
  ]
}
```

---

## 6. Writing a good `system_prompt`

A few rules that survive most LLMs:

1. **Anchor the role.** "You are a coach for X" beats "You know about X".
2. **Describe the HUD** the model is going to see. The vision model
   reads the screen — telling it where the health bar is saves
   tokens.
3. **Stay short for compact mode.** Models at 1B–4B parameters get a
   compressed prompt automatically; the integration trims, but verbose
   packs leave less room for game state. Keep `system_prompt` under
   ~600 characters.
4. **Don't bake in spoilers.** Story flags, secret items, and boss
   names belong behind `spoiler_defaults`, not in the system prompt.
5. **Avoid redundant instructions.** The PromptBuilder already adds
   "give ONE tip", language directives, and anti-repetition hints.

Compact-mode authors: write a long prompt, then prune until a 3B
model can still pick out the game's identity in a single pass.

---

## 7. Spoiler defaults

Packs *seed* the per-game profile, they don't enforce it. The first
time the integration loads a pack for a game it copies missing
categories from `spoiler_defaults` into the user's spoiler profile
for that game. After that, anything the user changes via the UI or
the `gaming_assistant.set_spoiler_level` service wins.

When picking defaults:

- `story`, `lore` → default to `none` for narrative-heavy games.
- `mechanics` → `high` is usually safe; this is what coaches need.
- `bosses` → `low` is a good middle ground; flag `high` only for
  competitive/PvP titles.
- `items` → match the genre; `medium` works for action, `low` for
  Soulslikes, `high` for arcade-style titles.

---

## 8. Testing locally

You can test a pack without going through the prompts repo:

1. Drop the JSON file into
   `<HA-config>/gaming_assistant/prompt_packs/` (the cache directory
   has priority over bundled packs).
2. Call `gaming_assistant.refresh_prompt_packs` from
   **Developer Tools → Services**.
3. Watch the HA log:
   ```
   Loaded N prompt packs total (… cached, … bundled, M invalid)
   Prompt pack <file>.json is invalid: <reason>   # only if validation failed
   ```
4. Check the **Gaming Assistant Workers** sensor and the panel: the
   active pack ID is exposed in the `available_game_packs` attribute.
5. Trigger an analysis (`gaming_assistant.analyze` or wait for the
   capture agent) and read the next tip. If it doesn't match your
   pack's voice, iterate on `system_prompt`.

For unit-test-style checks, the integration ships fixtures under
`tests/fixtures/prompt_packs/` and a parametrized validator test
(`tests/test_prompt_packs.py::TestPackValidation`). Run:

```bash
python -m unittest tests.test_prompt_packs
```

after dropping a copy of your pack into `tests/fixtures/prompt_packs/`
to confirm it parses.

---

## 9. Submitting to the community repo

1. Fork [`ha-gaming-assistant-prompts`](https://github.com/Chance-Konstruktion/ha-gaming-assistant-prompts).
2. Add your pack under `packs/base/<id>.json` (or another category).
3. Run any local validation you can:
   ```bash
   python -c "import json, sys; json.loads(open(sys.argv[1]).read())" packs/base/your_pack.json
   ```
4. Open a PR. Include:
   - Game title and platforms covered.
   - Why the pack is useful (which knowledge isn't already in a
     general coach).
   - Optional: screenshots of tips your pack produced.
5. Bump `version` if you're updating an existing pack.

The Gaming Assistant integration will pick up your pack on the next
HA start (or immediately after `refresh_prompt_packs`) once it's
merged into `main`.

---

## 10. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Pack never matches | `keywords` don't appear in the window/app title. Add the substring you actually see in the **Gaming Assistant Workers** sensor's `meta.window_title`. |
| Pack loads but tips ignore your role | `system_prompt` is being trimmed in compact mode — shorten it, or set `constraints.min_model_params_b` so users on 3B models get a warning. |
| Loader logs `invalid: ...` | Run `validate_pack()` mentally against the field table above. Common culprits: non-snake-case `id`, empty `keywords`, illegal spoiler level. |
| Two packs match the same title | Cached packs override bundled ones with the same `id`. Different IDs both match — narrow your `keywords` so they're game-specific. |

For anything else, check `docs/FAQ.md` and the "No tips" section in
the README's Troubleshooting chapter.
