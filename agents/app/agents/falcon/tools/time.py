"""Time-related tools available to Falcon."""

from datetime import UTC, datetime

from langchain_core.tools import tool


@tool
def get_current_time() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()
