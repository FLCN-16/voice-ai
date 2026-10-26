"""Factory functions for the Falcon LangChain agent."""

import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from ..common_tools import AgentRuntimeContext
from .config import FalconSettings
from .tools import get_tools


def create_falcon_agent(
    *,
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool] | None = None,
    settings: FalconSettings | None = None,
) -> Any:
    """Create a Falcon agent with optional model, tool, and setting overrides.

    The default model and prompt are resolved lazily from environment-backed
    settings, so importing this module does not require provider credentials.
    """
    resolved_settings = settings or FalconSettings.from_environment()
    chat_model = (
        model
        if isinstance(model, BaseChatModel)
        else ChatOpenAI(
            model=model or resolved_settings.model,
            api_key=os.getenv("SARVAM_API_KEY"),
            # ChatOpenAI appends /chat/completions to this base URL.
            base_url="https://api.sarvam.ai/v2",
        )
    )

    return create_agent(
        model=chat_model,
        tools=list(tools) if tools is not None else get_tools(),
        system_prompt=resolved_settings.system_prompt,
        context_schema=AgentRuntimeContext,
    )


@lru_cache(maxsize=1)
def get_falcon_agent() -> Any:
    """Create and cache the default Falcon agent on first use."""
    return create_falcon_agent()
