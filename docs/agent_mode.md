# Agent Mode / Player 2 — Safety Guide

> **Status:** experimental (Phase 5). Opt-in, off by default, and reset to OFF on
> every Home Assistant restart.

Agent Mode lets the assistant *play* — not just watch — by turning the LLM's
structured action output into inputs on a **virtual Xbox controller**
(`worker/agent_executor.py`, via [`vgamepad`](https://pypi.org/project/vgamepad/)).
This document is the single reference for its safety model.

---

## Why a virtual gamepad

A virtual controller can **only** emit game-controller inputs. It cannot move
the mouse, alt-tab, type system commands, or touch anything outside the focused
game. Constraining the AI to "press buttons on a gamepad" is the entire safety
premise — there is no path from a controller input to the host OS.

---

## The safety rails

Agent Mode is defended in layers, on both the Home Assistant side and the
executor side. Each rail is independent; a failure of one does not disable the
others.

### Home Assistant side (the governor)

| Rail | Behaviour |
| :--- | :--- |
| **Opt-in** | Off until you enable `switch.gaming_assistant_agent_mode` or call `gaming_assistant.set_agent_mode`. |
| **Reset on restart** | The switch returns to **OFF** on every HA restart — the AI never resumes driving on its own. |
| **Rate limiting** | Actions are throttled so a runaway pipeline cannot flood inputs. |
| **Dead-man switch** | Agent Mode **auto-disables after repeated failures**, so a broken pipeline never keeps the AI "driving". |
| **Audit** | Every decision (published or rejected) lands on `sensor.gaming_assistant_agent_action` and the `gaming_assistant_agent_action` event. |
| **Optional confirmation** | Off by default. When on, each action waits as *pending* until you confirm or reject it, and lapses after 30 s. See below. |

### Executor side (`agent_executor.py`)

| Rail | Behaviour |
| :--- | :--- |
| **Whitelist** | Only buttons listed in `--allow-buttons` are ever forwarded; anything else is rejected and logged. |
| **Dry-run** | `--dry-run` (and the automatic fallback when `vgamepad` isn't installed) validates and logs actions **without sending input**. Always start here. |
| **Audit log** | Every action — accepted, rejected, or skipped — is appended as one JSON line to `--audit-log`. |
| **Emergency stop** | Publish `stop` to `gaming_assistant/command` to instantly pause and release all inputs; `start` resumes. |
| **Fail-safe release** | Inputs are released on disconnect and on shutdown, so nothing ever stays stuck "held down". |

---

## Recommended bring-up

Always go live in stages — never enable HA-side publishing and a live executor
at the same time on the first run.

```bash
pip install -r worker/requirements-player2.txt   # vgamepad + paho-mqtt
# (Windows also needs the free ViGEmBus driver for vgamepad.)

# 1) Safe first run — validates + logs, sends nothing:
python worker/agent_executor.py --broker 192.168.1.10 --client-id gaming-pc --dry-run

# 2) Go live, restricted to face buttons + D-pad:
python worker/agent_executor.py --broker 192.168.1.10 --client-id gaming-pc \
  --allow-buttons A,B,X,Y,DPAD_UP,DPAD_DOWN,DPAD_LEFT,DPAD_RIGHT
```

Test the path end-to-end by publishing an action yourself before letting the LLM
drive (HA → *Developer Tools → Actions → `mqtt.publish`*, or `mosquitto_pub`):

```bash
mosquitto_pub -h 192.168.1.10 -t gaming_assistant/gaming-pc/action \
  -m '{"action":"tap_button","button":"A","duration_ms":80,"reason":"confirm"}'
```

Only once the executor behaves as expected, let Home Assistant drive it:

```yaml
action: gaming_assistant.set_agent_mode
data:
  enabled: true
  allowed_buttons: "A, B, X, Y, DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT"
```

Each analyzed frame then additionally asks the LLM for **one** controller
action, validates it, and publishes it to `gaming_assistant/{client_id}/action`
for the executor.

---

## Optional: confirm each action

Whoever enables Agent Mode trusts their agent, so actions go straight to the
executor by default. If you would rather approve each one, turn on
`switch.gaming_assistant_agent_confirm_actions` or pass `confirm_actions: true`:

```yaml
action: gaming_assistant.set_agent_mode
data:
  enabled: true
  confirm_actions: true
```

Each generated action is then held as **pending**:

- `sensor.gaming_assistant_agent_action` switches to `pending` and shows the
  action, its `pending_action_id` and `pending_expires`.
- The `gaming_assistant_agent_action` event fires with `status: pending` and
  the `action_id`.
- `button.gaming_assistant_agent_confirm_action` and
  `button.gaming_assistant_agent_reject_action` become available.

Decide with a button, with `gaming_assistant.confirm_agent_action` /
`gaming_assistant.reject_agent_action` (optionally with the `action_id`, so a
notification never confirms a newer action than the one it showed), or with a
phone notification (see `lovelace/automations_example.yaml`). Nobody decides
within 30 seconds? The action lapses as `expired`. While an action waits, the
agent does not ask the LLM for the next one. Turning Agent Mode or the
confirmation off drops a waiting action (`cancelled`) instead of sending it.

---

## Action schema

Actions follow `PromptBuilder.ACTION_SCHEMA`:

- `press_button`, `release_button`, `tap_button` — buttons
  `A`/`B`/`X`/`Y`/`LB`/`RB`/`LT`/`RT`/`DPAD_*`/`START`/`BACK`
- `move_stick` — `left`/`right`, `x`/`y` in `[-1.0, 1.0]`
- `wait`, `no_op`

Anything outside this schema, or outside the executor whitelist, is rejected and
audited — never forwarded.

The LLM sees an Xbox controller and has to guess what the buttons do in your
game. A capture client can tell it: a short `controls` text in the client's
`meta` payload (up to 400 characters, e.g. `"RT fires, A opens doors"`) goes
into the action prompt as is. The ViZDoom agent below sends one.

---

## ViZDoom hybrid: reflexes + LLM strategy

`worker/vizdoom_agent.py` lets the assistant play Doom inside
[ViZDoom](https://vizdoom.farama.org), a Doom engine built for AI research. An
LLM is far too slow for a firefight, so the agent splits the work:

| Layer | Runs | Does |
| :--- | :--- | :--- |
| Reflexes | in the worker, every tic (35 per second) | Reads ViZDoom's labels (what is on screen, with boxes), turns toward the biggest monster and fires once the crosshair is on it. Corpses and items are ignored. |
| Strategy | Home Assistant's Agent Mode, every few seconds | Gets a frame, the HUD numbers and the controls, and answers with one controller action: walk, turn, open a door, switch weapons. |

While a monster is in view, the reflexes aim and fire and the strategy keeps
moving (strafing while shooting). With no monster in view, the strategy steers;
with neither, the agent turns slowly to look around (`--idle scan`).

The worker is executor and capture client in one: it publishes frames, HUD
numbers (`health`, `armor`, `ammo`, `kills`) and its controls, and takes
actions from `gaming_assistant/{client_id}/action`. Everything the AI does stays
inside the ViZDoom process: no gamepad, no keyboard or mouse. The rails are the
executor's: a button whitelist (`--allow-buttons`), the audit log
(`--audit-log`), and `stop` / `start` on `gaming_assistant/command`, which cuts
all input, reflexes included.

Controller to Doom: the left stick walks and strafes, the right stick turns,
`RT` fires, `A`/`X` use (doors, switches), `RB`/`Y` and `LB` switch weapons, `LT`
runs, the D-pad walks and turns. `B`, `START` and `BACK` do nothing (no game
menu).

```bash
pip install -r worker/requirements-vizdoom.txt

# Reflexes alone, no Home Assistant (3 episodes, summary at the end):
python worker/vizdoom_agent.py --offline --show --scenario defend_the_center

# Hybrid: frames to Home Assistant, actions back. Then turn on Agent Mode.
python worker/vizdoom_agent.py --broker 192.168.1.10 --client-id doom --show
```

`--no-reflexes` lets only the LLM play, for comparison. `--scenario` picks one of
ViZDoom's bundled scenarios (`deathmatch` by default; `defend_the_center`,
`basic`, `my_way_home`, `health_gathering`, `freedoom2` for a whole Freedoom
level, …), `--config` your own `.cfg`. `--seed` makes runs repeatable.

---

## Performance note

Agent Mode runs a **second** inference per frame (in addition to the normal
tip), so expect higher load, especially on local models. If your model is slow,
raise the capture interval before enabling it.

---

## Emergency stop, again

If anything looks wrong, the instant brake is always:

```bash
mosquitto_pub -h 192.168.1.10 -t gaming_assistant/command -m stop
```

This releases all inputs immediately. Disabling the
`switch.gaming_assistant_agent_mode` switch (or restarting HA) stops new actions
from being published in the first place.
