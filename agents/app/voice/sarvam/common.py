"""Small helpers shared by Sarvam STT and TTS WebSocket adapters."""

import os
from collections.abc import Mapping
from typing import Any, Protocol


class JsonWebSocket(Protocol):
    """Minimal injected WebSocket surface required by the Sarvam adapters."""

    async def send(self, message: str) -> None:
        """Send one text frame to the provider."""
        ...

    async def recv(self) -> str | bytes:
        """Receive one text or binary frame from the provider."""
        ...

    async def close(self) -> None:
        """Close the provider WebSocket connection."""
        ...


def api_key(value: str | None) -> str:
    """Resolve an explicit Sarvam key or the ``SARVAM_API_KEY`` environment value."""
    resolved = value or os.getenv("SARVAM_API_KEY")
    if not resolved:
        raise ValueError("SARVAM_API_KEY is required")
    return resolved


def as_json_object(message: str | bytes) -> dict[str, Any]:
    """Decode a provider frame and require a JSON object payload."""
    import json

    value = json.loads(message)
    if not isinstance(value, dict):
        raise ValueError("Sarvam WebSocket message must be a JSON object")
    return value


def event_name(payload: Mapping[str, Any]) -> str:
    """Return the provider event name from its ``event`` or ``type`` field."""
    value = payload.get("event") or payload.get("type")
    return value if isinstance(value, str) else ""
