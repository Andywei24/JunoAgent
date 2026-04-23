"""Approval routes.

Pending approvals surface to humans here. Resolving an approval commits the
state transition, then re-submits the task to the runner so the orchestrator
picks up where it paused.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from brain_api.deps import CurrentUserDep, DbSession
from brain_core.enums import ApprovalStatus, TaskStatus
from brain_db.repositories import ApprovalRepository, TaskRepository


router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


class ApprovalItem(BaseModel):
    id: str
    task_id: str
    step_id: str | None
    status: str
    requested_action: str
    risk_level: str
    reason: str | None
    data_involved: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None
    approved_by: str | None
    created_at: datetime
    resolved_at: datetime | None


class ApprovalRejectRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)


@router.get("", response_model=list[ApprovalItem])
def list_pending_approvals(
    db: DbSession, user: CurrentUserDep
) -> list[ApprovalItem]:
    rows = ApprovalRepository(db).list_pending_for_user(user.id)
    return [_item(r) for r in rows]


@router.get("/{approval_id}", response_model=ApprovalItem)
def get_approval(
    approval_id: str, db: DbSession, user: CurrentUserDep
) -> ApprovalItem:
    approval = _require_user_approval(db, approval_id, user.id)
    return _item(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalItem)
def approve(
    approval_id: str,
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> ApprovalItem:
    _require_user_approval(db, approval_id, user.id)
    services = request.app.state.services
    try:
        approval, task = services.approvals.approve(
            db, approval_id, approver_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()

    # Resume the orchestrator. Runner guards against double-submits, and
    # run_task detects the task is back in RUNNING / was WAITING_FOR_APPROVAL
    # and continues from the resumed step.
    if TaskStatus(task.status) == TaskStatus.RUNNING:
        services.runner.submit(task.id)
    return _item(approval)


@router.post("/{approval_id}/reject", response_model=ApprovalItem)
def reject(
    approval_id: str,
    body: ApprovalRejectRequest,
    db: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> ApprovalItem:
    _require_user_approval(db, approval_id, user.id)
    services = request.app.state.services
    try:
        approval, _task = services.approvals.reject(
            db, approval_id, approver_id=user.id, reason=body.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return _item(approval)


def _require_user_approval(db, approval_id: str, user_id: str):
    approval = ApprovalRepository(db).get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    task = TaskRepository(db).get(approval.task_id)
    if task is None or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="approval not found")
    return approval


def _item(approval) -> ApprovalItem:
    return ApprovalItem(
        id=approval.id,
        task_id=approval.task_id,
        step_id=approval.step_id,
        status=approval.status,
        requested_action=approval.requested_action,
        risk_level=approval.risk_level,
        reason=approval.reason,
        data_involved=approval.data_involved or {},
        requested_by=approval.requested_by,
        approved_by=approval.approved_by,
        created_at=approval.created_at,
        resolved_at=approval.resolved_at,
    )
