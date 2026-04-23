"""Context Builder — Stage 6.

Assembles a structured context bundle for a specific step. Responsibilities
from `Brain agent platform.md` §5.14:

  * include the task goal, plan, and active step state;
  * include relevant memories (ranked by the MemoryService);
  * include recent events or summaries;
  * include prior step outputs;
  * stay within a character budget;
  * prefer high-signal content over raw history.

The builder is a pure function over repositories + the ``MemoryService``;
it doesn't mutate the session. Callers own the trim policy — the default
character budget is conservative and shrinks each section largest-first so
a single massive tool output can't crowd out the goal line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from brain_db import models
from brain_db.repositories import EventRepository, StepRepository, TaskRepository

from brain_engine.memory import MemoryHit, MemoryService


# Approximate: ~4 characters per token on English text, so 8000 chars ~ 2k tokens.
DEFAULT_CHAR_BUDGET = 8000

# Sections are trimmed largest-first until the total fits the budget.
# Tuples keep insertion order stable.
_TRIM_ORDER = (
    "recent_events",
    "prior_step_outputs",
    "relevant_memories",
    "parsed_goal",
    "active_step",
    "goal",
)


@dataclass(slots=True)
class ContextBundle:
    """The rendered output of :func:`build_context`.

    Ready to hand to a prompt template as a single variable or to splice
    into an existing render call. Each field is already string-clipped.
    """

    goal: str
    parsed_goal: dict[str, Any]
    active_step: dict[str, Any] | None
    relevant_memories: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    prior_step_outputs: list[dict[str, Any]]
    char_budget: int
    char_used: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "parsed_goal": self.parsed_goal,
            "active_step": self.active_step,
            "relevant_memories": self.relevant_memories,
            "recent_events": self.recent_events,
            "prior_step_outputs": self.prior_step_outputs,
            "char_budget": self.char_budget,
            "char_used": self.char_used,
        }


@dataclass(slots=True)
class ContextBuilder:
    memory: MemoryService
    char_budget: int = DEFAULT_CHAR_BUDGET
    max_memories: int = 5
    max_events: int = 10
    max_prior_outputs: int = 5

    def build(
        self,
        db: OrmSession,
        *,
        task_id: str,
        step_id: str | None = None,
        query: str | None = None,
    ) -> ContextBundle:
        task = TaskRepository(db).get(task_id)
        if task is None:
            raise LookupError(f"task {task_id} not found")

        steps = StepRepository(db).list_for_task(task_id)
        active_step = _active_step(steps, step_id)
        prior_outputs = _prior_step_outputs(steps, active_step, self.max_prior_outputs)

        events = EventRepository(db).list_for_task(task_id, limit=500)
        recent = _recent_events(events, self.max_events)

        search_query = query or _default_query(task, active_step)
        hits: list[MemoryHit] = []
        if search_query:
            hits = self.memory.search(
                db,
                user_id=task.user_id,
                query=search_query,
                limit=self.max_memories,
                event_task_id=task_id,
                event_step_id=step_id,
            )
        memory_rows = [_memory_view(h) for h in hits]

        goal = task.goal or ""
        parsed = dict(task.parsed_goal or {})
        active_view = _step_view(active_step) if active_step else None

        sections: dict[str, Any] = {
            "goal": goal,
            "parsed_goal": parsed,
            "active_step": active_view,
            "relevant_memories": memory_rows,
            "recent_events": recent,
            "prior_step_outputs": prior_outputs,
        }
        sections = _fit_to_budget(sections, self.char_budget)
        char_used = _estimate_chars(sections)
        return ContextBundle(
            goal=sections["goal"],
            parsed_goal=sections["parsed_goal"],
            active_step=sections["active_step"],
            relevant_memories=sections["relevant_memories"],
            recent_events=sections["recent_events"],
            prior_step_outputs=sections["prior_step_outputs"],
            char_budget=self.char_budget,
            char_used=char_used,
        )


# ---------------------------------------------------------------------------
# Shaping helpers
# ---------------------------------------------------------------------------


def _active_step(
    steps: list[models.TaskStep], step_id: str | None
) -> models.TaskStep | None:
    if step_id:
        for s in steps:
            if s.id == step_id:
                return s
    # Fall back to the first non-terminal step.
    for s in steps:
        if s.status in {"pending", "ready", "running", "waiting_for_approval", "blocked"}:
            return s
    return None


def _prior_step_outputs(
    steps: list[models.TaskStep],
    active: models.TaskStep | None,
    limit: int,
) -> list[dict[str, Any]]:
    cutoff = active.sequence_order if active else 1_000_000
    completed = [
        s
        for s in steps
        if s.status == "completed" and s.sequence_order < cutoff and s.output_payload
    ]
    completed.sort(key=lambda s: s.sequence_order)
    if len(completed) > limit:
        completed = completed[-limit:]
    return [
        {
            "step_id": s.id,
            "name": s.name,
            "output": _clip_jsonable(s.output_payload, 1200),
        }
        for s in completed
    ]


def _recent_events(events: list[models.Event], limit: int) -> list[dict[str, Any]]:
    # Drop noisy event types that don't help a reasoning step.
    skip = {"llm.called", "memory.retrieved"}
    filtered = [e for e in events if e.event_type not in skip]
    tail = filtered[-limit:]
    return [
        {
            "sequence": e.sequence,
            "type": e.event_type,
            "payload": _clip_jsonable(e.payload, 400),
        }
        for e in tail
    ]


def _step_view(step: models.TaskStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "name": step.name,
        "description": step.description,
        "status": step.status,
        "required_capability": step.required_capability,
        "risk_level": step.risk_level,
        "approval_required": step.approval_required,
        "input_payload": _clip_jsonable(step.input_payload, 800),
    }


def _memory_view(hit: MemoryHit) -> dict[str, Any]:
    item = hit.item
    return {
        "id": item.id,
        "memory_type": item.memory_type,
        "summary": item.summary,
        "content": (item.content or "")[:600],
        "score": round(hit.score, 4),
        "importance": float(item.importance or 0.0),
    }


def _default_query(
    task: models.Task, active: models.TaskStep | None
) -> str:
    parts: list[str] = []
    if task.goal:
        parts.append(task.goal)
    if active:
        if active.name:
            parts.append(active.name)
        if active.description:
            parts.append(active.description)
    return " ".join(parts).strip()


def _clip_jsonable(value: Any, limit: int) -> Any:
    """Clip a JSON-ish value's string representation to ``limit`` characters."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    try:
        s = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)[:limit]
    if len(s) <= limit:
        return value
    return s[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def _estimate_chars(sections: dict[str, Any]) -> int:
    total = 0
    for key, value in sections.items():
        if value is None:
            continue
        if isinstance(value, str):
            total += len(value)
        else:
            try:
                total += len(json.dumps(value, default=str))
            except (TypeError, ValueError):
                total += len(str(value))
    return total


def _fit_to_budget(sections: dict[str, Any], budget: int) -> dict[str, Any]:
    if _estimate_chars(sections) <= budget:
        return sections
    working = dict(sections)
    for key in _TRIM_ORDER:
        if _estimate_chars(working) <= budget:
            break
        value = working.get(key)
        working[key] = _shrink_section(value)
    # After shrinking once, if still over budget, drop the largest list.
    if _estimate_chars(working) > budget:
        for key in _TRIM_ORDER:
            value = working.get(key)
            if isinstance(value, list) and value:
                working[key] = []
                if _estimate_chars(working) <= budget:
                    break
    return working


def _shrink_section(value: Any) -> Any:
    if isinstance(value, list):
        if not value:
            return value
        # Keep the first half; for search hits the first is the best match.
        keep = max(1, len(value) // 2)
        return value[:keep]
    if isinstance(value, dict):
        # Preserve shape but drop long leaf strings.
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(v, str) and len(v) > 200:
                out[k] = v[:200] + "…"
            else:
                out[k] = v
        return out
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "…"
    return value


__all__ = [
    "ContextBuilder",
    "ContextBundle",
    "DEFAULT_CHAR_BUDGET",
]
