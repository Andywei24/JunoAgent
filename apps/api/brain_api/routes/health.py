"""Health + readiness endpoints.

`/health` is cheap: process-level liveness only.
`/ready` verifies the database is reachable — used by orchestrators to decide
whether to route traffic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from brain_api.deps import AppSettings, DbSession

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str


class ReadyResponse(HealthResponse):
    database: str


@router.get("/health", response_model=HealthResponse)
def health(settings: AppSettings) -> HealthResponse:
    return HealthResponse(status="ok", app=settings.app_name, env=settings.app_env)


@router.get("/ready", response_model=ReadyResponse)
def ready(db: DbSession, settings: AppSettings) -> ReadyResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"database": "unreachable", "error": str(exc)},
        ) from exc
    return ReadyResponse(
        status="ok", app=settings.app_name, env=settings.app_env, database="ok"
    )
