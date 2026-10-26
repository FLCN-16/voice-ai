"""Canonical events exchanged between voice providers and the application."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class VoiceEventType(StrEnum):
    """Stable event vocabulary used by controllers and voice orchestration."""

    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    AUDIO_INPUT = "audio.input"
    AUDIO_OUTPUT = "audio.output"
    SPEECH_STARTED = "speech.started"
    SPEECH_ENDED = "speech.ended"
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    CONFIG_UPDATED = "config.updated"
    KEEPALIVE = "keepalive"
    SYNTHESIS_COMPLETED = "synthesis.completed"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    CALL_HANGUP = "call.hangup"
    ERROR = "error"
    PROVIDER = "provider"

    VAD_SPEECH_START = SPEECH_STARTED
    VAD_SPEECH_END = SPEECH_ENDED
    PONG = KEEPALIVE
    COMPLETED = AGENT_COMPLETED


class VoiceEvent(BaseModel):
    """Normalized event payload with optional provider diagnostics."""

    type: VoiceEventType
    data: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    provider_event: str | None = None

    @classmethod
    def from_provider(
        cls,
        *,
        provider: str,
        provider_event: str,
        type: VoiceEventType,
        data: dict[str, Any],
    ) -> "VoiceEvent":
        """Create an application event while retaining provider wire metadata."""
        return cls(
            type=type,
            data=data,
            provider=provider,
            provider_event=provider_event,
        )

    @classmethod
    def provider_notice(
        cls, provider: str, provider_event: str, data: dict[str, Any]
    ) -> "VoiceEvent":
        """Wrap an unmapped provider message without treating it as control flow."""
        return cls(
            type=VoiceEventType.PROVIDER,
            data=data,
            provider=provider,
            provider_event=provider_event,
        )
