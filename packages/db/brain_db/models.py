"""ORM models for the Brain Agent Platform.

Tables follow `Brain agent platform.md` §6 + §5.22. String IDs (prefixed, e.g.
`task_abc...`) are used instead of UUIDs so raw log lines remain readable.
JSON fields use JSONB for Postgres; falls back to plain JSON elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brain_db.session import Base


# Alias so we can swap to generic JSON in SQLite tests without touching models.
JSONType = JSONB().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    from datetime import datetime as _dt
    from datetime import timezone

    return _dt.now(timezone.utc)


# ---------------------------------------------------------------------------
# Users + sessions
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONType, default=dict, nullable=False
    )


# ---------------------------------------------------------------------------
# Tasks + steps
# ---------------------------------------------------------------------------


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_goal: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    budget_limit: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    budget_used: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_output: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.sequence_order"
    )


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_step_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("task_steps.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    dependencies: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(64))
    required_capability: Mapped[str | None] = mapped_column(String(80))
    selected_tool_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tools.id", ondelete="SET NULL")
    )
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="steps")

    __table_args__ = (
        Index("ix_task_steps_task_order", "task_id", "sequence_order"),
    )


# ---------------------------------------------------------------------------
# Events — append-only
# ---------------------------------------------------------------------------


class Event(Base):
    """Immutable event record. Update/delete are blocked at the DB level (see migration)."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence: Mapped[int] = mapped_column(
        BigInteger, autoincrement=True, unique=True, nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("task_steps.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    actor_type: Mapped[str | None] = mapped_column(String(20))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_events_task_seq", "task_id", "sequence"),
        Index("ix_events_task_created", "task_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("task_steps.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_action: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    data_involved: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    capability_type: Mapped[str] = mapped_column(String(40), nullable=False)
    backend_type: Mapped[str] = mapped_column(String(40), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    required_permissions: Mapped[list[str]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    cost_model: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("timeout_seconds > 0", name="tools_timeout_positive"),
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class MemoryItem(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    memory_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONType, default=dict, nullable=False
    )
    embedding_ref: Mapped[str | None] = mapped_column(String(200))
    importance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
