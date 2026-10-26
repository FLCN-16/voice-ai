"""Sarvam realtime speech-to-text provider adapter."""

import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from ..base import BaseSTTModel
from ..events import VoiceEvent, VoiceEventType
from .common import JsonWebSocket, api_key, as_json_object, event_name


class SarvamSTT(BaseSTTModel[dict[str, Any]]):
    """Sarvam Saaras realtime STT WebSocket adapter."""

    def __init__(
        self,
        *,
        session_id: str,
        api_subscription_key: str | None = None,
        websocket: JsonWebSocket | None = None,
        **options: str | bool | int,
    ) -> None:
        """Configure a Sarvam STT session and optional injected WebSocket.

        The network connection is deliberately deferred until ``start`` so
        construction and imports remain safe without opening external I/O.
        """
        super().__init__(session_id=session_id)
        self._api_key = api_key(api_subscription_key)
        self._websocket = websocket
        self._options = {
            "language_code": os.getenv("SARVAM_LANGUAGE_CODE", "auto"),
            **options,
        }

    @property
    def provider(self) -> str:
        """Return the canonical provider name used in normalized events."""
        return "sarvam"

    async def start(self) -> AsyncIterator[VoiceEvent]:
        """Connect to Sarvam, then emit the shared session-start event."""
        self._logger.info(
            "starting Sarvam STT pipeline",
            injected_websocket=self._websocket is not None,
        )
        if self._websocket is None:
            from websockets.asyncio.client import connect

            query = {
                "model": "saaras:v4",
                "encoding": "linear16",
                "sample_rate": 16000,
                **self._options,
            }
            self._websocket = await connect(
                f"wss://api.sarvam.ai/speech-to-text-realtime/ws?{urlencode(query)}",
                additional_headers={
                    "Api-Subscription-Key": self._api_key,
                },
            )
            self._logger.info("Sarvam STT WebSocket connected")
        async for event in super().start():
            yield event

    async def send_audio(self, audio: bytes) -> AsyncIterator[VoiceEvent]:
        """Send one PCM audio frame and report its input size."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam STT WebSocket is not connected")
        self._logger.debug("sending STT audio frame", bytes=len(audio))
        await self._websocket.send(
            json.dumps(
                {
                    "event": "audio_input",
                    "audio": base64.b64encode(audio).decode("ascii"),
                }
            )
        )
        yield VoiceEvent(
            type=VoiceEventType.AUDIO_INPUT,
            data={"bytes": len(audio)},
        )

    async def _send_control(self, event: str) -> AsyncIterator[VoiceEvent]:
        """Send a Sarvam control command and expose a provider notice."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam STT WebSocket is not connected")
        self._logger.debug("sending STT control event", provider_event=event)
        await self._websocket.send(json.dumps({"event": event}))
        yield VoiceEvent.provider_notice("sarvam", f"{event}.sent", {})

    async def speech_start(self) -> AsyncIterator[VoiceEvent]:
        """Tell Sarvam that a user speech segment has started."""
        async for event in self._send_control("speech_start"):
            yield event

    async def speech_end(self) -> AsyncIterator[VoiceEvent]:
        """Tell Sarvam that a user speech segment has ended."""
        async for event in self._send_control("speech_end"):
            yield event

    async def flush(self) -> AsyncIterator[VoiceEvent]:
        """Ask Sarvam to flush buffered STT audio."""
        async for event in self._send_control("flush"):
            yield event

    async def ping(self) -> AsyncIterator[VoiceEvent]:
        """Send a keepalive command to the Sarvam STT session."""
        async for event in self._send_control("ping"):
            yield event

    async def end_session(self) -> AsyncIterator[VoiceEvent]:
        """Ask Sarvam to end its remote STT session."""
        async for event in self._send_control("end"):
            yield event

    async def handle_event(
        self, event: dict[str, Any]
    ) -> AsyncIterator[VoiceEvent]:
        """Map one Sarvam wire event to a canonical application event."""
        name = event_name(event)
        self._logger.debug("mapping Sarvam STT event", provider_event=name)
        if name == "transcript.partial":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.TRANSCRIPT_PARTIAL,
                data=event,
            )
        elif name == "transcript.final":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.TRANSCRIPT_FINAL,
                data=event,
            )
        elif name == "vad.speech_start":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.SPEECH_STARTED,
                data=event,
            )
        elif name == "vad.speech_end":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.SPEECH_ENDED,
                data=event,
            )
        elif name == "session.begin":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.SESSION_STARTED,
                data=event,
            )
        elif name == "session.end":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.SESSION_ENDED,
                data=event,
            )
        elif name == "config.updated":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.CONFIG_UPDATED,
                data=event,
            )
        elif name == "pong":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.KEEPALIVE,
                data=event,
            )
        elif name == "error":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.ERROR,
                data=event,
            )
        else:
            yield VoiceEvent.provider_notice("sarvam", name or "unknown", event)

    async def receive_event(self) -> AsyncIterator[VoiceEvent]:
        """Read one provider frame, decode it, and yield normalized events."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam STT WebSocket is not connected")
        event = as_json_object(await self._websocket.recv())
        self._logger.debug(
            "received Sarvam STT event", provider_event=event_name(event)
        )
        async for normalized in self.handle_event(event):
            yield normalized

    async def stop(self) -> AsyncIterator[VoiceEvent]:
        """Emit the shared end event and close the provider WebSocket."""
        self._logger.info("stopping Sarvam STT pipeline")
        async for event in super().stop():
            yield event
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None
            self._logger.info("Sarvam STT WebSocket closed")
