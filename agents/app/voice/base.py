"""Abstract contracts shared by streaming voice provider adapters."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Generic, TypeVar

from ..common import get_logger
from .events import VoiceEvent

ProviderEvent = TypeVar("ProviderEvent")


class BaseVoiceModel(ABC, Generic[ProviderEvent]):
    """Common lifecycle and event contract for streaming voice providers."""

    def __init__(self, *, session_id: str) -> None:
        """Create an idle provider session identified by ``session_id``."""
        self.session_id = session_id
        self._started = False
        self._logger = get_logger(type(self).__name__).bind(
            provider=self.provider,
            session_id=session_id,
        )

    @property
    @abstractmethod
    def provider(self) -> str:
        """Return the provider identifier, for example ``elevenlabs``."""

    async def start(self) -> AsyncIterator[VoiceEvent]:
        """Mark the session active and emit its canonical start event.

        Concrete adapters establish their provider connection before delegating
        here, allowing this base implementation to own common lifecycle state.
        """
        if self._started:
            raise RuntimeError("Voice model session is already started")
        self._started = True
        self._logger.info("provider session started")
        yield VoiceEvent(
            type="session.started",
            data={"session_id": self.session_id, "provider": self.provider},
        )

    async def stop(self) -> AsyncIterator[VoiceEvent]:
        """Mark an active session idle and emit its canonical end event."""
        if not self._started:
            return
        self._started = False
        self._logger.info("provider session stopped")
        yield VoiceEvent(
            type="session.ended",
            data={"session_id": self.session_id, "provider": self.provider},
        )

    @abstractmethod
    async def handle_event(self, event: ProviderEvent) -> AsyncIterator[VoiceEvent]:
        """Translate one provider event into normalized application events."""

    def ensure_started(self) -> None:
        """Raise when an operation requires an active provider session."""
        if not self._started:
            raise RuntimeError("Voice model session has not been started")


class BaseSTTModel(BaseVoiceModel[ProviderEvent], ABC):
    """Base contract for speech-to-text streaming adapters."""

    @abstractmethod
    async def send_audio(self, audio: bytes) -> AsyncIterator[VoiceEvent]:
        """Send an audio chunk and yield transcript/provider events."""


class BaseSSTModel(BaseVoiceModel[ProviderEvent], ABC):
    """Base contract for speech streaming/synthesis adapters."""

    @abstractmethod
    async def send_text(self, text: str) -> AsyncIterator[VoiceEvent]:
        """Send text and yield audio/provider events."""

    @abstractmethod
    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield audio chunks received from the provider."""
