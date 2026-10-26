"""Sarvam realtime text-to-speech provider adapter."""

import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from ..base import BaseSSTModel
from ..events import VoiceEvent, VoiceEventType
from .common import JsonWebSocket, api_key, as_json_object, event_name


class SarvamTTS(BaseSSTModel[dict[str, Any]]):
    """Sarvam Bulbul streaming TTS WebSocket adapter."""

    def __init__(
        self,
        *,
        session_id: str,
        api_subscription_key: str | None = None,
        websocket: JsonWebSocket | None = None,
        **options: str | bool | int | float,
    ) -> None:
        """Configure a Sarvam TTS session and optional injected WebSocket."""
        super().__init__(session_id=session_id)
        self._api_key = api_key(api_subscription_key)
        self._websocket = websocket
        self._options = {
            "model": os.getenv("SARVAM_TTS_MODEL", "bulbul:v4-flash"),
            "speaker": os.getenv("SARVAM_TTS_SPEAKER", "shubh"),
            "speech_sample_rate": int(
                os.getenv("SARVAM_TTS_SAMPLE_RATE", "24000")
            ),
            "output_audio_codec": os.getenv(
                "SARVAM_TTS_CODEC", "mp3"
            ),
            "output_audio_bitrate": os.getenv(
                "SARVAM_TTS_BITRATE", "128k"
            ),
            **options,
        }

    @property
    def provider(self) -> str:
        """Return the canonical provider name used in normalized events."""
        return "sarvam"

    async def start(self) -> AsyncIterator[VoiceEvent]:
        """Connect to Sarvam, send synthesis options, and start the session."""
        self._logger.info(
            "starting Sarvam TTS pipeline",
            injected_websocket=self._websocket is not None,
            option_keys=sorted(self._options),
        )
        if self._websocket is None:
            from websockets.asyncio.client import connect

            self._websocket = await connect(
                "wss://api.sarvam.ai/text-to-speech/ws?"
                + urlencode({"send_completion_event": "true"}),
                additional_headers={
                    "Api-Subscription-Key": self._api_key,
                },
            )
            self._logger.info("Sarvam TTS WebSocket connected")
        await self._websocket.send(
            json.dumps({"type": "config", "data": self._options})
        )
        self._logger.debug("Sarvam TTS configuration sent")
        async for event in super().start():
            yield event

    async def send_text(self, text: str) -> AsyncIterator[VoiceEvent]:
        """Send text for synthesis and report the outbound provider message."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam TTS WebSocket is not connected")
        self._logger.debug("sending TTS text", text_length=len(text))
        await self._websocket.send(
            json.dumps({"type": "text", "data": {"text": text}})
        )
        yield VoiceEvent.provider_notice("sarvam", "text.sent", {"text": text})

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield decoded audio bytes from normalized audio output events."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam TTS WebSocket is not connected")
        async for event in self.receive_event():
            if event.type is VoiceEventType.AUDIO_OUTPUT:
                audio = event.data.get("audio")
                if isinstance(audio, str):
                    self._logger.debug(
                        "received TTS audio", encoded_length=len(audio)
                    )
                    yield base64.b64decode(audio)

    async def receive_event(self) -> AsyncIterator[VoiceEvent]:
        """Read one provider frame, decode it, and yield normalized events."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam TTS WebSocket is not connected")
        payload = as_json_object(await self._websocket.recv())
        self._logger.debug(
            "received Sarvam TTS event", provider_event=event_name(payload)
        )
        async for event in self.handle_event(payload):
            yield event

    async def handle_event(
        self, event: dict[str, Any]
    ) -> AsyncIterator[VoiceEvent]:
        """Map Sarvam audio, completion, and error frames to canonical events."""
        name = event_name(event)
        self._logger.debug("mapping Sarvam TTS event", provider_event=name)
        if name == "audio":
            data = event.get("data", {})
            if not isinstance(data, dict):
                data = {}
            audio = data.get("audio")
            self._logger.debug(
                "mapping TTS audio chunk",
                content_type=data.get("content_type"),
                encoded_length=len(audio) if isinstance(audio, str) else 0,
            )
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.AUDIO_OUTPUT,
                data=data,
            )
        elif name == "event":
            data = event.get("data", {})
            if isinstance(data, dict) and data.get("event_type") == "final":
                yield VoiceEvent.from_provider(
                    provider="sarvam",
                    provider_event="event.final",
                    type=VoiceEventType.SYNTHESIS_COMPLETED,
                    data=data,
                )
            else:
                yield VoiceEvent.provider_notice("sarvam", name, event)
        elif name == "error":
            yield VoiceEvent.from_provider(
                provider="sarvam",
                provider_event=name,
                type=VoiceEventType.ERROR,
                data=event,
            )
        else:
            yield VoiceEvent.provider_notice("sarvam", name or "unknown", event)

    async def flush(self) -> None:
        """Ask Sarvam to finish the current text synthesis buffer."""
        self.ensure_started()
        if self._websocket is None:
            raise RuntimeError("Sarvam TTS WebSocket is not connected")
        self._logger.debug("flushing Sarvam TTS buffer")
        await self._websocket.send(json.dumps({"type": "flush", "data": {}}))

    async def stop(self) -> AsyncIterator[VoiceEvent]:
        """Emit the shared end event and close the provider WebSocket."""
        self._logger.info("stopping Sarvam TTS pipeline")
        async for event in super().stop():
            yield event
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None
            self._logger.info("Sarvam TTS WebSocket closed")


SarvamSST = SarvamTTS
