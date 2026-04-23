"""Memory routes.

Exposes the user's memory store: list/create/search/delete. Everything is
user-scoped through :class:`CurrentUserDep` — no cross-user reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain_api.deps import CurrentUserDep, DbSession
from brain_core.enums import MemoryType


router = APIRouter(prefix="/v1/memories", tags=["memories"])


class MemoryItemResponse(BaseModel):
    id: str
    user_id: str
    task_id: str | None
    memory_type: str
    content: str
    summary: str | None
    importance: float
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryHitResponse(BaseModel):
    item: MemoryItemResponse
    score: float


class MemoryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=32_000)
    memory_type: str = Field("long_term")
    task_id: str | None = None
    summary: str | None = Field(None, max_length=400)
    importance: float = Field(0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("", response_model=list[MemoryItemResponse])
def list_memories(
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
    memory_type: str | None = Query(None),
    task_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[MemoryItemResponse]:
    mtype = _parse_memory_type(memory_type)
    service = request.app.state.services.memory
    rows = service.list_for_user(
        db,
        user.id,
        memory_type=mtype,
        task_id=task_id,
        limit=limit,
    )
    return [_item(row) for row in rows]


@router.post("", response_model=MemoryItemResponse, status_code=201)
def create_memory(
    body: MemoryCreateRequest,
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> MemoryItemResponse:
    mtype = _parse_memory_type(body.memory_type)
    if mtype is None:
        raise HTTPException(status_code=422, detail="memory_type required")
    service = request.app.state.services.memory
    try:
        row = service.write(
            db,
            user_id=user.id,
            memory_type=mtype,
            content=body.content,
            task_id=body.task_id,
            summary=body.summary,
            metadata=body.metadata,
            importance=body.importance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _item(row)


@router.get("/search", response_model=list[MemoryHitResponse])
def search_memories(
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
    q: str = Query(..., min_length=1, max_length=2000),
    limit: int = Query(5, ge=1, le=50),
    memory_type: str | None = Query(None),
    task_id: str | None = Query(None),
) -> list[MemoryHitResponse]:
    mtype = _parse_memory_type(memory_type)
    service = request.app.state.services.memory
    hits = service.search(
        db,
        user_id=user.id,
        query=q,
        limit=limit,
        memory_type=mtype,
        task_id=task_id,
    )
    db.commit()  # persist the memory.retrieved event
    return [MemoryHitResponse(item=_item(h.item), score=h.score) for h in hits]


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str,
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> None:
    service = request.app.state.services.memory
    from brain_db.repositories import MemoryRepository

    item = MemoryRepository(db).get(memory_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="memory not found")
    service.delete(db, memory_id)
    db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_memory_type(value: str | None) -> MemoryType | None:
    if value is None:
        return None
    try:
        return MemoryType(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid memory_type '{value}'; "
            f"expected one of {[m.value for m in MemoryType]}",
        ) from exc


def _item(row) -> MemoryItemResponse:
    meta = dict(row.meta or {})
    # Don't leak the raw embedding vector to API clients.
    meta.pop("embedding", None)
    return MemoryItemResponse(
        id=row.id,
        user_id=row.user_id,
        task_id=row.task_id,
        memory_type=row.memory_type,
        content=row.content,
        summary=row.summary,
        importance=float(row.importance or 0.0),
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=meta,
    )
