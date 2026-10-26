"""Environment-backed configuration for the Falcon agent."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_system_prompt() -> str:
    """Load Falcon's default system prompt from its agent package."""
    return (
        Path(__file__)
        .with_name("system_prompt.md")
        .read_text(encoding="utf-8")
        .strip()
    )


@dataclass(frozen=True)
class FalconSettings:
    """Immutable model and system-prompt settings for Falcon."""

    model: str = "sarvam-105b"
    system_prompt: str = field(default_factory=_load_system_prompt)

    @classmethod
    def from_environment(cls) -> "FalconSettings":
        """Build settings from environment variables with safe defaults."""
        return cls(
            model=os.getenv("FALCON_MODEL", cls.model),
            system_prompt=os.getenv("FALCON_SYSTEM_PROMPT", _load_system_prompt()),
        )
