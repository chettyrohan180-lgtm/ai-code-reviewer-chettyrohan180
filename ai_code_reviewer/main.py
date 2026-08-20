"""
main.py — FastAPI Application Entry Point
==========================================
Bootstraps the FastAPI application, configures structured logging,
mounts all routers, and exposes a health-check endpoint.

Run locally with:
    uvicorn ai_code_reviewer.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_code_reviewer.config import get_settings
from ai_code_reviewer.webhook import router as webhook_router

# ── Logging Setup ────────────────────────────────────────────────────────────
# Use a structured format so log lines are easy to grep in prod.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Lifespan: startup / shutdown hooks ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Runs once at startup and once at shutdown.
    Use this to warm caches, open DB connections, etc.
    """
    settings = get_settings()
    logger.info(
        "AI Code Reviewer starting | env=%s | app_id=%s",
        settings.app_env,
        settings.github_app_id,
    )
    yield  # ← application runs here
    logger.info("AI Code Reviewer shutting down")


# ── Application Factory ──────────────────────────────────────────────────────

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Autonomous AI Code Reviewer",
        description=(
            "GitHub App webhook listener that triggers an LLM-powered "
            "multi-agent code review pipeline on every pull request."
        ),
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────
    # Allow GitHub's IP ranges in production; open in dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # Tighten to GitHub IP blocks in prod
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(webhook_router)

    # ── Health Check ──────────────────────────────────────────────────────
    @app.get("/health", tags=["Health"], summary="Liveness probe")
    async def health() -> dict:
        """Simple liveness probe — returns 200 if the server is up."""
        return {
            "status": "healthy",
            "env": settings.app_env,
            "app_id": settings.github_app_id,
        }

    return app


# ── Singleton app instance (used by uvicorn) ─────────────────────────────────
app = create_app()
