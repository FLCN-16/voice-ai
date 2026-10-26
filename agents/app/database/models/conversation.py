"""Typed document shapes stored in the conversations collection."""

from datetime import datetime
from typing import Any, TypedDict


class MessageDocument(TypedDict, total=False):
    """A chat message stored as part of a conversation document."""

    role: str
    content: Any


class ConversationDocument(TypedDict, total=False):
    """MongoDB document containing conversation metadata and message history."""

    _id: str
    agent: str
    messages: list[MessageDocument]
    created_at: datetime
    updated_at: datetime
