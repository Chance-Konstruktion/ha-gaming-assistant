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

## Action schema

Actions follow `PromptBuilder.ACTION_SCHEMA`:

- `press_button`, `release_button`, `tap_button` — buttons
  `A`/`B`/`X`/`Y`/`LB`/`RB`/`LT`/`RT`/`DPAD_*`/`START`/`BACK`
- `move_stick` — `left`/`right`, `x`/`y` in `[-1.0, 1.0]`
- `wait`, `no_op`

Anything outside this schema, or outside the executor whitelist, is rejected and
audited — never forwarded.

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
