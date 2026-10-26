"""HTTP endpoint for invoking dynamically discovered agents."""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from ..agents import get_agent
from ..database import ConversationRepository

router = APIRouter(prefix="/v1/agent", tags=["agents"])


class AgentQuery(BaseModel):
    """Request body accepted by the synchronous agent query endpoint."""

    messages: list[dict[str, Any]]
    session_id: str | None = Field(
        default=None,
        description="Server-created session ID used as the conversation ID.",
    )

    # Keep accepting the old field while clients migrate to session_id.
    conversation_id: str | None = None


@router.post("/{agent_name}/query")
async def query_agent(
    agent_name: str,
    query: AgentQuery,
    request: Request,
) -> dict[str, Any]:
    """Invoke an agent, persist the exchange, and return its text response.

    The session ID is used directly as the conversation ID. If no session ID
    is supplied, a UUID is generated in Python for backwards compatibility;
    new clients should call ``POST /v1/sessions`` first.
    """
    try:
        agent = get_agent(agent_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if query.session_id and query.conversation_id and query.session_id != query.conversation_id:
        raise HTTPException(
            status_code=422,
            detail="session_id and conversation_id must match when both are provided",
        )
    session_id = query.session_id or query.conversation_id or str(uuid4())
    conversation_id = session_id
    repository: ConversationRepository = request.app.state.conversations
    try:
        history = await repository.get_messages(conversation_id)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation storage is unavailable",
        ) from exc

    result = await agent.ainvoke({"messages": [*history, *query.messages]})
    response = result["messages"][-1]
    response_message = {
        "role": "assistant",
        "content": response.content,
    }
    try:
        await repository.append_messages(
            conversation_id=conversation_id,
            agent_name=agent_name,
            messages=[*query.messages, response_message],
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation storage is unavailable",
        ) from exc

    return {
        "agent": agent_name,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "response": response.content,
    }
