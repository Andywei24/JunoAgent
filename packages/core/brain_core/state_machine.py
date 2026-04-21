"""Explicit state machines for tasks and steps.

Valid transitions come from `Brain agent platform.md` §5.6. Anything not in the
allow-table raises `StateTransitionError` — the Workflow Engine should never
allow drift-by-accident between states.
"""

from __future__ import annotations

from brain_core.enums import StepStatus, TaskStatus


class StateTransitionError(ValueError):
    """Raised when an invalid state transition is attempted."""


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

_TASK_TERMINAL: frozenset[TaskStatus] = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)

_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset(
        {TaskStatus.PARSING, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.PARSING: frozenset(
        {TaskStatus.PLANNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.PLANNING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_FOR_TOOL,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.PAUSED,
            TaskStatus.RETRYING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_FOR_TOOL: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING_FOR_APPROVAL: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.PAUSED: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.RETRYING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    # Terminal
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class TaskStateMachine:
    @staticmethod
    def next_states(current: TaskStatus) -> frozenset[TaskStatus]:
        return _TASK_TRANSITIONS[current]

    @staticmethod
    def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
        return target in _TASK_TRANSITIONS.get(current, frozenset())

    @staticmethod
    def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
        if not TaskStateMachine.can_transition(current, target):
            raise StateTransitionError(
                f"Invalid task transition: {current.value} -> {target.value}"
            )

    @staticmethod
    def is_terminal(state: TaskStatus) -> bool:
        return state in _TASK_TERMINAL


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------

_STEP_TERMINAL: frozenset[StepStatus] = frozenset(
    {StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.CANCELLED}
)

_STEP_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset(
        {
            StepStatus.READY,
            StepStatus.BLOCKED,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        }
    ),
    StepStatus.READY: frozenset(
        {
            StepStatus.RUNNING,
            StepStatus.BLOCKED,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        }
    ),
    StepStatus.RUNNING: frozenset(
        {
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.WAITING_FOR_APPROVAL,
            StepStatus.BLOCKED,
            StepStatus.READY,  # retry returns to ready
            StepStatus.CANCELLED,
        }
    ),
    StepStatus.BLOCKED: frozenset(
        {StepStatus.READY, StepStatus.FAILED, StepStatus.CANCELLED}
    ),
    StepStatus.WAITING_FOR_APPROVAL: frozenset(
        {StepStatus.RUNNING, StepStatus.FAILED, StepStatus.CANCELLED, StepStatus.SKIPPED}
    ),
    # Terminal
    StepStatus.COMPLETED: frozenset(),
    StepStatus.FAILED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
    StepStatus.CANCELLED: frozenset(),
}


class StepStateMachine:
    @staticmethod
    def next_states(current: StepStatus) -> frozenset[StepStatus]:
        return _STEP_TRANSITIONS[current]

    @staticmethod
    def can_transition(current: StepStatus, target: StepStatus) -> bool:
        return target in _STEP_TRANSITIONS.get(current, frozenset())

    @staticmethod
    def assert_transition(current: StepStatus, target: StepStatus) -> None:
        if not StepStateMachine.can_transition(current, target):
            raise StateTransitionError(
                f"Invalid step transition: {current.value} -> {target.value}"
            )

    @staticmethod
    def is_terminal(state: StepStatus) -> bool:
        return state in _STEP_TERMINAL
