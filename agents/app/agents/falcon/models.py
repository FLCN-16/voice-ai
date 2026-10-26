"""Data models used to carry Falcon request context."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FalconContext:
    """Immutable request-scoped context available to agent integrations."""

    user_id: str | None = None
    conversation_id: str | None = None
