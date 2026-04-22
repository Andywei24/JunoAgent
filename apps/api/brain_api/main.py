"""FastAPI application factory.

Importable as `brain_api.main:app` by uvicorn; also exposes `create_app()` so
tests can build isolated instances.
"""

from __future__ import annotations

from fastapi import FastAPI

from brain_api.config import Settings, get_settings
from brain_api.logging_setup import configure_logging, get_logger
from brain_api.middleware import RequestContextMiddleware
from brain_api.routes.health import router as health_router
from brain_api.routes.tasks import router as tasks_router
from brain_api.services import build_services
from brain_db.session import init_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        level=settings.log_level,
        fmt=settings.log_format,
        app=settings.app_name,
        env=settings.app_env,
    )
    log = get_logger("brain_api")
    log.info("app.starting", app=settings.app_name, env=settings.app_env)

    init_engine(settings.database_url)

    app = FastAPI(
        title="Brain Agent Platform",
        version="0.1.0",
        description="Core orchestration, planning, and workflow engine.",
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(tasks_router)

    # Process-wide service container (LLM, prompts, orchestrator, runner).
    app.state.services = build_services(settings)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        app.state.services.runner.shutdown(wait=True)

    return app


app = create_app()
