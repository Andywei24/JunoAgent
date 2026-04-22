"""Task orchestrator.

Drives a single task from ``created`` to a terminal state. The orchestrator
is blocking and synchronous on purpose — the API layer wraps it in a thread
pool, and the DB session lifecycle is scoped per-phase so SSE consumers can
observe partial progress as phases commit.

Flow::

    created -> parsing  (goal parsing)
            -> planning (plan generation + step insertion)
            -> running  (step-by-step execution)
            -> completed | failed

Any unexpected exception is funneled into a ``failed`` transition with the
exception class + message recorded on the task. That makes test runs
predictable and keeps bad LLM output from leaving tasks stuck in a non-
terminal state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from brain_core.enums import ActorType, EventType, StepStatus, TaskStatus
from brain_db import models
from brain_db.repositories import (
    EventRepository,
    StepRepository,
    TaskRepository,
)
from brain_llm.service import LLMService
from brain_llm.types import LLMRequest, LLMResponse
from brain_prompts.registry import PromptRegistry

from brain_engine.goal_parser import GoalParser
from brain_engine.planner import Planner
from brain_engine.tool_router import ToolExecutionContext, ToolRouter


log = logging.getLogger(__name__)


@dataclass(slots=True)
class OrchestratorDeps:
    session_factory: sessionmaker[OrmSession]
    llm: LLMService
    prompts: PromptRegistry
    tool_router: ToolRouter


class Orchestrator:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self._deps = deps
        self._goal_parser = GoalParser(deps.llm, deps.prompts)
        self._planner = Planner(deps.llm, deps.prompts)
        # Wrap the LLM service so every call emits an ``llm.called`` event.
        deps.llm._on_call = self._on_llm_call  # type: ignore[attr-defined]
        self._active_task_id: str | None = None

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def run_task(self, task_id: str) -> None:
        self._active_task_id = task_id
        try:
            parsed_goal = self._run_parsing(task_id)
            plan = self._run_planning(task_id, parsed_goal)
            self._run_steps(task_id, parsed_goal, plan)
            self._finalize(task_id)
        except Exception as exc:  # noqa: BLE001 - top-level guard on purpose
            log.exception("orchestrator failed for task %s", task_id)
            self._mark_failed(task_id, exc)
        finally:
            self._active_task_id = None

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    def _run_parsing(self, task_id: str) -> dict[str, Any]:
        with self._session() as db:
            tasks = TaskRepository(db)
            events = EventRepository(db)
            task = _require_task(tasks, task_id)
            tasks.transition(task, TaskStatus.PARSING)
            goal = task.goal
            events.append(
                event_type=EventType.TASK_CREATED,
                task_id=task_id,
                payload={"goal": goal},
                actor_type=ActorType.SYSTEM,
            )
            db.commit()

        parsed = self._goal_parser.parse(goal, task_id=task_id)

        with self._session() as db:
            tasks = TaskRepository(db)
            events = EventRepository(db)
            task = _require_task(tasks, task_id)
            task.parsed_goal = parsed
            task.risk_level = parsed.get("risk_level", task.risk_level)
            events.append(
                event_type=EventType.GOAL_PARSED,
                task_id=task_id,
                payload={"parsed_goal": parsed},
                actor_type=ActorType.SYSTEM,
            )
            db.commit()

        return parsed

    def _run_planning(
        self, task_id: str, parsed_goal: dict[str, Any]
    ) -> dict[str, Any]:
        with self._session() as db:
            tasks = TaskRepository(db)
            task = _require_task(tasks, task_id)
            tasks.transition(task, TaskStatus.PLANNING)
            goal = task.goal
            db.commit()

        plan = self._planner.plan(goal=goal, parsed_goal=parsed_goal, task_id=task_id)
        step_specs = plan.get("steps", [])
        if not step_specs:
            raise RuntimeError("planner produced an empty plan")

        with self._session() as db:
            steps_repo = StepRepository(db)
            events = EventRepository(db)
            steps_repo.create_many(task_id, step_specs)
            events.append(
                event_type=EventType.PLAN_GENERATED,
                task_id=task_id,
                payload={
                    "plan": plan,
                    "step_count": len(step_specs),
                },
                actor_type=ActorType.SYSTEM,
            )
            db.commit()

        return plan

    def _run_steps(
        self,
        task_id: str,
        parsed_goal: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        with self._session() as db:
            tasks = TaskRepository(db)
            task = _require_task(tasks, task_id)
            tasks.transition(task, TaskStatus.RUNNING)
            db.commit()

        with self._session() as db:
            steps = StepRepository(db).list_for_task(task_id)
            step_ids = [s.id for s in steps]

        for step_id in step_ids:
            self._run_single_step(task_id, step_id)

    def _run_single_step(self, task_id: str, step_id: str) -> None:
        # Phase A: pending -> ready -> running, record selected tool, emit events.
        with self._session() as db:
            steps_repo = StepRepository(db)
            tasks_repo = TaskRepository(db)
            events = EventRepository(db)
            step = _require_step(steps_repo, step_id)
            task = _require_task(tasks_repo, task_id)
            executor = self._deps.tool_router.resolve(step.required_capability)
            # `selected_tool_id` is a FK to the `tools` table, which only holds
            # registered external tools. Stage 2 uses an in-process executor,
            # so we record its logical id on the `tool.selected` event payload
            # instead and leave the FK column null.
            steps_repo.transition(step, StepStatus.READY)
            steps_repo.transition(step, StepStatus.RUNNING)
            events.append(
                event_type=EventType.TOOL_SELECTED,
                task_id=task_id,
                step_id=step_id,
                payload={
                    "capability": step.required_capability,
                    "tool_id": executor.tool_id,
                },
                actor_type=ActorType.SYSTEM,
            )
            events.append(
                event_type=EventType.STEP_STARTED,
                task_id=task_id,
                step_id=step_id,
                payload={"name": step.name},
                actor_type=ActorType.SYSTEM,
            )
            ctx = ToolExecutionContext(
                task_id=task_id,
                step_id=step_id,
                goal=task.goal,
                step_name=step.name,
                input_payload=step.input_payload or {},
            )
            db.commit()

        # Phase B: execute outside the DB session — the call can be slow
        # and holding a transaction here would block SSE polling.
        try:
            output = executor.execute(ctx)
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 - per-step isolation
            log.exception("step %s failed", step_id)
            output = None
            error = f"{type(exc).__name__}: {exc}"

        # Phase C: persist result and emit terminal step event.
        with self._session() as db:
            steps_repo = StepRepository(db)
            events = EventRepository(db)
            step = _require_step(steps_repo, step_id)
            if error is None:
                step.output_payload = output
                steps_repo.transition(step, StepStatus.COMPLETED)
                events.append(
                    event_type=EventType.STEP_COMPLETED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={"output": output},
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
            else:
                step.error = error
                steps_repo.transition(step, StepStatus.FAILED)
                events.append(
                    event_type=EventType.STEP_FAILED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={"error": error},
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
                # Abort the rest of the task on first step failure.
                raise RuntimeError(f"step {step_id} failed: {error}")

    def _finalize(self, task_id: str) -> None:
        with self._session() as db:
            tasks = TaskRepository(db)
            steps = StepRepository(db).list_for_task(task_id)
            events = EventRepository(db)
            task = _require_task(tasks, task_id)
            task.final_output = _synthesize_final_output(task, steps)
            tasks.transition(task, TaskStatus.COMPLETED)
            events.append(
                event_type=EventType.TASK_COMPLETED,
                task_id=task_id,
                payload={"final_output": task.final_output},
                actor_type=ActorType.SYSTEM,
            )
            db.commit()

    def _mark_failed(self, task_id: str, exc: BaseException) -> None:
        try:
            with self._session() as db:
                tasks = TaskRepository(db)
                events = EventRepository(db)
                task = tasks.get(task_id)
                if task is None:
                    return
                if TaskStatus(task.status) in {
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                }:
                    return
                task.failure_reason = f"{type(exc).__name__}: {exc}"
                tasks.transition(task, TaskStatus.FAILED)
                events.append(
                    event_type=EventType.TASK_FAILED,
                    task_id=task_id,
                    payload={"error": task.failure_reason},
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
        except Exception:  # noqa: BLE001 - last-ditch
            log.exception("failed to record task failure for %s", task_id)

    # ------------------------------------------------------------------
    # Instrumentation
    # ------------------------------------------------------------------

    def _on_llm_call(self, request: LLMRequest, response: LLMResponse) -> None:
        task_id = self._active_task_id or request.metadata.get("task_id")
        step_id = request.metadata.get("step_id")
        if not task_id:
            return
        try:
            with self._session() as db:
                EventRepository(db).append(
                    event_type=EventType.LLM_CALLED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={
                        "provider": response.provider,
                        "model": response.model,
                        "prompt_id": request.metadata.get("prompt_id"),
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "cost_usd": response.usage.cost_usd,
                    },
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
        except Exception:  # noqa: BLE001 - telemetry must never break the run
            log.exception("failed to record llm.called event")

    # ------------------------------------------------------------------
    # Session plumbing
    # ------------------------------------------------------------------

    def _session(self) -> _SessionContext:
        return _SessionContext(self._deps.session_factory)


class _SessionContext:
    """Minimal session CM; commits are explicit."""

    def __init__(self, factory: sessionmaker[OrmSession]) -> None:
        self._factory = factory
        self._session: OrmSession | None = None

    def __enter__(self) -> OrmSession:
        self._session = self._factory()
        return self._session

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._session is not None
        try:
            if exc is not None:
                self._session.rollback()
        finally:
            self._session.close()


def _require_task(repo: TaskRepository, task_id: str) -> models.Task:
    task = repo.get(task_id)
    if task is None:
        raise LookupError(f"task not found: {task_id}")
    return task


def _require_step(repo: StepRepository, step_id: str) -> models.TaskStep:
    step = repo.get(step_id)
    if step is None:
        raise LookupError(f"step not found: {step_id}")
    return step


def _synthesize_final_output(
    task: models.Task, steps: list[models.TaskStep]
) -> dict[str, Any]:
    """Collapse step outputs into a task-level result.

    Stage 2 keeps this deterministic: list the step summaries and the final
    step's full payload. Later stages will introduce a synthesis LLM pass.
    """
    step_summaries: list[dict[str, Any]] = []
    last_output: dict[str, Any] | None = None
    for step in steps:
        summary = None
        if isinstance(step.output_payload, dict):
            summary = step.output_payload.get("summary")
            last_output = step.output_payload
        step_summaries.append(
            {
                "step_id": step.id,
                "name": step.name,
                "status": step.status,
                "summary": summary,
            }
        )
    return {
        "goal": task.goal,
        "step_summaries": step_summaries,
        "last_step_output": last_output,
    }
