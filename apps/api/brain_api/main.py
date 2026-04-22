"""FastAPI application factory.

Importable as `brain_api.main:app` by uvicorn; also exposes `create_app()` so
tests can build isolated instances.
"""

from __future__ import annotations

from pathlib import Path

from brain_db.session import init_engine
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from brain_api.config import Settings, get_settings
from brain_api.logging_setup import configure_logging, get_logger
from brain_api.middleware import RequestContextMiddleware
from brain_api.routes.health import router as health_router
from brain_api.routes.tasks import router as tasks_router
from brain_api.services import build_services


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

    console_dir = Path(__file__).resolve().parents[3] / "apps" / "console"
    if console_dir.exists():
        app.mount("/console", StaticFiles(directory=console_dir, html=True), name="console")

        @app.get("/", include_in_schema=False)
        def _console_redirect() -> RedirectResponse:
            return RedirectResponse(url="/console/")

    # Process-wide service container (LLM, prompts, orchestrator, runner).
    app.state.services = build_services(settings)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        app.state.services.runner.shutdown(wait=True)

    return app


app = create_app()
