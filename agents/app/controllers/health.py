"""Health endpoint for process status and agent discovery visibility."""

from fastapi import APIRouter

from ..agents import available_agents

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    """Return a lightweight readiness response and available agent names."""
    return {"status": "ok", "agents": available_agents()}
