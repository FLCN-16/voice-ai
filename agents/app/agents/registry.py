"""Dynamic discovery and construction of agent packages."""

import importlib
import pkgutil
from functools import lru_cache
from typing import Any, Callable

AgentFactory = Callable[[], Any]


@lru_cache(maxsize=None)
def _factories() -> dict[str, AgentFactory]:
    """Discover and cache ``get_<name>_agent`` factories under ``app.agents``.

    Only subpackages with a callable factory are exposed. Caching keeps module
    discovery deterministic and avoids repeating imports for every request.
    """
    factories: dict[str, AgentFactory] = {}
    package = importlib.import_module(__package__)

    for module_info in pkgutil.iter_modules(package.__path__):
        if not module_info.ispkg or module_info.name.startswith("_"):
            continue

        name = module_info.name
        module = importlib.import_module(f"{package.__name__}.{name}")
        factory = getattr(module, f"get_{name}_agent", None)
        if factory is not None and callable(factory):
            factories[name] = factory

    return factories


def available_agents() -> tuple[str, ...]:
    """Return discovered agent names in stable alphabetical order."""
    return tuple(sorted(_factories()))


def get_agent(name: str) -> Any:
    """Create the named agent or raise a message listing valid agent names."""
    factory = _factories().get(name)
    if factory is None:
        available = ", ".join(available_agents()) or "none"
        raise ValueError(f"Unknown agent '{name}'. Available agents: {available}")
    return factory()
