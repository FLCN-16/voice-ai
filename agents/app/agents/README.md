# Agent development guide

This directory contains dynamically discovered agents. The registry scans
each package directly under ``.

## Required package contract

An agent package must export a factory named after the package:

```text
app/agents/<name>/__init__.py
```

```python
from .agent import get_weather_agent

__all__ = ["get_weather_agent"]
```

The registry discovers that factory as `get_<name>_agent`. The following then
works without changing the registry:

```python
from agents.app.agents import available_agents, get_agent

print(available_agents())
agent = get_agent("weather")
```

Unknown names must raise a clear `ValueError`. Do not add a manual switch to
`registry.py`.

## Recommended layout

```text
app/agents/<name>/
├── __init__.py       # Public factory exports
├── agent.py          # Agent construction and cached getter
├── config.py         # Environment-backed settings
├── system_prompt.md  # Agent system prompt
├── models.py         # Agent-specific typed context/models
└── tools/
    ├── __init__.py   # Tool exports and get_tools()
    └── <tool>.py
```

Use the Falcon package as the reference implementation:

```text
app/agents/falcon/
```

## Factory rules

Expose two levels of construction when useful:

```python
def create_weather_agent(...):
    ...


@lru_cache(maxsize=1)
def get_weather_agent():
    return create_weather_agent()
```

The zero-argument `get_<name>_agent` factory is the registry contract. Keep
credential-dependent model creation lazy so importing the package does not
require an API key.

Use explicit types and existing LangChain abstractions. Prefer configuration
objects and environment variables over hard-coded credentials or provider
settings.

## Tools

Put tools in the agent's `tools/` package. Export them from
`tools/__init__.py` and return them from `get_tools()`:

```python
from collections.abc import Sequence

from langchain_core.tools import BaseTool

from .weather import get_weather


def get_tools() -> Sequence[BaseTool]:
    return (get_weather,)
```

Tools must:

- Have a useful docstring because the model sees the tool description.
- Validate their inputs.
- Return explicit errors rather than silently returning fallback data.
- Avoid reading secrets directly from source code.

## Conversation behavior

The controllers own MongoDB persistence. Agents should focus on reasoning,
tools, and model configuration. Do not duplicate conversation storage inside
an agent unless the feature explicitly requires separate state.

For voice sessions, the orchestration layer sends final transcript messages
to the selected agent and persists the resulting user/assistant turn.

## Voice integration

Voice providers must emit canonical `VoiceEventType` values. Never make the
voice agent depend on a provider-specific event name:

```python
yield VoiceEvent.from_provider(
    provider="elevenlabs",
    provider_event="provider-specific-name",
    type=VoiceEventType.SPEECH_STARTED,
    data=payload,
)
```

Use `provider` and `provider_event` only for diagnostics and observability.
The orchestration layer should consume events such as:

```text
SPEECH_STARTED
SPEECH_ENDED
TRANSCRIPT_PARTIAL
TRANSCRIPT_FINAL
AUDIO_OUTPUT
SYNTHESIS_COMPLETED
ERROR
```

## Adding a new agent checklist

1. Create `..`.
2. Add `__init__.py` with `get_<name>_agent`.
3. Add `agent.py`, configuration, models, and tools as needed.
4. Add the agent's system instructions to `system_prompt.md`.
5. Keep model creation lazy and credentials in environment variables.
6. Confirm `available_agents()` includes the new name.
7. Confirm `get_agent("<name>")` returns the agent.
8. Test the agent's tools and model invocation.
9. Update the root `../../README.md` if the agent adds public configuration or API
   behavior.
