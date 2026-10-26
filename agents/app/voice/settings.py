"""Small helpers for environment-backed voice settings."""

import os


def duration_setting(name: str, value: float | None, default: float) -> float:
    """Resolve a non-negative duration from an argument or environment."""
    if value is None:
        raw_value = os.getenv(name)
        value = default if raw_value is None else float(raw_value)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value
