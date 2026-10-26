"""Tools shared by every agent that can participate in a voice call."""

from collections.abc import Callable, Sequence
from typing import Any, TypedDict

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool


class AgentRuntimeContext(TypedDict, total=False):
    """Optional callbacks supplied by the application while running an agent."""

    request_hangup: Callable[[str], None]


@tool(return_direct=True)
def hangup_call(
    runtime: ToolRuntime[AgentRuntimeContext, Any],
    goodbye: str,
    reason: str = "The caller requested to end the call.",
) -> str:
    """End the active voice call after speaking a short goodbye.

    Use this when the caller gives a closing statement, asks to end the call,
    or the conversation is complete. Write ``goodbye`` in the same language as
    the current conversation. The voice runtime performs the actual hangup;
    the returned text is spoken before the connection closes.
    """
    goodbye = goodbye.strip()
    if not goodbye:
        raise ValueError("goodbye must contain the closing message to speak")
    context = runtime.context
    request_hangup = context.get("request_hangup") if isinstance(context, dict) else None
    if callable(request_hangup):
        request_hangup(reason)
        return goodbye
    return "Call control is only available during a live voice call."


def get_common_tools() -> Sequence[BaseTool]:
    """Return tools that should be available to every voice-capable agent."""
    return (hangup_call,)


__all__ = ["AgentRuntimeContext", "get_common_tools", "hangup_call"]
