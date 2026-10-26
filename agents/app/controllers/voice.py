"""WebSocket route for one streaming voice session.

This controller stays thin: it looks up the requested agent, loads
conversation history, and hands the accepted socket to ``VoiceAgent``.
Persistence stays here via ``on_messages`` so individual agents never
talk to MongoDB. Provider adapters (Sarvam STT/TTS) share one
conversation-scoped ``session_id`` on session events; control flow uses
canonical ``VoiceEventType`` values inside ``VoiceAgent``.
"""

from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pymongo.errors import PyMongoError

from ..agents import get_agent
from ..common import get_logger
from ..database import ConversationRepository
from ..voice import SarvamSTT, SarvamTTS, VoiceAgent

router = APIRouter(prefix="/v1/voice", tags=["voice"])
logger = get_logger(__name__)


@router.websocket("/{agent_name}")
async def voice_session_without_id(
    websocket: WebSocket,
    agent_name: str,
) -> None:
    """Create a session in Python and start a voice socket in one request."""
    await _run_voice_session(websocket, agent_name, str(uuid4()))


@router.websocket("/{agent_name}/{session_id}")
async def voice_session(
    websocket: WebSocket,
    agent_name: str,
    session_id: str,
) -> None:
    """Run a duplex voice session for an existing server-created session.

    The handshake is accepted before agent lookup so the client can receive a
    JSON error instead of a silent WebSocket rejection. Unknown agents close
    with 1008 (policy); unexpected runtime failures close with 1011.

    Args:
        websocket: JSON audio frames in; canonical VoiceEvent payloads out.
        agent_name: Dynamically discovered agent package name.
        session_id: Server-created ID that is also the MongoDB conversation ID.
    """
    await _run_voice_session(websocket, agent_name, session_id)


async def _run_voice_session(
    websocket: WebSocket,
    agent_name: str,
    session_id: str,
) -> None:
    """Run the shared voice orchestration flow for one session ID."""
    session_logger = logger.bind(
        agent=agent_name,
        session_id=session_id,
        pipeline="voice",
    )
    # Accept first so lookup and runtime errors can be returned as structured
    # WebSocket messages instead of appearing as handshake failures.
    await websocket.accept()
    session_logger.info("voice WebSocket accepted")
    try:
        agent = get_agent(agent_name)
    except ValueError as exc:
        session_logger.warning("unknown voice agent", error=str(exc))
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1008)
        return

    # Load history before creating the orchestrator; the orchestrator owns only
    # real-time coordination and receives persistence through this callback.
    repository: ConversationRepository = websocket.app.state.conversations
    # The server-created session ID is shared by STT, TTS, and persistence.
    try:
        history = await repository.get_messages(session_id)
    except PyMongoError:
        session_logger.exception("conversation history unavailable")
        await websocket.send_json(
            {"type": "error", "message": "Conversation storage is unavailable"}
        )
        await websocket.close(code=1011, reason="Conversation storage unavailable")
        return
    session_logger.info(
        "conversation history loaded", history_messages=len(history)
    )
    voice_agent = VoiceAgent(
        agent=agent,
        stt=SarvamSTT(session_id=session_id),
        tts=SarvamTTS(session_id=session_id),
        socket=websocket,
        history=history,
        on_messages=lambda messages: repository.append_messages(
            conversation_id=session_id,
            agent_name=agent_name,
            messages=messages,
        ),
    )
    try:
        await voice_agent.run()
    except WebSocketDisconnect:
        # Client hangup is the normal end of a session.
        session_logger.info("voice WebSocket disconnected")
        return
    except Exception as exc:
        session_logger.exception("voice session failed")
        await websocket.send_json(
            {"type": "error", "message": "Voice session failed"}
        )
        # Close reasons are capped at 123 bytes; send a truncated hint only.
        await websocket.close(code=1011, reason=str(exc)[:120])

