"""Async MongoDB connection and collection access."""

import os
from typing import Any

from pymongo import AsyncMongoClient


class MongoDatabase:
    """Own the lazy MongoDB client used by conversation repositories."""

    def __init__(
        self,
        *,
        uri: str | None = None,
        database: str | None = None,
        collection: str | None = None,
    ) -> None:
        """Store connection settings without opening a network connection.

        Explicit arguments take precedence over environment variables, which
        keeps the class easy to configure in tests and local deployments.
        """
        self._uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self._database_name = database or os.getenv("MONGODB_DATABASE", "voice_ai")
        self._collection_name = collection or os.getenv(
            "MONGODB_COLLECTION", "conversations"
        )
        self._client: AsyncMongoClient[dict[str, Any]] | None = None

    async def connect(self) -> None:
        """Create the client once and verify connectivity with a ping."""
        if self._client is None:
            self._client = AsyncMongoClient(self._uri)
            await self._client.admin.command("ping")

    async def conversations(self) -> Any:
        """Return the configured conversations collection after connecting."""
        await self.connect()
        assert self._client is not None
        return self._client[self._database_name][self._collection_name]

    async def close(self) -> None:
        """Close the MongoDB client and make the object reusable."""
        if self._client is not None:
            await self._client.close()
            self._client = None
