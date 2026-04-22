"""Task routes: create, fetch, list steps/events, SSE event stream.

Task creation submits the task id to the in-process runner. Clients then
observe progress via GET endpoints or SSE.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from brain_api.deps import CurrentUserDep, DbSession
from brain_core.enums import TaskStatus
from brain_db.repositories import (
    EventRepository,
    StepRepository,
    TaskRepository,
)


router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    priority: int = 0
    budget_limit: dict[str, Any] = Field(default_factory=dict)


class TaskSummary(BaseModel):
    id: str
    user_id: str
    status: str
    goal: str
    priority: int
    risk_level: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TaskDetail(TaskSummary):
    parsed_goal: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None
    failure_reason: str | None = None
    budget_limit: dict[str, Any] = Field(default_factory=dict)
    budget_used: dict[str, Any] = Field(default_factory=dict)


class StepItem(BaseModel):
    id: str
    task_id: str
    name: str
    description: str | None
    status: str
    sequence_order: int
    required_capability: str | None
    selected_tool_id: str | None
    risk_level: str
    approval_required: bool
    input_payload: dict[str, Any] | None
    output_payload: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class EventItem(BaseModel):
    id: str
    sequence: int
    task_id: str | None
    step_id: str | None
    event_type: str
    payload: dict[str, Any]
    actor_type: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def create_task(
    body: CreateTaskRequest,
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> TaskDetail:
    tasks = TaskRepository(db)
    task = tasks.create(
        user_id=user.id,
        goal=body.goal,
        session_id=body.session_id,
        priority=body.priority,
        budget_limit=body.budget_limit,
    )
    # Commit before handing off to the background runner so the worker sees the row.
    db.commit()

    services = request.app.state.services
    services.runner.submit(task.id)

    return _task_detail(task)


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, db: DbSession, user: CurrentUserDep) -> TaskDetail:
    task = _require_user_task(db, task_id, user.id)
    return _task_detail(task)


@router.get("", response_model=list[TaskSummary])
def list_tasks(
    db: DbSession, user: CurrentUserDep, limit: int = Query(50, ge=1, le=200)
) -> list[TaskSummary]:
    rows = TaskRepository(db).list_for_user(user.id, limit=limit)
    return [_task_summary(t) for t in rows]


@router.get("/{task_id}/steps", response_model=list[StepItem])
def list_steps(
    task_id: str, db: DbSession, user: CurrentUserDep
) -> list[StepItem]:
    _require_user_task(db, task_id, user.id)
    rows = StepRepository(db).list_for_task(task_id)
    return [_step_item(s) for s in rows]


@router.get("/{task_id}/events", response_model=list[EventItem])
def list_events(
    task_id: str,
    db: DbSession,
    user: CurrentUserDep,
    after_sequence: int | None = Query(None, ge=0),
    limit: int = Query(500, ge=1, le=5000),
) -> list[EventItem]:
    _require_user_task(db, task_id, user.id)
    rows = EventRepository(db).list_for_task(
        task_id, after_sequence=after_sequence, limit=limit
    )
    return [_event_item(e) for e in rows]


@router.get("/{task_id}/events/stream")
def stream_events(
    task_id: str,
    request: Request,
    user: CurrentUserDep,
    after_sequence: int | None = Query(None, ge=0),
) -> StreamingResponse:
    # Authorize against the current user, then hand off to a long-lived loop
    # that opens its own per-iteration DB sessions.
    factory = request.app.state.services.session_factory
    with factory() as db:
        task = TaskRepository(db).get(task_id)
        if task is None or task.user_id != user.id:
            raise HTTPException(status_code=404, detail="task not found")

    generator = _event_stream(task_id, after_sequence or 0, factory)
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/{task_id}/result")
def get_result(task_id: str, db: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    task = _require_user_task(db, task_id, user.id)
    return {
        "task_id": task.id,
        "status": task.status,
        "final_output": task.final_output,
        "failure_reason": task.failure_reason,
    }


@router.post("/{task_id}/cancel", response_model=TaskDetail)
def cancel_task(
    task_id: str, db: DbSession, user: CurrentUserDep
) -> TaskDetail:
    task = _require_user_task(db, task_id, user.id)
    current = TaskStatus(task.status)
    if current in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        return _task_detail(task)
    TaskRepository(db).transition(task, TaskStatus.CANCELLED)
    db.commit()
    return _task_detail(task)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_user_task(db, task_id: str, user_id: str):
    task = TaskRepository(db).get(task_id)
    if task is None or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _task_summary(task) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        user_id=task.user_id,
        status=task.status,
        goal=task.goal,
        priority=task.priority,
        risk_level=task.risk_level,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


def _task_detail(task) -> TaskDetail:
    return TaskDetail(
        id=task.id,
        user_id=task.user_id,
        status=task.status,
        goal=task.goal,
        priority=task.priority,
        risk_level=task.risk_level,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        parsed_goal=task.parsed_goal,
        final_output=task.final_output,
        failure_reason=task.failure_reason,
        budget_limit=task.budget_limit or {},
        budget_used=task.budget_used or {},
    )


def _step_item(step) -> StepItem:
    return StepItem(
        id=step.id,
        task_id=step.task_id,
        name=step.name,
        description=step.description,
        status=step.status,
        sequence_order=step.sequence_order,
        required_capability=step.required_capability,
        selected_tool_id=step.selected_tool_id,
        risk_level=step.risk_level,
        approval_required=step.approval_required,
        input_payload=step.input_payload,
        output_payload=step.output_payload,
        error=step.error,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def _event_item(evt) -> EventItem:
    return EventItem(
        id=evt.id,
        sequence=evt.sequence,
        task_id=evt.task_id,
        step_id=evt.step_id,
        event_type=evt.event_type,
        payload=evt.payload or {},
        actor_type=evt.actor_type,
        created_at=evt.created_at,
    )


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _event_stream(
    task_id: str,
    after_sequence: int,
    factory,
) -> Iterator[bytes]:
    """SSE loop.

    Polls the event store for new rows, emits each as an SSE ``data:`` line.
    Stops when the task reaches a terminal status and all buffered events
    have been flushed, or when the client disconnects.
    """
    last_seq = after_sequence
    idle_ticks = 0
    # Safety cap — no single stream should run longer than 10 minutes.
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        with factory() as db:
            task = TaskRepository(db).get(task_id)
            if task is None:
                return
            events = EventRepository(db).list_for_task(
                task_id, after_sequence=last_seq, limit=200
            )
            task_status = task.status

        if events:
            idle_ticks = 0
            for evt in events:
                last_seq = max(last_seq, evt.sequence)
                payload = {
                    "id": evt.id,
                    "sequence": evt.sequence,
                    "task_id": evt.task_id,
                    "step_id": evt.step_id,
                    "event_type": evt.event_type,
                    "payload": evt.payload or {},
                    "created_at": evt.created_at.isoformat(),
                }
                yield _sse_frame(evt.event_type, payload)
        else:
            idle_ticks += 1

        if task_status in _TERMINAL_STATUSES and not events:
            yield _sse_frame(
                "stream.end",
                {"task_id": task_id, "final_status": task_status},
            )
            return

        # Heartbeat every ~15 idle ticks (~7.5s) keeps proxies from killing us.
        if idle_ticks and idle_ticks % 15 == 0:
            yield b": keep-alive\n\n"

        time.sleep(0.5)


def _sse_frame(event_name: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, default=str, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n".encode()


