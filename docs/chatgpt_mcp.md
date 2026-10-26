# ChatGPT / MCP bridge

The optional bridge in `worker/mcp_server.py` exposes a small, allowlisted gaming
surface through the Model Context Protocol (MCP). It lets a compatible MCP host
read a recent game frame, inspect Player-2 status, and request one controller
action at a time. It does **not** expose arbitrary Home Assistant services,
keyboard/mouse injection, shell access, or raw MQTT publishing.

The bridge is separate from the HACS integration. Home Assistant remains the
policy and validation boundary; the Windows/Linux gaming PC continues to run
`worker/agent_executor.py`.

## Tools

| Tool | Purpose |
| --- | --- |
| `list_game_clients` | List the clients known to Home Assistant. |
| `get_game_status` | Read Agent Mode state, the last action, and the latest executor receipt. |
| `get_game_snapshot` | Return a screenshot together with its client ID, game and frame timestamp. |
| `set_agent_mode` | Explicitly turn Player 2 on/off. Enabling defaults to a restricted button allowlist. |
| `send_game_action` | Request one validated action against a recent snapshot and wait briefly for a receipt. |
| `stop_game_agent` | Disable Player 2 and request neutral controller inputs. |

## Install and run locally

Use a dedicated virtual environment on a machine that can reach Home Assistant.
Python 3.11 or newer is required.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r worker/requirements-mcp.txt
```

Set the Home Assistant base URL and a long-lived access token in environment
variables. Do not commit the token to a file or repository.

PowerShell:

```powershell
$env:HA_URL = "http://homeassistant.local:8123"
$env:HA_TOKEN = "<your Home Assistant token>"
python worker/mcp_server.py
```

Linux/macOS:

```bash
export HA_URL="http://homeassistant.local:8123"
export HA_TOKEN="<your Home Assistant token>"
python worker/mcp_server.py
```

The default transport is `stdio`, intended for a local MCP host that launches the
process. Configure that host to run `python /absolute/path/to/worker/mcp_server.py`
with `HA_URL` and `HA_TOKEN` in the process environment.

## Connect a remote ChatGPT MCP client

For a hosted client that requires a URL, use Streamable HTTP:

```bash
# Keep the MCP listener on loopback.
export MCP_TRANSPORT="streamable-http"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"
python worker/mcp_server.py
```

The local endpoint is `http://127.0.0.1:8000/mcp`. Put it behind a reverse
proxy or secure tunnel that provides **HTTPS and authentication/access control**
before making it reachable from outside your LAN. Do not bind the MCP server
directly to `0.0.0.0`, expose port 8000 to the Internet, or publish Home
Assistant's API token. The bridge intentionally refuses a non-loopback HTTP
bind.

The SDK's DNS-rebinding protection remains enabled. Its Host allowlist defaults
to loopback names, so for a reverse proxy with a public hostname configure the
exact public Host header in the bridge process, for example:

```bash
export MCP_ALLOWED_HOSTS="gaming-mcp.example.com,gaming-mcp.example.com:*"
# Only needed if a browser-based MCP client sends Origin:
export MCP_ALLOWED_ORIGINS="https://chat.example.com"
```

List both the hostname without a port and the `:*` form; reverse proxies may
forward either. Keep only the hostname(s) you actually serve. Avoid setting
wildcard hostnames or globally disabling DNS-rebinding protection. Configure
the proxy to require authentication, terminate TLS, and limit access to the
trusted client(s). Keep the reverse proxy and token management outside the repository.

The bridge itself does **not** implement MCP OAuth or public-endpoint
authentication. Before exposing it remotely, configure a ChatGPT-compatible
authentication flow at the trusted proxy, or use ChatGPT's Secure MCP Tunnel
when available. A plain unauthenticated public reverse proxy is not safe:
this service can send actual controller inputs.

OpenAI's current help documentation lists custom MCP connections and full
write-capable MCP support for ChatGPT Business and Enterprise/Edu on the web;
workspace policy and rollout still apply. See
[Connecting custom MCP servers in ChatGPT](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).
If your ChatGPT account cannot call write-capable MCP tools, the bridge can still
be used with a compatible local MCP host. A separate API-based player can also
use the same Home Assistant service, but it would be a separate model/API session.

## Safe first run

1. Run `worker/agent_executor.py` on the gaming PC in `--dry-run` mode first.
2. Start the MCP bridge and confirm `list_game_clients` and `get_game_snapshot`
   return the expected client and image.
3. Call `set_agent_mode(enabled=true)` only when you intentionally want Player 2
   to accept actions. The tool selects **exclusive external control**: Home Assistant's
   own local LLM action generator is suppressed while ChatGPT/MCP owns the controller.
   Its default allowlist is limited to face buttons and D-pad.
4. Try one `tap_button` action with a fresh frame timestamp, then check
   `get_game_status` for the matching executor receipt.
5. Use `stop_game_agent` to disable control and neutralize inputs.

Home Assistant rejects an action if Agent Mode is off, exclusive external control
is not enabled, per-action confirmation is still enabled, the target client is not
known, the latest image belongs to a different client, the supplied frame
timestamp is invalid/stale, or the action violates the active button whitelist.
The executor independently validates the action, rejects expired or duplicate
command IDs, and clears held buttons/sticks when its watchdog expires.

The bridge's action receipt means the executor handled the command. It does not
prove that the in-game objective succeeded; a fresh screenshot and game-state
check are still required. For real-time shooters, use a local low-latency
controller for reflexes and reserve ChatGPT for tactical decisions.
