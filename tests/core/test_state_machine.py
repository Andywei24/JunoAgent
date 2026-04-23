"""State-machine transition tests.

Covers the Stage-5 additions (approval pause/resume, pre-run failures) plus
the legacy happy-path transitions so regressions can't collapse the graph.
"""

from __future__ import annotations

import pytest

from brain_core.enums import StepStatus, TaskStatus
from brain_core.state_machine import (
    StateTransitionError,
    StepStateMachine,
    TaskStateMachine,
)


# ---------------------------------------------------------------------------
# Step transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,target",
    [
        # Legacy happy path.
        (StepStatus.PENDING, StepStatus.READY),
        (StepStatus.READY, StepStatus.RUNNING),
        (StepStatus.RUNNING, StepStatus.COMPLETED),
        # Stage-5 additions — approval pause/resume + pre-run failure.
        (StepStatus.PENDING, StepStatus.WAITING_FOR_APPROVAL),
        (StepStatus.PENDING, StepStatus.FAILED),
        (StepStatus.READY, StepStatus.WAITING_FOR_APPROVAL),
        (StepStatus.READY, StepStatus.FAILED),
        (StepStatus.WAITING_FOR_APPROVAL, StepStatus.READY),
        (StepStatus.WAITING_FOR_APPROVAL, StepStatus.RUNNING),
        (StepStatus.WAITING_FOR_APPROVAL, StepStatus.CANCELLED),
        # Retry returns RUNNING → READY.
        (StepStatus.RUNNING, StepStatus.READY),
    ],
)
def test_valid_step_transitions(current: StepStatus, target: StepStatus) -> None:
    assert StepStateMachine.can_transition(current, target) is True
    StepStateMachine.assert_transition(current, target)  # does not raise


@pytest.mark.parametrize(
    "current,target",
    [
        # Terminal states are dead-ends.
        (StepStatus.COMPLETED, StepStatus.RUNNING),
        (StepStatus.FAILED, StepStatus.READY),
        (StepStatus.SKIPPED, StepStatus.PENDING),
        (StepStatus.CANCELLED, StepStatus.RUNNING),
        # Can't skip straight from PENDING to a run outcome.
        (StepStatus.PENDING, StepStatus.COMPLETED),
        (StepStatus.PENDING, StepStatus.RUNNING),
        # Approval wait can't rewind to PENDING.
        (StepStatus.WAITING_FOR_APPROVAL, StepStatus.PENDING),
    ],
)
def test_invalid_step_transitions_raise(
    current: StepStatus, target: StepStatus
) -> None:
    assert StepStateMachine.can_transition(current, target) is False
    with pytest.raises(StateTransitionError):
        StepStateMachine.assert_transition(current, target)


def test_step_terminal_states() -> None:
    for s in (
        StepStatus.COMPLETED,
        StepStatus.FAILED,
        StepStatus.SKIPPED,
        StepStatus.CANCELLED,
    ):
        assert StepStateMachine.is_terminal(s) is True
        assert StepStateMachine.next_states(s) == frozenset()
    for s in (
        StepStatus.PENDING,
        StepStatus.READY,
        StepStatus.RUNNING,
        StepStatus.BLOCKED,
        StepStatus.WAITING_FOR_APPROVAL,
    ):
        assert StepStateMachine.is_terminal(s) is False


# ---------------------------------------------------------------------------
# Task transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,target",
    [
        # Legacy happy path.
        (TaskStatus.CREATED, TaskStatus.PARSING),
        (TaskStatus.PARSING, TaskStatus.PLANNING),
        (TaskStatus.PLANNING, TaskStatus.RUNNING),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        # Approval pause/resume.
        (TaskStatus.RUNNING, TaskStatus.WAITING_FOR_APPROVAL),
        (TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.RUNNING),
        (TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.CANCELLED),
        # Cancel is always reachable from the live states.
        (TaskStatus.CREATED, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
    ],
)
def test_valid_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    assert TaskStateMachine.can_transition(current, target) is True
    TaskStateMachine.assert_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        # Terminal → anything.
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.RUNNING),
        (TaskStatus.CANCELLED, TaskStatus.RUNNING),
        # Can't skip planning.
        (TaskStatus.CREATED, TaskStatus.RUNNING),
        (TaskStatus.PARSING, TaskStatus.RUNNING),
        # Can't rewind RUNNING to a pre-run phase.
        (TaskStatus.RUNNING, TaskStatus.PARSING),
        (TaskStatus.RUNNING, TaskStatus.PLANNING),
    ],
)
def test_invalid_task_transitions_raise(
    current: TaskStatus, target: TaskStatus
) -> None:
    assert TaskStateMachine.can_transition(current, target) is False
    with pytest.raises(StateTransitionError):
        TaskStateMachine.assert_transition(current, target)


def test_task_terminal_states() -> None:
    for s in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        assert TaskStateMachine.is_terminal(s) is True
        assert TaskStateMachine.next_states(s) == frozenset()
    for s in (
        TaskStatus.CREATED,
        TaskStatus.PARSING,
        TaskStatus.PLANNING,
        TaskStatus.RUNNING,
        TaskStatus.WAITING_FOR_APPROVAL,
        TaskStatus.WAITING_FOR_TOOL,
        TaskStatus.PAUSED,
        TaskStatus.RETRYING,
    ):
        assert TaskStateMachine.is_terminal(s) is False
