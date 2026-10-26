"""Session creation endpoint shared by chat and voice clients."""

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents import available_agents

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class SessionCreateRequest(BaseModel):
    """Input required to create a new agent interaction session."""

    agent_name: str
    mode: Literal["chat", "voice"]


@router.post("", status_code=201)
async def create_session(request: SessionCreateRequest) -> dict[str, str]:
    """Create a server-owned ID for a new chat or voice conversation.

    The session ID is also the MongoDB conversation ID. Conversation metadata
    and messages are created lazily when the first exchange is persisted.
    """
    if request.agent_name not in available_agents():
        available = ", ".join(available_agents()) or "none"
        raise HTTPException(
            status_code=404,
            detail=f"Unknown agent '{request.agent_name}'. Available agents: {available}",
        )

    session_id = str(uuid4())
    return {
        "session_id": session_id,
        "conversation_id": session_id,
        "agent": request.agent_name,
        "mode": request.mode,
    }
