#!/usr/bin/env python3
"""Optional MCP bridge between ChatGPT-compatible clients and Home Assistant.

The bridge exposes a deliberately small game-control surface. It never exposes
arbitrary Home Assistant services, shell commands, keyboard input, or raw MQTT.
Run with stdio for a local MCP host, or Streamable HTTP bound to loopback behind
a TLS/authentication reverse proxy.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ImageContent, TextContent

HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8000"))
_DEFAULT_ALLOWED_HOSTS = (
    "127.0.0.1,127.0.0.1:*,localhost,localhost:*,[::1],[::1]:*"
)
MCP_ALLOWED_HOSTS = tuple(
    item.strip() for item in os.getenv("MCP_ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS).split(",")
    if item.strip()
)
_DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1,http://127.0.0.1:*,http://localhost,"
    "http://localhost:*,http://[::1],http://[::1]:*"
)
MCP_ALLOWED_ORIGINS = tuple(
    item.strip() for item in os.getenv("MCP_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS).split(",")
    if item.strip()
)
REQUEST_TIMEOUT_S = 10.0
RESULT_WAIT_S = 2.5
RESULT_POLL_S = 0.25
SNAPSHOT_MAX_AGE_S = 10.0
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CLIENTS_ENTITY = "sensor.gaming_assistant_clients"
ACTION_ENTITY = "sensor.gaming_assistant_agent_action"
LAST_FRAME_ENTITY = "image.gaming_assistant_last_frame"

# The project pins the v1 maintenance line (mcp<2), where HTTP settings and
# TransportSecuritySettings belong to the FastMCP constructor. Never turn off
# DNS-rebinding protection globally; deployers must allowlist the public proxy host.
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=list(MCP_ALLOWED_HOSTS),
    allowed_origins=list(MCP_ALLOWED_ORIGINS),
)
mcp = FastMCP(
    "Home Assistant Gaming Assistant",
    host=HOST,
    port=PORT,
    transport_security=_transport_security,
)


class BridgeError(RuntimeError):
    """A safe, user-readable bridge error without credentials or response dumps."""


def _validate_configuration() -> None:
    parsed = urlparse(HA_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BridgeError("HA_URL must be an absolute http:// or https:// URL.")
    if TRANSPORT not in {"stdio", "streamable-http"}:
        raise BridgeError("MCP_TRANSPORT must be stdio or streamable-http.")
    if not MCP_ALLOWED_HOSTS:
        raise BridgeError("MCP_ALLOWED_HOSTS must contain at least one allowed Host header.")
    if TRANSPORT == "streamable-http" and HOST not in {"127.0.0.1", "localhost", "::1"}:
        raise BridgeError(
            "The MCP bridge only binds to loopback by default. Put it behind a TLS "
            "reverse proxy with authentication rather than exposing this port directly."
        )


async def _ha_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    binary: bool = False,
) -> Any:
    if not HA_TOKEN.strip():
        raise BridgeError("Set HA_TOKEN to a Home Assistant long-lived access token.")
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Accept": "image/jpeg" if binary else "application/json",
    }
    try:
        async with httpx.AsyncClient(
            base_url=HA_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=False,
        ) as client:
            response = await client.request(
                method, path, params=params, json=json_body
            )
            if response.status_code >= 400:
                if response.status_code == 401:
                    raise BridgeError("Home Assistant rejected HA_TOKEN (HTTP 401).")
                if response.status_code == 404:
                    raise BridgeError(
                        f"Home Assistant entity or service was not found: {path}"
                    )
                raise BridgeError(
                    f"Home Assistant request failed with HTTP {response.status_code}."
                )
            if binary:
                if len(response.content) > MAX_IMAGE_BYTES:
                    raise BridgeError("Screenshot exceeds the configured 8 MiB limit.")
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    raise BridgeError("Home Assistant did not return image content.")
                return response.content
            return response.json()
    except httpx.TimeoutException as err:
        raise BridgeError("Timed out while contacting Home Assistant.") from err
    except httpx.HTTPError as err:
        raise BridgeError("Could not connect to Home Assistant; check HA_URL and network access.") from err


async def _get_state(entity_id: str) -> dict[str, Any]:
    data = await _ha_request("GET", f"/api/states/{entity_id}")
    if not isinstance(data, dict):
        raise BridgeError(f"Unexpected state response for {entity_id}.")
    return data


def _snapshot_metadata(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes") or {}
    return {
        "entity_id": LAST_FRAME_ENTITY,
        "client_id": attrs.get("client_id", ""),
        "game": attrs.get("game", ""),
        "timestamp": attrs.get("timestamp", ""),
        "last_updated": state.get("last_updated", ""),
    }


def _timestamp_age(timestamp: str) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
        # HA can return naive local timestamps or timezone-aware ISO timestamps.
        # Keep negative age visible so future timestamps fail closed at the call site.
        return time.time() - parsed.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def _image_format(image_bytes: bytes) -> str:
    """Infer the MCP image MIME subtype from the actual screenshot bytes."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "webp"
    # JPEG is the capture agents' standard encoding and is the safe fallback.
    return "jpeg"


@mcp.tool()
async def list_game_clients() -> str:
    """List registered gaming clients and their reported online/game metadata."""
    state = await _get_state(CLIENTS_ENTITY)
    attrs = state.get("attributes") or {}
    return json.dumps(
        {
            "count": state.get("state", "0"),
            "clients": attrs.get("clients", {}),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def get_game_status() -> str:
    """Return current Agent Mode status, last action, and executor receipt."""
    state = await _get_state(ACTION_ENTITY)
    attrs = state.get("attributes") or {}
    return json.dumps(
        {
            "agent_mode": attrs.get("agent_mode", False),
            "external_control": attrs.get("external_control", False),
            "state": state.get("state", "unknown"),
            "last_action": attrs.get("last_action"),
            "last_execution_result": attrs.get("last_execution_result"),
            "actions_published": attrs.get("actions_published", 0),
            "actions_failed": attrs.get("actions_failed", 0),
            "allowed_buttons": attrs.get("allowed_buttons", []),
            "confirm_actions": attrs.get("confirm_actions", False),
            "pending_action": attrs.get("pending_action"),
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def get_game_snapshot(client_id: str = "") -> list[TextContent | ImageContent]:
    """Return one recent screenshot with its exact frame timestamp and game metadata.

    Use the timestamp from the text block as expected_frame_timestamp when sending
    a later action. If the client is capturing too quickly and the screenshot
    changes during retrieval, this tool retries once to produce a consistent pair.
    """
    for _attempt in range(2):
        state_before = await _get_state(LAST_FRAME_ENTITY)
        meta = _snapshot_metadata(state_before)
        if client_id and meta["client_id"] != client_id:
            raise BridgeError(
                f"The newest frame belongs to {meta['client_id']!r}, not {client_id!r}. "
                "Retry after that client publishes a frame."
            )
        age = _timestamp_age(str(meta["timestamp"]))
        if age is None or age < -1.0 or age > SNAPSHOT_MAX_AGE_S:
            raise BridgeError(
                "No fresh game frame is available. Start the capture agent and retry."
            )
        image_bytes = await _ha_request(
            "GET",
            f"/api/image_proxy/{LAST_FRAME_ENTITY}",
            params={"time": str(int(time.time() * 1000))},
            binary=True,
        )
        state_after = await _get_state(LAST_FRAME_ENTITY)
        meta_after = _snapshot_metadata(state_after)
        if meta_after["timestamp"] == meta["timestamp"] and meta_after["client_id"] == meta["client_id"]:
            meta["snapshot_age_seconds"] = round(age, 2)
            meta["instruction"] = (
                "Use this timestamp as expected_frame_timestamp when issuing an action. "
                "A stale frame or a different active client will be rejected."
            )
            text = TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))
            image = Image(data=image_bytes, format=_image_format(image_bytes)).to_image_content()
            return [text, image]
    raise BridgeError("The game frame changed during retrieval; fetch a new snapshot.")


@mcp.tool()
async def set_agent_mode(
    enabled: bool,
    allowed_buttons: str = "A,B,X,Y,DPAD_UP,DPAD_DOWN,DPAD_LEFT,DPAD_RIGHT",
    confirm_actions: bool = False,
) -> str:
    """Enable or disable Player 2. Default allowlist is intentionally restrictive."""
    data: dict[str, Any] = {
        "enabled": enabled,
        "confirm_actions": confirm_actions,
        # Exclusive control is essential: otherwise the local HA LLM could
        # publish its own controller actions in parallel with this MCP client.
        "external": enabled,
    }
    if enabled:
        data["allowed_buttons"] = allowed_buttons
    await _ha_request("POST", "/api/services/gaming_assistant/set_agent_mode", json_body=data)
    return json.dumps(
        {
            "accepted": True,
            "agent_mode": enabled,
            "external_control": enabled,
            "allowed_buttons": allowed_buttons.split(",") if enabled else [],
            "confirm_actions": confirm_actions,
            "note": "Actions stay disabled until this tool is explicitly called with enabled=true.",
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def send_game_action(
    client_id: str,
    expected_frame_timestamp: str,
    action: str,
    button: str = "",
    stick: str = "",
    x: float | None = None,
    y: float | None = None,
    duration_ms: int | None = None,
    reason: str = "",
) -> str:
    """Send one allowlist-checked action for a recent snapshot and wait briefly for its receipt.

    Supported actions: tap_button, press_button, release_button, move_stick, wait,
    no_op. Buttons/sticks/axis values and active Player-2 state are revalidated
    inside Home Assistant before MQTT publishing. This is not an arbitrary input API.
    """
    if action not in {
        "tap_button", "press_button", "release_button", "move_stick", "wait", "no_op"
    }:
        raise BridgeError("Unsupported action type.")
    if not client_id or len(client_id) > 64:
        raise BridgeError("A valid client_id from list_game_clients is required.")
    age = _timestamp_age(expected_frame_timestamp)
    if age is None:
        raise BridgeError("expected_frame_timestamp must come from get_game_snapshot.")
    if age < -1.0:
        raise BridgeError("Snapshot timestamp is in the future; fetch a new screenshot.")
    if age > SNAPSHOT_MAX_AGE_S:
        raise BridgeError("Snapshot is older than 10 seconds; fetch a new screenshot.")

    command_id = uuid.uuid4().hex
    data: dict[str, Any] = {
        "client_id": client_id,
        "expected_frame_timestamp": expected_frame_timestamp,
        "command_id": command_id,
        "action": action,
    }
    if button:
        data["button"] = button.upper()
    if stick:
        data["stick"] = stick.lower()
    if x is not None:
        data["x"] = x
    if y is not None:
        data["y"] = y
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    if reason:
        data["reason"] = reason[:200]

    await _ha_request(
        "POST", "/api/services/gaming_assistant/send_game_action", json_body=data
    )

    deadline = time.monotonic() + RESULT_WAIT_S
    while time.monotonic() < deadline:
        try:
            state = await _get_state(ACTION_ENTITY)
            attrs = state.get("attributes") or {}
            result = attrs.get("last_execution_result")
            if isinstance(result, dict) and result.get("command_id") == command_id:
                return json.dumps(
                    {"command_id": command_id, "status": result.get("result", "unknown"), "receipt": result},
                    ensure_ascii=False,
                )
        except BridgeError:
            # The service may succeed before sensor state becomes available.
            pass
        await asyncio.sleep(RESULT_POLL_S)

    return json.dumps(
        {
            "command_id": command_id,
            "status": "published_waiting_for_executor_receipt",
            "note": "Publishing is not proof of execution. Check get_game_status or fetch a fresh snapshot.",
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def stop_game_agent() -> str:
    """Disable Player 2 and request neutral controller inputs immediately."""
    await _ha_request(
        "POST",
        "/api/services/gaming_assistant/set_agent_mode",
        json_body={"enabled": False},
    )
    return "Agent Mode disabled; Home Assistant requested a neutral controller reset."


def main() -> None:
    _validate_configuration()
    mcp.run(transport=TRANSPORT)


if __name__ == "__main__":
    main()
