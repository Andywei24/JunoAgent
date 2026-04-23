"""Budget controller.

Tallies LLM + step usage on each task and decides whether further work is
allowed. Limits are carried on ``task.budget_limit`` so they travel with the
task row and are visible to the UI; ``task.budget_used`` is updated in the
same transactions that record work, so the two sides never drift.

Supported limit keys:
  * ``max_llm_calls`` — integer cap on the number of ``llm.called`` events.
  * ``max_cost_usd`` — float cap on the cumulative LLM cost.
  * ``max_steps`` — integer cap on steps processed (includes failed steps).

Missing keys mean "no limit". Unknown keys are ignored so future additions
don't break old tasks.
"""

from __future__ import annotations

from dataclasses import dataclass

from brain_db import models


_KEYS: tuple[str, ...] = ("max_llm_calls", "max_cost_usd", "max_steps")


@dataclass(slots=True)
class BudgetDecision:
    ok: bool
    reason: str | None = None
    limit: dict[str, float] | None = None
    used: dict[str, float] | None = None


class BudgetController:
    """Stateless checker + in-place recorder.

    The orchestrator calls :meth:`check` before each step and calls
    :meth:`record_llm` / :meth:`record_step` inside DB transactions; the
    controller itself holds no state, so swapping it for a redis-backed
    implementation later only requires changing call sites, not signatures.
    """

    @staticmethod
    def check(task: models.Task) -> BudgetDecision:
        limits = task.budget_limit or {}
        used = task.budget_used or {}
        if not limits:
            return BudgetDecision(ok=True)
        for key in _KEYS:
            limit = limits.get(key)
            if limit is None:
                continue
            spent = used.get(key, 0)
            if spent >= limit:
                return BudgetDecision(
                    ok=False,
                    reason=f"{key} exceeded: used={spent}, limit={limit}",
                    limit={k: v for k, v in limits.items() if k in _KEYS},
                    used={k: v for k, v in used.items() if k in _KEYS},
                )
        return BudgetDecision(ok=True)

    @staticmethod
    def record_llm(task: models.Task, *, cost_usd: float | None) -> None:
        used = dict(task.budget_used or {})
        used["max_llm_calls"] = int(used.get("max_llm_calls", 0)) + 1
        if cost_usd is not None:
            used["max_cost_usd"] = float(used.get("max_cost_usd", 0.0)) + float(
                cost_usd
            )
        task.budget_used = used

    @staticmethod
    def record_step(task: models.Task) -> None:
        used = dict(task.budget_used or {})
        used["max_steps"] = int(used.get("max_steps", 0)) + 1
        task.budget_used = used
