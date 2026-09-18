"""FastAPI application for the GridWise LLM Energy Optimizer.

Exposes the two endpoints required by the BUP CSE Fest 2026 preliminary round:

* ``GET  /health``          - readiness probe.
* ``POST /optimize-energy`` - operator-note interpretation plus the optimized
  24-hour energy schedule.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import Settings, load_settings

LOGGER = logging.getLogger("gridwise")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare shared resources once, and release them on shutdown."""
    settings: Settings = app.state.settings
    _configure_logging(settings.log_level)
    LOGGER.info(
        "GridWise service %s starting (interpreter model: %s)",
        __version__,
        settings.model_label if settings.llm_available else "disabled",
    )
    yield
    LOGGER.info("GridWise service stopping")


def create_app() -> FastAPI:
    """Application factory used by uvicorn and by the test suite."""
    app = FastAPI(
        title="GridWise LLM Energy Optimizer",
        description=(
            "Interprets natural-language campus operator notes into structured "
            "directives with a language model, validates them deterministically, "
            "and solves a cost-minimizing 24-hour energy schedule."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = load_settings()

    @app.get("/health", summary="Readiness probe", tags=["system"])
    async def health() -> dict[str, str]:
        """Readiness endpoint polled by the judging harness."""
        return {"status": "ok"}

    return app


app = create_app()
