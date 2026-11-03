---
name: ha-gaming-assistant
description: Play or coach a running video game through the Home Assistant Gaming Assistant MCP bridge (tools list_game_clients, get_game_snapshot, get_game_status, set_agent_mode, send_game_action, stop_game_agent). Use when the user asks for help with the game on screen, wants a tip for the current situation, or wants the agent to take over as Player 2 on the gamepad.
---

# Home Assistant Gaming Assistant

The MCP bridge (`worker/mcp_server.py`) gives you a recent screenshot of the
game and, only when the user enables it, one gamepad action at a time. Home
Assistant and the executor on the gaming PC validate every action again; you
cannot reach other Home Assistant services, the keyboard, the mouse or a shell.

If none of the tools above are available, the bridge is not connected. Point
the user to `docs/chatgpt_mcp.md` instead of guessing.

## Coaching (read-only, the default)

1. `list_game_clients` — pick the client that is online and reports a game.
   If there are several, ask which one.
2. `get_game_snapshot(client_id)` — look at the image and the `game` field.
   "No fresh game frame" means the capture agent is not running; say so.
3. Answer with one or two concrete tips for what is on screen right now.
   Refer to what you see (HUD values, enemies, map, menu), not to generic advice.
4. For a follow-up question, fetch a new snapshot first; frames go stale fast.

Do not call `set_agent_mode` or `send_game_action` while coaching.

## Playing as Player 2 (only when the user asks)

1. Confirm the user really wants you to press buttons, then call
   `set_agent_mode(enabled=true)`. Keep the default allowlist
   (face buttons + D-pad) unless the user names more buttons for this game.
   This switches Home Assistant to exclusive external control.
2. Loop, one action at a time:
   - `get_game_snapshot(client_id)` and read the `timestamp`.
   - `send_game_action(client_id, expected_frame_timestamp=<that timestamp>, action=..., reason=...)`.
     Keep `reason` short; it ends up in the audit log.
   - Check the returned `status`. `published_waiting_for_executor_receipt`
     is not success — fetch a new snapshot or `get_game_status` before the
     next step.
3. Judge success only from a fresh snapshot. A receipt means the button was
   pressed, not that the game reacted the way you wanted.
4. Finish with `stop_game_agent`, also when anything goes wrong or the user
   says stop. It disables Player 2 and releases all inputs.

### Actions

| action | parameters |
| --- | --- |
| `tap_button` | `button`, optional `duration_ms` |
| `press_button` / `release_button` | `button` (a held button is released by the watchdog after ~1.5 s without fresh control) |
| `move_stick` | `stick` = `left`/`right`, `x`, `y` in `[-1.0, 1.0]`, optional `duration_ms` |
| `wait` / `no_op` | — |

Buttons: `A B X Y LB RB LT RT START BACK DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT`,
limited to what `set_agent_mode` allowed.

## Common rejections

- **Snapshot older than 10 seconds / in the future** — fetch a new snapshot and
  use its timestamp.
- **Newest frame belongs to another client** — wait for the right client or
  ask the user which one to use.
- **Agent Mode off / not external / confirmation enabled** — call
  `set_agent_mode(enabled=true)` again; do not work around it.
- **Button not in allowlist** — ask the user before widening it.

## Limits

The loop of snapshot → decision → action takes seconds. Do not try to aim or
dodge in real-time shooters; leave reflexes to the player and offer tactics.
Never ask for or print the Home Assistant token.
