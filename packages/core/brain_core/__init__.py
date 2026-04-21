"""Brain core: domain types, enums, events, and the task/step state machine.

This package is the vocabulary of the platform. It has no I/O and no framework
dependencies beyond pydantic — everything here describes *what* the brain
manipulates, not *how* it is persisted or served.
"""

from brain_core.enums import (
    ActorType,
    ApprovalStatus,
    EventType,
    MemoryType,
    RiskLevel,
    StepStatus,
    TaskStatus,
    ToolBackendType,
    ToolCapabilityType,
)
from brain_core.state_machine import (
    StateTransitionError,
    StepStateMachine,
    TaskStateMachine,
)

__all__ = [
    "ActorType",
    "ApprovalStatus",
    "EventType",
    "MemoryType",
    "RiskLevel",
    "StateTransitionError",
    "StepStateMachine",
    "StepStatus",
    "TaskStateMachine",
    "TaskStatus",
    "ToolBackendType",
    "ToolCapabilityType",
]
