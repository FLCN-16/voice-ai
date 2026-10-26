"""Application entry point and FastAPI lifecycle configuration."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from .common import configure_logging

configure_logging()

from .controllers import (
    agents_router,
    conversations_router,
    health_router,
    sessions_router,
    voice_router,
)
from .database import ConversationRepository, InMemoryConversationRepository


def _mongodb_enabled() -> bool:
    """Return whether persistent MongoDB storage was explicitly enabled."""
    return os.getenv("MONGODB_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Create shared resources at startup and close them during shutdown.

    The conversation repository is stored on ``app.state`` so every HTTP and
    WebSocket controller uses the same database abstraction for the lifetime
    of the process.
    """
    repository = (
        ConversationRepository()
        if _mongodb_enabled()
        else InMemoryConversationRepository()
    )
    application.state.conversations = repository
    try:
        yield
    finally:
        await repository.close()


app = FastAPI(
    title="Voice AI",
    description="An AI-powered voice assistant",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(agents_router)
app.include_router(conversations_router)
app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(voice_router)
