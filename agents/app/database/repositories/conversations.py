"""Persistence operations for conversation documents."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import PyMongoError

from ..dbs import MongoDatabase
from ..models import ConversationDocument, MessageDocument

__all__ = [
    "ConversationRepository",
    "InMemoryConversationRepository",
    "PyMongoError",
]


class InMemoryConversationRepository:
    """Store conversations in process memory when MongoDB is disabled."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationDocument] = {}

    async def get_messages(self, conversation_id: str) -> list[MessageDocument]:
        """Return a copy of the conversation's messages."""
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return []
        return [dict(message) for message in conversation.get("messages", [])]

    async def get_conversation(
        self, conversation_id: str
    ) -> ConversationDocument | None:
        """Return a copy of a conversation, if it exists."""
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return None
        return {
            **conversation,
            "messages": [
                dict(message) for message in conversation.get("messages", [])
            ],
        }

    async def append_messages(
        self,
        *,
        conversation_id: str,
        agent_name: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        """Append messages and create the conversation when needed."""
        if not messages:
            return

        now = datetime.now(UTC)
        conversation = self._conversations.setdefault(
            conversation_id,
            {
                "_id": conversation_id,
                "agent": agent_name,
                "messages": [],
                "created_at": now,
                "updated_at": now,
            },
        )
        conversation["agent"] = agent_name
        conversation["updated_at"] = now
        conversation.setdefault("messages", []).extend(
            dict(message) for message in messages
        )

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and report whether it existed."""
        return self._conversations.pop(conversation_id, None) is not None

    async def close(self) -> None:
        """Release the in-memory repository contents."""
        self._conversations.clear()


class ConversationRepository:
    """Provide conversation CRUD operations over the database abstraction."""

    def __init__(self, database: MongoDatabase | None = None) -> None:
        """Use the supplied database or create the default MongoDB adapter."""
        self._database = database or MongoDatabase()

    async def get_messages(self, conversation_id: str) -> list[MessageDocument]:
        """Return only the message history for a conversation.

        An absent conversation is treated as an empty history so callers can
        begin a new conversation without a separate existence check.
        """
        collection = await self._database.conversations()
        document = await collection.find_one(
            {"_id": conversation_id},
            {"messages": 1},
        )
        if document is None:
            return []
        return list(document.get("messages", []))

    async def get_conversation(
        self, conversation_id: str
    ) -> ConversationDocument | None:
        """Fetch the complete conversation document, if it exists."""
        collection = await self._database.conversations()
        document = await collection.find_one({"_id": conversation_id})
        if document is None:
            return None
        return document

    async def append_messages(
        self,
        *,
        conversation_id: str,
        agent_name: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        """Append messages and upsert conversation metadata atomically.

        Timestamps are generated once for the operation; ``created_at`` is
        written only for a new document while ``updated_at`` changes each time.
        """
        if not messages:
            return

        now = datetime.now(UTC)
        collection = await self._database.conversations()
        await collection.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "agent": agent_name,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
                "$push": {
                    "messages": {"$each": [dict(message) for message in messages]},
                },
            },
            upsert=True,
        )

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete one conversation and report whether a document was removed."""
        collection = await self._database.conversations()
        result = await collection.delete_one({"_id": conversation_id})
        return result.deleted_count == 1

    async def close(self) -> None:
        """Release the underlying database client."""
        await self._database.close()
