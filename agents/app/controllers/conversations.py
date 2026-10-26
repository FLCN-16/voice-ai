"""HTTP endpoints for reading and deleting persisted conversations."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pymongo.errors import PyMongoError

from ..database import ConversationRepository

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Return conversation metadata and ordered messages by ID.

    Database failures are translated into a ``503`` response, while a missing
    document is reported as ``404``.
    """
    repository: ConversationRepository = request.app.state.conversations
    try:
        conversation = await repository.get_conversation(conversation_id)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation storage is unavailable",
        ) from exc

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "conversation_id": conversation["_id"],
        "agent": conversation.get("agent"),
        "messages": conversation.get("messages", []),
        "created_at": conversation.get("created_at"),
        "updated_at": conversation.get("updated_at"),
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    request: Request,
) -> Response:
    """Delete a conversation and return an empty ``204`` response.

    The endpoint distinguishes a missing document from a storage outage so
    clients can decide whether to retry.
    """
    repository: ConversationRepository = request.app.state.conversations
    try:
        deleted = await repository.delete_conversation(conversation_id)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation storage is unavailable",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return Response(status_code=204)
