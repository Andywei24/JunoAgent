"""Approval manager.

Owns the three small state machines around a pending approval:

  * **Create** — transitions the step into ``waiting_for_approval`` and the
    task into ``waiting_for_approval`` (only if currently ``running``), then
    emits ``approval.requested``.
  * **Approve** — flips the approval row to ``approved``, returns the step to
    ``ready`` so the orchestrator can resume it, brings the task back to
    ``running``, and emits ``approval.approved``.
  * **Reject** — flips the approval row to ``rejected``, cancels the step and
    task, and emits ``approval.rejected``.

All three accept an externally-managed ``Session`` so the caller (orchestrator
or API) can commit the full effect in a single transaction.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as OrmSession

from brain_core.enums import (
    ActorType,
    ApprovalStatus,
    EventType,
    StepStatus,
    TaskStatus,
)
from brain_db import models
from brain_db.repositories import (
    ApprovalRepository,
    EventRepository,
    StepRepository,
    TaskRepository,
)


class ApprovalManager:
    def request(
        self,
        db: OrmSession,
        *,
        task: models.Task,
        step: models.TaskStep,
        requested_action: str,
        risk_level: str,
        reason: str,
        data_involved: dict[str, Any] | None = None,
        requested_by: str | None = None,
    ) -> models.Approval:
        approvals = ApprovalRepository(db)
        steps = StepRepository(db)
        tasks = TaskRepository(db)
        events = EventRepository(db)

        approval = approvals.create(
            task_id=task.id,
            step_id=step.id,
            requested_action=requested_action,
            risk_level=risk_level,
            reason=reason,
            data_involved=data_involved or {},
            requested_by=requested_by,
        )
        if StepStatus(step.status) != StepStatus.WAITING_FOR_APPROVAL:
            steps.transition(step, StepStatus.WAITING_FOR_APPROVAL)
        if TaskStatus(task.status) == TaskStatus.RUNNING:
            tasks.transition(task, TaskStatus.WAITING_FOR_APPROVAL)

        events.append(
            event_type=EventType.APPROVAL_REQUESTED,
            task_id=task.id,
            step_id=step.id,
            payload={
                "approval_id": approval.id,
                "requested_action": requested_action,
                "risk_level": risk_level,
                "reason": reason,
                "data_involved": data_involved or {},
            },
            actor_type=ActorType.SYSTEM,
        )
        return approval

    def approve(
        self,
        db: OrmSession,
        approval_id: str,
        *,
        approver_id: str | None,
    ) -> tuple[models.Approval, models.Task]:
        approval, step, task = self._load_pending(db, approval_id)
        approvals = ApprovalRepository(db)
        steps = StepRepository(db)
        tasks = TaskRepository(db)
        events = EventRepository(db)

        approvals.resolve(approval, ApprovalStatus.APPROVED, approved_by=approver_id)
        if step is not None and StepStatus(step.status) == StepStatus.WAITING_FOR_APPROVAL:
            steps.transition(step, StepStatus.READY)
        if TaskStatus(task.status) == TaskStatus.WAITING_FOR_APPROVAL:
            tasks.transition(task, TaskStatus.RUNNING)

        events.append(
            event_type=EventType.APPROVAL_APPROVED,
            task_id=task.id,
            step_id=approval.step_id,
            payload={
                "approval_id": approval.id,
                "approved_by": approver_id,
            },
            actor_type=ActorType.USER,
            actor_id=approver_id,
        )
        return approval, task

    def reject(
        self,
        db: OrmSession,
        approval_id: str,
        *,
        approver_id: str | None,
        reason: str | None = None,
    ) -> tuple[models.Approval, models.Task]:
        approval, step, task = self._load_pending(db, approval_id)
        approvals = ApprovalRepository(db)
        steps = StepRepository(db)
        tasks = TaskRepository(db)
        events = EventRepository(db)

        approvals.resolve(
            approval,
            ApprovalStatus.REJECTED,
            approved_by=approver_id,
            reason=reason,
        )
        if step is not None and StepStatus(step.status) == StepStatus.WAITING_FOR_APPROVAL:
            steps.transition(step, StepStatus.CANCELLED)
        task_status = TaskStatus(task.status)
        if task_status == TaskStatus.WAITING_FOR_APPROVAL:
            tasks.transition(task, TaskStatus.CANCELLED)

        events.append(
            event_type=EventType.APPROVAL_REJECTED,
            task_id=task.id,
            step_id=approval.step_id,
            payload={
                "approval_id": approval.id,
                "rejected_by": approver_id,
                "reason": reason,
            },
            actor_type=ActorType.USER,
            actor_id=approver_id,
        )
        return approval, task

    def _load_pending(
        self, db: OrmSession, approval_id: str
    ) -> tuple[models.Approval, models.TaskStep | None, models.Task]:
        approvals = ApprovalRepository(db)
        approval = approvals.get(approval_id)
        if approval is None:
            raise LookupError(f"approval not found: {approval_id}")
        if approval.status != ApprovalStatus.PENDING.value:
            raise ValueError(
                f"approval {approval_id} already resolved "
                f"(status={approval.status})"
            )
        task = TaskRepository(db).get(approval.task_id)
        if task is None:
            raise LookupError(
                f"approval {approval_id} references missing task {approval.task_id}"
            )
        step = None
        if approval.step_id:
            step = StepRepository(db).get(approval.step_id)
        return approval, step, task
