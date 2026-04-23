"""Repositories: the only layer that should construct/mutate ORM rows.

Stage 1 ships the core primitives needed by the first end-to-end loop:
users, tasks, steps, and the append-only event store. More repositories
(tools, memories, approvals) can land as later stages need them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from brain_core.enums import ActorType, ApprovalStatus, EventType, StepStatus, TaskStatus
from brain_core.ids import new_approval_id, new_event_id, new_step_id, new_task_id
from brain_core.state_machine import StepStateMachine, TaskStateMachine

from brain_db import models


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserRepository:
    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def get(self, user_id: str) -> models.User | None:
        return self.db.get(models.User, user_id)

    def upsert_dev_user(self, user_id: str, email: str | None = None) -> models.User:
        """Idempotent get-or-create for the local dev user placeholder."""
        user = self.get(user_id)
        if user:
            return user
        user = models.User(id=user_id, email=email, display_name="Local Dev")
        self.db.add(user)
        self.db.flush()
        return user


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class TaskRepository:
    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: str,
        goal: str,
        session_id: str | None = None,
        priority: int = 0,
        budget_limit: dict[str, Any] | None = None,
    ) -> models.Task:
        task = models.Task(
            id=new_task_id(),
            user_id=user_id,
            session_id=session_id,
            goal=goal,
            status=TaskStatus.CREATED.value,
            priority=priority,
            budget_limit=budget_limit or {},
            budget_used={},
        )
        self.db.add(task)
        self.db.flush()
        return task

    def get(self, task_id: str) -> models.Task | None:
        return self.db.get(models.Task, task_id)

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[models.Task]:
        stmt = (
            select(models.Task)
            .where(models.Task.user_id == user_id)
            .order_by(models.Task.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def transition(self, task: models.Task, target: TaskStatus) -> models.Task:
        """Validate then apply a status transition."""
        current = TaskStatus(task.status)
        TaskStateMachine.assert_transition(current, target)
        task.status = target.value
        if TaskStateMachine.is_terminal(target) and task.completed_at is None:
            task.completed_at = _utcnow()
        self.db.flush()
        return task


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


class StepRepository:
    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def create_many(
        self, task_id: str, specs: Iterable[dict[str, Any]]
    ) -> list[models.TaskStep]:
        steps: list[models.TaskStep] = []
        for idx, spec in enumerate(specs):
            step = models.TaskStep(
                id=spec.get("id") or new_step_id(),
                task_id=task_id,
                parent_step_id=spec.get("parent_step_id"),
                name=spec["name"],
                description=spec.get("description"),
                status=spec.get("status", StepStatus.PENDING.value),
                sequence_order=spec.get("sequence_order", idx),
                dependencies=spec.get("dependencies", []),
                required_capability=spec.get("required_capability"),
                risk_level=spec.get("risk_level", "low"),
                approval_required=spec.get("approval_required", False),
                input_payload=spec.get("input_payload"),
            )
            self.db.add(step)
            steps.append(step)
        self.db.flush()
        return steps

    def get(self, step_id: str) -> models.TaskStep | None:
        return self.db.get(models.TaskStep, step_id)

    def list_for_task(self, task_id: str) -> list[models.TaskStep]:
        stmt = (
            select(models.TaskStep)
            .where(models.TaskStep.task_id == task_id)
            .order_by(models.TaskStep.sequence_order)
        )
        return list(self.db.scalars(stmt))

    def transition(self, step: models.TaskStep, target: StepStatus) -> models.TaskStep:
        current = StepStatus(step.status)
        StepStateMachine.assert_transition(current, target)
        step.status = target.value
        now = _utcnow()
        if target is StepStatus.RUNNING and step.started_at is None:
            step.started_at = now
        if StepStateMachine.is_terminal(target) and step.completed_at is None:
            step.completed_at = now
        self.db.flush()
        return step


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ToolRepository:
    """CRUD for the tool registry.

    The registry is the durable projection of in-process :class:`ToolSpec`
    objects: specs are registered in code on boot and synced here so the
    rest of the platform (steps, audit logs, eventually approvals) can
    reference tools by stable id.
    """

    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def get(self, tool_id: str) -> models.Tool | None:
        return self.db.get(models.Tool, tool_id)

    def list_enabled(self) -> list[models.Tool]:
        stmt = (
            select(models.Tool)
            .where(models.Tool.enabled.is_(True))
            .order_by(models.Tool.name)
        )
        return list(self.db.scalars(stmt))

    def upsert(
        self,
        *,
        id: str,
        name: str,
        description: str,
        capability_type: str,
        backend_type: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        risk_level: str = "low",
        required_permissions: list[str] | None = None,
        timeout_seconds: int = 30,
        retry_policy: dict[str, Any] | None = None,
        cost_model: dict[str, Any] | None = None,
        version: str = "1",
        enabled: bool = True,
    ) -> models.Tool:
        tool = self.get(id)
        if tool is None:
            tool = models.Tool(id=id)
            self.db.add(tool)
        tool.name = name
        tool.description = description
        tool.capability_type = capability_type
        tool.backend_type = backend_type
        tool.input_schema = input_schema or {}
        tool.output_schema = output_schema or {}
        tool.risk_level = risk_level
        tool.required_permissions = required_permissions or []
        tool.timeout_seconds = timeout_seconds
        tool.retry_policy = retry_policy or {}
        tool.cost_model = cost_model or {}
        tool.version = version
        tool.enabled = enabled
        self.db.flush()
        return tool


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


class ApprovalRepository:
    """CRUD for the approvals table.

    Approvals are created by the engine when a step needs a human decision,
    and resolved by the API layer. The row carries enough context (action,
    risk, data involved) that approvers can decide without re-reading the
    step.
    """

    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def get(self, approval_id: str) -> models.Approval | None:
        return self.db.get(models.Approval, approval_id)

    def create(
        self,
        *,
        task_id: str,
        step_id: str | None,
        requested_action: str,
        risk_level: str,
        reason: str | None = None,
        data_involved: dict[str, Any] | None = None,
        requested_by: str | None = None,
        status: ApprovalStatus = ApprovalStatus.PENDING,
        expires_at: datetime | None = None,
    ) -> models.Approval:
        approval = models.Approval(
            id=new_approval_id(),
            task_id=task_id,
            step_id=step_id,
            status=status.value,
            requested_action=requested_action,
            risk_level=risk_level,
            reason=reason,
            data_involved=data_involved or {},
            requested_by=requested_by,
            expires_at=expires_at,
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def resolve(
        self,
        approval: models.Approval,
        target: ApprovalStatus,
        *,
        approved_by: str | None = None,
        reason: str | None = None,
    ) -> models.Approval:
        if approval.status != ApprovalStatus.PENDING.value:
            raise ValueError(
                f"approval {approval.id} already resolved ({approval.status})"
            )
        approval.status = target.value
        approval.approved_by = approved_by
        if reason is not None:
            approval.reason = reason
        approval.resolved_at = _utcnow()
        self.db.flush()
        return approval

    def list_pending_for_user(self, user_id: str) -> list[models.Approval]:
        """Approvals across all of a user's tasks that still need a decision."""
        stmt = (
            select(models.Approval)
            .join(models.Task, models.Task.id == models.Approval.task_id)
            .where(models.Task.user_id == user_id)
            .where(models.Approval.status == ApprovalStatus.PENDING.value)
            .order_by(models.Approval.created_at.asc())
        )
        return list(self.db.scalars(stmt))

    def list_for_task(self, task_id: str) -> list[models.Approval]:
        stmt = (
            select(models.Approval)
            .where(models.Approval.task_id == task_id)
            .order_by(models.Approval.created_at.asc())
        )
        return list(self.db.scalars(stmt))


# ---------------------------------------------------------------------------
# Events (append-only)
# ---------------------------------------------------------------------------


class EventRepository:
    """Append-only event store.

    Mutations are blocked at the SQL layer (see migration 0001); this class
    mirrors that constraint by exposing only `append` and read helpers.
    """

    def __init__(self, db: OrmSession) -> None:
        self.db = db

    def append(
        self,
        *,
        event_type: EventType,
        task_id: str | None = None,
        step_id: str | None = None,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
        actor_type: ActorType | None = None,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> models.Event:
        evt = models.Event(
            id=new_event_id(),
            task_id=task_id,
            step_id=step_id,
            agent_id=agent_id,
            event_type=event_type.value,
            payload=payload or {},
            actor_type=actor_type.value if actor_type else None,
            actor_id=actor_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        self.db.add(evt)
        self.db.flush()
        return evt

    def list_for_task(
        self, task_id: str, *, after_sequence: int | None = None, limit: int = 500
    ) -> list[models.Event]:
        stmt = select(models.Event).where(models.Event.task_id == task_id)
        if after_sequence is not None:
            stmt = stmt.where(models.Event.sequence > after_sequence)
        stmt = stmt.order_by(models.Event.sequence.asc()).limit(limit)
        return list(self.db.scalars(stmt))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    from datetime import datetime as _dt
    from datetime import timezone

    return _dt.now(timezone.utc)
