"""Canonical enums used across the platform.

Kept deliberately as string enums so values survive JSON round-trips, database
storage, and external clients without translation tables.
"""

from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    CREATED = "created"
    PARSING = "parsing"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ActorType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
    TOOL = "tool"
    WORKER = "worker"


class MemoryType(str, Enum):
    SESSION = "session"
    WORKING = "working"
    SEMANTIC = "semantic"
    LONG_TERM = "long_term"


class ToolCapabilityType(str, Enum):
    REASONING = "reasoning"
    RETRIEVAL = "retrieval"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    EXECUTION = "execution"
    EXTERNAL_API = "external_api"
    DESKTOP = "desktop"


class ToolBackendType(str, Enum):
    INTERNAL = "internal"
    LLM = "llm"
    MEMORY = "memory"
    SANDBOX = "sandbox"
    EXTERNAL_API = "external_api"
    WORKER = "worker"


class EventType(str, Enum):
    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Goal + plan
    GOAL_PARSED = "goal.parsed"
    PLAN_GENERATED = "plan.generated"

    # Step lifecycle
    STEP_READY = "step.ready"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_SKIPPED = "step.skipped"
    STEP_RETRYING = "step.retrying"

    # Execution surface
    LLM_CALLED = "llm.called"
    TOOL_SELECTED = "tool.selected"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

    # Approval
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"

    # Policy / budget
    POLICY_BLOCKED = "policy.blocked"
    BUDGET_EXCEEDED = "budget.exceeded"

    # Memory
    MEMORY_WRITTEN = "memory.written"
    MEMORY_RETRIEVED = "memory.retrieved"
