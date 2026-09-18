"""FastAPI application for the GridWise LLM Energy Optimizer.

Exposes the two endpoints required by the BUP CSE Fest 2026 preliminary round:

* ``GET  /health``          - readiness probe returning ``{"status": "ok"}``.
* ``POST /optimize-energy`` - operator-note interpretation plus the optimized
  24-hour energy schedule.

Every failure mode is mapped onto a controlled JSON error: malformed JSON and
structurally invalid bodies return 400, semantically invalid scenarios return
422, and unexpected internal failures return a generic 500 that never leaks a
stack trace, a configuration value or a credential.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings, load_settings
from app.llm_interpreter import LLMInterpreter
from app.models import OptimizeResponse, ScenarioRequest
from app.optimizer import OptimizationError
from app.pipeline import optimize
from app.validator import PlanValidationError

LOGGER = logging.getLogger("gridwise")

#: Reject oversized bodies before they reach the parser. A legitimate scenario
#: is a few kilobytes, so this is generous while still bounding the work an
#: unauthenticated caller can trigger.
MAX_REQUEST_BYTES = 256 * 1024


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _error(status_code: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"type": error_type, "message": message}})


def _is_malformed_body(raw: bytes, exc: RequestValidationError) -> bool:
    """True when the body could not be parsed at all, rather than failing schema rules.

    An empty body and an unparsable body are client errors (400); a body that
    parses but does not match the schema is a validation error (422).
    """
    if not raw.strip():
        return True
    return any(error.get("type") in {"json_invalid", "json_type"} for error in exc.errors())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare shared resources once, and release them on shutdown."""
    settings: Settings = app.state.settings
    _configure_logging(settings.log_level)
    interpreter = LLMInterpreter(settings)
    await interpreter.warmup()
    app.state.interpreter = interpreter
    LOGGER.info(
        "GridWise service %s ready (interpreter: %s)",
        __version__,
        settings.model_label if settings.llm_available else "deterministic fallback only",
    )
    try:
        yield
    finally:
        await interpreter.aclose()
        LOGGER.info("GridWise service stopped")


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

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
                return _error(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "payload_too_large",
                    f"request body must not exceed {MAX_REQUEST_BYTES} bytes",
                )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        try:
            raw_body = await request.body()
        except Exception:  # pragma: no cover - body already consumed or unreadable
            raw_body = b""
        malformed = _is_malformed_body(raw_body, exc)
        details = [
            {"field": ".".join(str(part) for part in error.get("loc", ())), "message": error.get("msg", "")}
            for error in exc.errors()[:10]
        ]
        LOGGER.info("rejected request: %s", details)
        return _error(
            status.HTTP_400_BAD_REQUEST if malformed else status.HTTP_422_UNPROCESSABLE_ENTITY,
            "malformed_json" if malformed else "invalid_request",
            "request body is not valid JSON" if malformed else "request body failed schema validation",
        )

    @app.exception_handler(OptimizationError)
    async def handle_optimization_error(request: Request, exc: OptimizationError) -> JSONResponse:
        LOGGER.warning("scenario is not solvable: %s", exc)
        return _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "infeasible_scenario",
            "no schedule satisfies the supplied scenario and operator directives",
        )

    @app.exception_handler(PlanValidationError)
    async def handle_plan_error(request: Request, exc: PlanValidationError) -> JSONResponse:
        LOGGER.error("produced schedule failed validation: %s", exc)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "invalid_schedule",
            "the service could not produce a schedule that satisfies every constraint",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("unhandled error while serving %s", request.url.path)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "the service encountered an unexpected internal error",
        )

    @app.get("/health", summary="Readiness probe", tags=["system"])
    async def health() -> dict[str, str]:
        """Readiness endpoint polled by the judging harness."""
        return {"status": "ok"}

    @app.post(
        "/optimize-energy",
        response_model=OptimizeResponse,
        summary="Interpret operator notes and optimize the 24-hour schedule",
        tags=["optimization"],
    )
    async def optimize_energy(payload: ScenarioRequest, request: Request) -> OptimizeResponse:
        """Interpret every operator note, apply the directives, and return a valid plan."""
        result = await optimize(payload, request.app.state.interpreter)
        LOGGER.info(
            "scenario %s solved: %s directive(s), %.2f kWh, %.2f BDT, source=%s%s",
            payload.scenario_id,
            len(result.response.directive_interpretation),
            result.response.total_grid_kwh,
            result.response.total_cost_bdt,
            result.interpreter_source,
            " (degraded)" if result.degraded else "",
        )
        return result.response

    return app


app = create_app()
