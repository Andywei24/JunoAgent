"""BudgetController unit tests.

The controller only reads/writes ``task.budget_limit`` and
``task.budget_used``; a stub object with those two attributes is enough to
cover the surface.
"""

from __future__ import annotations

from types import SimpleNamespace

from brain_engine.budget import BudgetController


def _task(
    *,
    limit: dict | None = None,
    used: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(budget_limit=limit or {}, budget_used=used or {})


def test_no_limits_is_always_ok() -> None:
    assert BudgetController.check(_task()).ok is True


def test_limit_not_yet_reached_is_ok() -> None:
    decision = BudgetController.check(
        _task(limit={"max_steps": 3}, used={"max_steps": 2})
    )
    assert decision.ok is True


def test_limit_hit_exactly_blocks() -> None:
    decision = BudgetController.check(
        _task(limit={"max_steps": 2}, used={"max_steps": 2})
    )
    assert decision.ok is False
    assert "max_steps" in decision.reason


def test_limit_exceeded_blocks() -> None:
    decision = BudgetController.check(
        _task(limit={"max_llm_calls": 5}, used={"max_llm_calls": 7})
    )
    assert decision.ok is False
    assert decision.limit == {"max_llm_calls": 5}
    assert decision.used == {"max_llm_calls": 7}


def test_unknown_limit_key_is_ignored() -> None:
    # Forward-compat: a limit key the controller doesn't yet understand
    # shouldn't spuriously block.
    decision = BudgetController.check(
        _task(limit={"max_tokens": 10}, used={"max_tokens": 99})
    )
    assert decision.ok is True


def test_record_llm_increments_calls_and_cost() -> None:
    task = _task()
    BudgetController.record_llm(task, cost_usd=0.01)
    BudgetController.record_llm(task, cost_usd=0.02)
    assert task.budget_used["max_llm_calls"] == 2
    assert task.budget_used["max_cost_usd"] == 0.03


def test_record_llm_without_cost_only_counts_calls() -> None:
    task = _task()
    BudgetController.record_llm(task, cost_usd=None)
    assert task.budget_used["max_llm_calls"] == 1
    assert "max_cost_usd" not in task.budget_used


def test_record_step_increments_step_count() -> None:
    task = _task(used={"max_steps": 4})
    BudgetController.record_step(task)
    assert task.budget_used["max_steps"] == 5


def test_multiple_limits_any_one_trips() -> None:
    decision = BudgetController.check(
        _task(
            limit={"max_llm_calls": 10, "max_steps": 2},
            used={"max_llm_calls": 3, "max_steps": 2},
        )
    )
    assert decision.ok is False
    assert "max_steps" in decision.reason
