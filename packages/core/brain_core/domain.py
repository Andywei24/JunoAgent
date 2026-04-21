"""Pydantic models for platform domain objects.

These mirror the data model in `Brain agent platform.md` §6. They are the
wire + in-memory representation; ORM rows in `brain_db.models` map onto them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brain_core.enums import (
    ApprovalStatus,
    EventType,
    MemoryType,
    RiskLevel,
    StepStatus,
    TaskStatus,
    ToolBackendType,
    ToolCapabilityType,
)


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=False)


# ---------------------------------------------------------------------------
# User + session
# ---------------------------------------------------------------------------


class User(_Base):
    id: str
    email: str | None = None
    display_name: str | None = None
    created_at: datetime


class Session(_Base):
    id: str
    user_id: str
    created_at: datetime
    closed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Task + step
# ---------------------------------------------------------------------------


class ParsedGoal(_Base):
    """Structured output from the Goal Parser (§5.4). Shape will evolve."""

    objective: str
    deliverable: str | None = None
    scope: str | None = None
    input_type: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    candidate_capabilities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class Task(_Base):
    id: str
    user_id: str
    session_id: str | None = None
    goal: str
    parsed_goal: ParsedGoal | None = None
    status: TaskStatus
    priority: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    budget_limit: dict[str, Any] = Field(default_factory=dict)
    budget_used: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    final_output: dict[str, Any] | None = None
    failure_reason: str | None = None


class TaskStep(_Base):
    id: str
    task_id: str
    parent_step_id: str | None = None
    name: str
    description: str | None = None
    status: StepStatus
    sequence_order: int
    dependencies: list[str] = Field(default_factory=list)
    assigned_agent_id: str | None = None
    required_capability: str | None = None
    selected_tool_id: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    approval_required: bool = False
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class Event(_Base):
    id: str
    task_id: str | None = None
    step_id: str | None = None
    agent_id: str | None = None
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_type: str | None = None
    actor_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


class Approval(_Base):
    id: str
    task_id: str
    step_id: str | None = None
    status: ApprovalStatus
    requested_action: str
    risk_level: RiskLevel
    reason: str | None = None
    data_involved: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    resolved_at: datetime | None = None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ToolDefinition(_Base):
    id: str
    name: str
    description: str
    capability_type: ToolCapabilityType
    backend_type: ToolBackendType
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    required_permissions: list[str] = Field(default_factory=list)
    timeout_seconds: int = 30
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    version: str = "1"
    enabled: bool = True


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class MemoryItem(_Base):
    id: str
    user_id: str
    task_id: str | None = None
    memory_type: MemoryType
    content: str
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding_ref: str | None = None
    importance: float = 0.0
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
