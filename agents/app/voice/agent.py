"""Provider-independent orchestration for one voice WebSocket session.

``VoiceAgent`` fans in client JSON, STT events, and TTS events. Provider
control flow uses canonical ``VoiceEventType`` values (for example
``SPEECH_STARTED``), not Sarvam or ElevenLabs wire names. Persistence is
optional via ``on_messages`` so this class never talks to MongoDB.
"""

import asyncio
import base64
import os
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import uuid4

from ..common import get_logger
from .events import VoiceEvent, VoiceEventType
from .settings import duration_setting as _duration_setting


class VoiceSocket(Protocol):
    """JSON duplex socket; inject a fake in tests instead of FastAPI's."""

    async def receive_json(self) -> Any:
        """Receive and decode the next client JSON message."""
        ...

    async def send_json(self, data: Any) -> None:
        """Serialize and send one JSON message to the client."""
        ...

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the client socket."""
        ...


class VoiceAgent:
    """Run STT, a LangChain agent, and TTS over one client socket.

    Turns are committed after TTS ``SYNTHESIS_COMPLETED``. Barge-in
    (``SPEECH_STARTED``) cancels the in-flight agent task and retains only the
    interrupted user turn. The next turn can then answer the interrupted and
    new user messages together without keeping the abandoned reply.
    """

    def __init__(
        self,
        *,
        agent: Any,
        stt: Any,
        tts: Any,
        socket: VoiceSocket,
        history: list[dict[str, Any]] | None = None,
        on_messages: Any | None = None,
        inactivity_prompt_after: float | None = None,
        inactivity_hangup_after: float | None = None,
        inactivity_prompt: str | None = None,
        hangup_grace_after_synthesis: float | None = None,
        playback_ack_timeout: float | None = None,
    ) -> None:
        """Configure one provider-independent voice session.

        ``history`` supplies prior conversation messages to the agent, while
        ``on_messages`` receives completed user/assistant turns and interrupted
        user messages. This keeps persistence outside the real-time
        coordinator.
        """
        self._agent = agent
        self._stt = stt
        self._tts = tts
        self._socket = socket
        self._logger = get_logger(__name__).bind(
            session_id=getattr(stt, "session_id", None),
            pipeline="voice",
        )
        self._history = history if history is not None else []
        self._on_messages = on_messages
        self._running = True
        self._pending_completion: str | None = None
        self._pending_messages: tuple[dict[str, Any], dict[str, Any]] | None = None
        self._pending_playback_id: str | None = None
        self._pending_synthesis_completed: asyncio.Event | None = None
        self._active_user_message: dict[str, Any] | None = None
        self._active_turn: asyncio.Task[None] | None = None
        # Stale TTS may still emit SYNTHESIS_COMPLETED; drop persist/AGENT_COMPLETED.
        self._discard_next_synthesis_completion = False
        self._hangup_requested = asyncio.Event()
        self._hangup_reason = "Call ended"
        self._inactivity_task: asyncio.Task[None] | None = None
        self._inactivity_prompt_active = False
        self._playback_completed = asyncio.Event()
        self._awaiting_playback_completion: str | None = None
        self._playback_ack_starts_inactivity = True
        self._playback_ack_task: asyncio.Task[None] | None = None
        self._inactivity_prompt_after = _duration_setting(
            "VOICE_INACTIVITY_PROMPT_AFTER_SECONDS",
            inactivity_prompt_after,
            3.0,
        )
        self._inactivity_hangup_after = _duration_setting(
            "VOICE_INACTIVITY_HANGUP_AFTER_SECONDS",
            inactivity_hangup_after,
            5.0,
        )
        self._inactivity_prompt = inactivity_prompt or os.getenv(
            "VOICE_INACTIVITY_PROMPT", "Are you still there?"
        )
        self._hangup_grace_after_synthesis = _duration_setting(
            "VOICE_HANGUP_GRACE_SECONDS",
            hangup_grace_after_synthesis,
            2.5,
        )
        self._playback_ack_timeout = _duration_setting(
            "VOICE_PLAYBACK_ACK_TIMEOUT_SECONDS",
            playback_ack_timeout,
            60.0,
        )
        if self._inactivity_hangup_after <= self._inactivity_prompt_after:
            raise ValueError(
                "VOICE_INACTIVITY_HANGUP_AFTER_SECONDS must be greater than "
                "VOICE_INACTIVITY_PROMPT_AFTER_SECONDS"
            )

    async def run(self) -> None:
        """Start providers, fan in events, and cleanly stop on task completion.

        Three concurrent readers handle client input, STT output, and TTS
        output. If any reader exits, the remaining readers and provider
        sessions are cancelled or stopped in the ``finally`` block.
        """
        self._logger.info(
            "voice pipeline starting", history_messages=len(self._history)
        )
        await self._emit_model_events(self._stt.start())
        await self._emit_model_events(self._tts.start())
        await self._socket.send_json(
            VoiceEvent(
                type=VoiceEventType.SESSION_STARTED,
                data={"session_id": self._stt.session_id},
            ).model_dump()
        )
        await self._arm_inactivity_timeout()
        self._logger.info("voice pipeline started")

        stt_events = asyncio.create_task(
            self._read_stt_events(), name="voice.stt-events"
        )
        tts_events = asyncio.create_task(
            self._read_tts_events(), name="voice.tts-events"
        )
        client_messages = asyncio.create_task(
            self._read_client_messages(), name="voice.client-messages"
        )
        call_control = asyncio.create_task(
            self._wait_for_call_end(), name="voice.call-control"
        )
        try:
            await self._wait_for_tasks(
                stt_events, tts_events, client_messages, call_control
            )
        finally:
            self._logger.info("voice pipeline stopping")
            stt_events.cancel()
            tts_events.cancel()
            client_messages.cancel()
            call_control.cancel()
            await self._cancel_inactivity_timeout()
            await self._cancel_playback_ack_timeout()
            await self._cancel_active_turn()
            await self._emit_model_events(self._tts.stop())
            await self._emit_model_events(self._stt.stop())
            if self._hangup_requested.is_set():
                close_socket = getattr(self._socket, "close", None)
                if close_socket is not None:
                    await close_socket(code=1000, reason=self._hangup_reason[:120])
            self._logger.info("voice pipeline stopped")

    async def _wait_for_call_end(self) -> None:
        """Wait for an agent tool or inactivity watchdog to request hangup."""
        await self._hangup_requested.wait()
        # Keep the provider readers alive during the closing handshake so the
        # final goodbye playback acknowledgement can still arrive.
        active_turn = self._active_turn
        if active_turn is not None and active_turn is not asyncio.current_task():
            try:
                await active_turn
            except asyncio.CancelledError:
                pass
        await self._cancel_playback_ack_timeout()
        if self._awaiting_playback_completion is not None:
            try:
                await asyncio.wait_for(
                    self._playback_completed.wait(),
                    timeout=self._playback_ack_timeout,
                )
            except asyncio.TimeoutError:
                self._logger.warning(
                    "hangup playback acknowledgement timed out",
                    timeout_seconds=self._playback_ack_timeout,
                )
            self._awaiting_playback_completion = None
        else:
            # Covers a hangup requested before TTS had produced a response.
            await asyncio.sleep(self._hangup_grace_after_synthesis)
        self._running = False
        await self._socket.send_json(
            VoiceEvent(
                type=VoiceEventType.CALL_HANGUP,
                data={"reason": self._hangup_reason},
            ).model_dump()
        )

    def _request_hangup(self, reason: str) -> None:
        """Record a hangup request from a tool or the inactivity watchdog."""
        if not self._hangup_requested.is_set():
            self._hangup_reason = reason or "Call ended"
            self._hangup_requested.set()

    async def _cancel_active_turn(self) -> None:
        """Cancel an agent turn while the voice session is shutting down."""
        if self._active_turn is None or self._active_turn.done():
            return
        self._active_turn.cancel()
        try:
            await self._active_turn
        except asyncio.CancelledError:
            pass

    async def _cancel_inactivity_timeout(self) -> None:
        """Cancel the current no-response timer, if one is armed."""
        task = self._inactivity_task
        self._inactivity_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_playback_ack_timeout(self) -> None:
        """Cancel the fallback timer waiting for browser playback completion."""
        task = self._playback_ack_task
        self._playback_ack_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _wait_for_playback_ack_or_timeout(self) -> None:
        """Arm inactivity after playback, with a bounded browser-ack fallback."""
        response_id = self._awaiting_playback_completion
        if response_id is None:
            return
        try:
            await asyncio.wait_for(
                self._playback_completed.wait(), timeout=self._playback_ack_timeout
            )
        except asyncio.TimeoutError:
            if self._awaiting_playback_completion:
                self._logger.warning(
                    "playback completion acknowledgement timed out",
                    timeout_seconds=self._playback_ack_timeout,
                )
        if self._awaiting_playback_completion == response_id:
            self._awaiting_playback_completion = None
            if not self._hangup_requested.is_set():
                await self._arm_inactivity_timeout()

    async def _arm_inactivity_timeout(self) -> None:
        """Start the no-response prompt and hangup countdown."""
        await self._cancel_inactivity_timeout()
        if self._running and not self._hangup_requested.is_set():
            self._inactivity_task = asyncio.create_task(
                self._handle_inactivity_timeout(), name="voice.inactivity"
            )

    async def _handle_inactivity_timeout(self) -> None:
        """Prompt after a pause, then hang up if the caller stays silent."""
        hangup_deadline = (
            asyncio.get_running_loop().time() + self._inactivity_hangup_after
        )
        await asyncio.sleep(self._inactivity_prompt_after)
        if not self._running or self._hangup_requested.is_set():
            return
        self._inactivity_prompt_active = True
        try:
            response_id = str(uuid4())
            self._playback_completed.clear()
            self._awaiting_playback_completion = response_id
            self._playback_ack_starts_inactivity = False
            await self._socket.send_json(
                VoiceEvent(
                    type=VoiceEventType.AGENT_STARTED,
                    data={
                        "text": self._inactivity_prompt,
                        "reason": "inactivity",
                        "response_id": response_id,
                    },
                ).model_dump()
            )
            await self._emit_model_events(self._tts.send_text(self._inactivity_prompt))
            await self._tts.flush()
            try:
                await asyncio.wait_for(
                    self._playback_completed.wait(),
                    timeout=self._playback_ack_timeout,
                )
            except asyncio.TimeoutError:
                self._logger.warning(
                    "inactivity prompt playback acknowledgement timed out",
                    timeout_seconds=self._playback_ack_timeout,
                )
            if self._awaiting_playback_completion == response_id:
                self._awaiting_playback_completion = None
            remaining = hangup_deadline - asyncio.get_running_loop().time()
            if remaining > 0:
                await asyncio.sleep(remaining)
            if self._running and not self._hangup_requested.is_set():
                self._request_hangup("No response from caller")
        finally:
            self._inactivity_prompt_active = False

    async def _wait_for_tasks(self, *tasks: asyncio.Task[None]) -> None:
        """Wait for the first reader to finish and cancel all remaining readers."""
        # Any reader exiting (stop, disconnect, or error) tears the session down.
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            self._logger.info(
                "voice reader completed",
                reader=task.get_name(),
                cancelled=task.cancelled(),
            )
            try:
                task.result()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception(
                    "voice reader failed", reader=task.get_name()
                )
                raise

    async def _read_client_messages(self) -> None:
        """Decode client commands and forward base64 audio to the STT adapter."""
        # Keep the reader alive during hangup so it can deliver the final
        # playback acknowledgement for a goodbye that is still playing.
        while self._running or self._hangup_requested.is_set():
            message = await self._socket.receive_json()
            if not isinstance(message, dict):
                raise ValueError("Voice socket messages must be JSON objects")
            message_type = message.get("type")
            self._logger.debug("client message received", message_type=message_type)
            if message_type == "audio":
                if self._hangup_requested.is_set():
                    continue
                audio = message.get("audio")
                if not isinstance(audio, str):
                    raise ValueError("Audio messages require a base64 audio field")
                audio_bytes = base64.b64decode(audio)
                self._logger.debug("audio frame received", bytes=len(audio_bytes))
                await self._emit_model_events(self._stt.send_audio(audio_bytes))
            elif message_type == "stop":
                self._running = False
                self._logger.info("client requested voice pipeline stop")
            elif message_type == "playback.completed":
                response_id = message.get("response_id")
                if response_id == self._awaiting_playback_completion:
                    starts_inactivity = self._playback_ack_starts_inactivity
                    self._playback_completed.set()
                    await self._cancel_playback_ack_timeout()
                    self._awaiting_playback_completion = None
                    if starts_inactivity and not self._hangup_requested.is_set():
                        await self._arm_inactivity_timeout()
                    self._logger.debug(
                        "client finished playing agent audio", response_id=response_id
                    )
            else:
                raise ValueError(f"Unknown voice socket message type: {message_type}")

    async def _read_stt_events(self) -> None:
        """Forward STT events and start or interrupt agent turns as needed."""
        while self._running:
            async for event in self._stt.receive_event():
                self._logger.debug(
                    "STT event received",
                    event_type=event.type,
                    provider_event=event.provider_event,
                )
                await self._socket.send_json(event.model_dump())
                if self._hangup_requested.is_set():
                    continue
                if event.type is VoiceEventType.SPEECH_STARTED:
                    # Barge-in: drop the current reply before the user finishes speaking.
                    await self._cancel_inactivity_timeout()
                    await self._cancel_playback_ack_timeout()
                    self._playback_completed.clear()
                    self._awaiting_playback_completion = None
                    self._playback_ack_starts_inactivity = True
                    await self._interrupt_agent_turn()
                elif event.type is VoiceEventType.TRANSCRIPT_FINAL:
                    await self._start_agent_turn(event.data.get("text", ""))
                elif event.type is VoiceEventType.SPEECH_ENDED:
                    if (
                        not self._inactivity_prompt_active
                        and self._active_turn is None
                        and self._pending_completion is None
                        and self._awaiting_playback_completion is None
                    ):
                        await self._arm_inactivity_timeout()

    async def _read_tts_events(self) -> None:
        """Forward TTS events and commit turns after synthesis completes."""
        while self._running:
            async for event in self._tts.receive_event():
                self._logger.debug(
                    "TTS event received",
                    event_type=event.type,
                    provider_event=event.provider_event,
                )
                await self._socket.send_json(event.model_dump())
                if event.type is VoiceEventType.SYNTHESIS_COMPLETED:
                    if self._discard_next_synthesis_completion:
                        self._discard_next_synthesis_completion = False
                        self._pending_completion = None
                        self._pending_messages = None
                        self._pending_playback_id = None
                        if self._pending_synthesis_completed is not None:
                            self._pending_synthesis_completed.set()
                            self._pending_synthesis_completed = None
                        continue
                    if self._pending_completion is None:
                        continue
                    pending_messages = self._pending_messages
                    if pending_messages is None:
                        continue
                    completion = self._pending_completion
                    synthesis_completed = self._pending_synthesis_completed
                    self._pending_completion = None
                    self._pending_messages = None
                    # Commit only after the reply was fully synthesized.
                    self._history.append(pending_messages[1])
                    self._active_user_message = None
                    try:
                        if self._on_messages is not None:
                            self._logger.debug("persisting completed voice turn")
                            try:
                                await self._on_messages(pending_messages)
                            except Exception:
                                self._logger.exception("voice turn persistence failed")
                                raise
                        response_id = self._pending_playback_id
                        self._playback_completed.clear()
                        self._awaiting_playback_completion = response_id
                        self._playback_ack_starts_inactivity = True
                        await self._cancel_playback_ack_timeout()
                        await self._socket.send_json(
                            VoiceEvent(
                                type=VoiceEventType.AGENT_COMPLETED,
                                data={
                                    "text": completion,
                                    "response_id": response_id,
                                },
                            ).model_dump()
                        )
                        self._playback_ack_task = asyncio.create_task(
                            self._wait_for_playback_ack_or_timeout(),
                            name="voice.playback-ack-timeout",
                        )
                    finally:
                        if synthesis_completed is not None:
                            synthesis_completed.set()
                            self._pending_synthesis_completed = None

    async def _start_agent_turn(self, text: str) -> None:
        """Launch a background agent turn for a non-empty final transcript."""
        if not text:
            self._logger.debug("empty final transcript ignored")
            return
        self._logger.info("final transcript received", text_length=len(text))
        await self._cancel_inactivity_timeout()
        await self._cancel_playback_ack_timeout()
        self._playback_completed.clear()
        self._awaiting_playback_completion = None
        self._playback_ack_starts_inactivity = True
        self._pending_playback_id = None
        await self._interrupt_agent_turn()
        self._active_user_message = {"role": "user", "content": text}
        self._history.append(self._active_user_message)
        self._active_turn = asyncio.create_task(self._complete_agent_turn(text))

    async def _interrupt_agent_turn(self) -> None:
        """Cancel the in-flight turn and retain only its user message."""
        if self._active_turn is not None:
            self._logger.info("interrupting active agent turn")
            self._active_turn.cancel()
            try:
                await self._active_turn
            except asyncio.CancelledError:
                pass
            self._active_turn = None
        if self._pending_completion is not None:
            self._logger.info("discarding pending synthesized response")
            pending_messages = self._pending_messages
            self._pending_completion = None
            self._pending_messages = None
            self._pending_playback_id = None
            self._discard_next_synthesis_completion = True
        else:
            pending_messages = None
        interrupted_user_message = self._active_user_message
        if interrupted_user_message is None and pending_messages is not None:
            interrupted_user_message = pending_messages[0]
        if interrupted_user_message is not None:
            # The user message is already in in-memory history. Persist only
            # that message; the interrupted assistant response is abandoned.
            if self._on_messages is not None:
                try:
                    await self._on_messages((interrupted_user_message,))
                except Exception:
                    self._logger.exception(
                        "interrupted user message persistence failed"
                    )
                    raise
            self._active_user_message = None

    async def _complete_agent_turn(self, text: str) -> None:
        """Invoke the agent, queue its response for TTS, and flush synthesis.

        Messages remain pending until the TTS reader observes
        ``SYNTHESIS_COMPLETED``; this prevents interrupted replies from being
        persisted as if they had been delivered.
        """
        user_message = self._active_user_message or {
            "role": "user",
            "content": text,
        }
        self._logger.info("agent turn started", text_length=len(text))
        messages = [*self._history]
        if self._active_user_message is None:
            messages.append(user_message)
        try:
            result = await self._agent.ainvoke(
                {"messages": messages},
                context={"request_hangup": self._request_hangup},
            )
        except Exception:
            self._logger.exception("agent turn failed")
            raise
        response = result["messages"][-1]
        content = response.content
        if not isinstance(content, str):
            content = str(content)
        assistant_message = {"role": "assistant", "content": content}
        self._logger.info("agent turn completed", response_length=len(content))
        # Hold messages until SYNTHESIS_COMPLETED so barge-in can drop them.
        self._pending_messages = (user_message, assistant_message)
        self._pending_completion = content
        self._pending_playback_id = str(uuid4())
        synthesis_completed = asyncio.Event()
        self._pending_synthesis_completed = synthesis_completed
        # AGENT_STARTED is post-LLM and pre-TTS, not at transcript time.
        await self._socket.send_json(
            VoiceEvent(
                type=VoiceEventType.AGENT_STARTED,
                data={"text": text, "response_id": self._pending_playback_id},
            ).model_dump()
        )
        await self._emit_model_events(self._tts.send_text(content))
        await self._tts.flush()
        await synthesis_completed.wait()

    async def _emit_model_events(
        self, events: AsyncIterator[VoiceEvent]
    ) -> None:
        """Serialize every provider-normalized event onto the client socket."""
        async for event in events:
            self._logger.debug(
                "voice event emitted",
                event_type=event.type,
                provider=event.provider,
                provider_event=event.provider_event,
            )
            await self._socket.send_json(event.model_dump())
