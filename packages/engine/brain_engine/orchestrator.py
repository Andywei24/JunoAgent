"""Task orchestrator.

Drives a single task from ``created`` to a terminal state. The orchestrator
is blocking and synchronous on purpose — the API layer wraps it in a thread
pool, and the DB session lifecycle is scoped per-phase so SSE consumers can
observe partial progress as phases commit.

Flow::

    created -> parsing  (goal parsing)
            -> planning (plan generation + step insertion)
            -> running  (step-by-step execution)
            -> completed | failed | waiting_for_approval (pause) | cancelled

Stage 5 introduces three gates in front of each step:

  * :class:`PolicyEngine` — may block the step outright or require human
    approval before execution. On approval-required the orchestrator pauses
    the task (transitions to ``waiting_for_approval``) and returns; the
    approval API later re-submits the task and ``run_task`` resumes from
    the step whose status is now ``ready``.
  * :class:`BudgetController` — enforces per-task LLM/step budgets. Exceeding
    a budget fails the task with a ``budget.exceeded`` event.
  * Input/output JSON-schema validation (inherited from Stage 4).

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

from brain_engine.approvals import ApprovalManager
from brain_engine.budget import BudgetController
from brain_engine.goal_parser import GoalParser
from brain_engine.planner import Planner
from brain_engine.policy import PolicyAction, PolicyEngine
from brain_engine.tool_router import ToolExecutionContext, ToolRouter
from brain_engine.tool_spec import ToolValidationError, validate_payload


log = logging.getLogger(__name__)


# Step outcomes from ``_run_single_step``. 'paused' and 'blocked' stop the
# step loop; 'completed' and 'skipped' allow the loop to continue.
_OUTCOME_COMPLETED = "completed"
_OUTCOME_PAUSED = "paused"
_OUTCOME_BLOCKED = "blocked"
_OUTCOME_SKIPPED = "skipped"


@dataclass(slots=True)
class OrchestratorDeps:
    session_factory: sessionmaker[OrmSession]
    llm: LLMService
    prompts: PromptRegistry
    tool_router: ToolRouter
    policy: PolicyEngine
    budget: BudgetController
    approvals: ApprovalManager


class Orchestrator:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self._deps = deps
        self._goal_parser = GoalParser(deps.llm, deps.prompts)
        self._planner = Planner(deps.llm, deps.prompts)
        # Wrap the LLM service so every call emits an ``llm.called`` event
        # and increments the per-task budget counter.
        deps.llm._on_call = self._on_llm_call  # type: ignore[attr-defined]
        self._active_task_id: str | None = None

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def run_task(self, task_id: str) -> None:
        self._active_task_id = task_id
        try:
            with self._session() as db:
                task = TaskRepository(db).get(task_id)
                if task is None:
                    return
                status = TaskStatus(task.status)

            if status == TaskStatus.CREATED:
                parsed_goal = self._run_parsing(task_id)
                self._run_planning(task_id, parsed_goal)
                self._transition_task_to_running(task_id)
            elif status == TaskStatus.WAITING_FOR_APPROVAL:
                # Approval API has already flipped the step back to ready and
                # the task to running — continue the step loop.
                self._transition_task_to_running(task_id)
            elif status == TaskStatus.RUNNING:
                # Re-entered mid-run (e.g., after process restart). Keep going.
                pass
            elif status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return
            else:
                log.warning(
                    "run_task called on task %s with unexpected status %s",
                    task_id,
                    status.value,
                )
                return

            paused = self._run_steps(task_id)
            if paused:
                return
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

    def _transition_task_to_running(self, task_id: str) -> None:
        with self._session() as db:
            tasks = TaskRepository(db)
            task = _require_task(tasks, task_id)
            if TaskStatus(task.status) == TaskStatus.RUNNING:
                return
            tasks.transition(task, TaskStatus.RUNNING)
            db.commit()

    def _run_steps(self, task_id: str) -> bool:
        """Iterate steps in order.

        Returns True if processing paused (e.g., waiting for approval) so the
        caller skips finalization and can be re-invoked later.
        """
        with self._session() as db:
            steps = StepRepository(db).list_for_task(task_id)
            step_ids = [s.id for s in steps]

        for step_id in step_ids:
            outcome = self._run_single_step(task_id, step_id)
            if outcome == _OUTCOME_PAUSED:
                return True
            if outcome == _OUTCOME_BLOCKED:
                # Block / budget failures already emitted their events and
                # transitioned the step; raising lets the top-level catch mark
                # the task FAILED with a meaningful reason.
                raise RuntimeError(f"step {step_id} blocked by policy or budget")
        return False

    def _run_single_step(self, task_id: str, step_id: str) -> str:
        # Phase A — pre-execution: resolve executor, run policy + budget gates,
        # validate input, transition into RUNNING. Emits tool.selected on the
        # first visit; on resume (step.status==READY) we skip re-emitting.
        with self._session() as db:
            steps_repo = StepRepository(db)
            tasks_repo = TaskRepository(db)
            events = EventRepository(db)
            step = _require_step(steps_repo, step_id)
            task = _require_task(tasks_repo, task_id)

            status = StepStatus(step.status)
            if status in {
                StepStatus.COMPLETED,
                StepStatus.SKIPPED,
                StepStatus.CANCELLED,
                StepStatus.FAILED,
            }:
                return _OUTCOME_SKIPPED
            if status == StepStatus.WAITING_FOR_APPROVAL:
                # Someone else paused this step (e.g., re-entry from a crash
                # before approval landed) — leave it alone.
                return _OUTCOME_PAUSED

            executor = self._deps.tool_router.resolve(step.required_capability)
            spec = executor.spec

            first_visit = status == StepStatus.PENDING
            if first_visit:
                step.selected_tool_id = spec.id
                events.append(
                    event_type=EventType.TOOL_SELECTED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={
                        "capability": step.required_capability,
                        "resolved_capability": spec.capability,
                        "tool_id": spec.id,
                        "tool_name": spec.name,
                        "tool_version": spec.version,
                        "risk_level": spec.risk_level.value,
                    },
                    actor_type=ActorType.SYSTEM,
                )

                decision = self._deps.policy.evaluate(step=step, tool_spec=spec)
                if decision.action == PolicyAction.BLOCK:
                    events.append(
                        event_type=EventType.POLICY_BLOCKED,
                        task_id=task_id,
                        step_id=step_id,
                        payload={
                            "tool_id": spec.id,
                            "capability": spec.capability,
                            "effective_risk": decision.effective_risk,
                            "reason": decision.reason,
                        },
                        actor_type=ActorType.SYSTEM,
                    )
                    step.error = f"policy: {decision.reason}"
                    steps_repo.transition(step, StepStatus.FAILED)
                    events.append(
                        event_type=EventType.STEP_FAILED,
                        task_id=task_id,
                        step_id=step_id,
                        payload={"error": step.error},
                        actor_type=ActorType.SYSTEM,
                    )
                    db.commit()
                    return _OUTCOME_BLOCKED

                if decision.action == PolicyAction.REQUIRE_APPROVAL:
                    self._deps.approvals.request(
                        db,
                        task=task,
                        step=step,
                        requested_action=(
                            f"run tool {spec.name} for step '{step.name}'"
                        ),
                        risk_level=decision.effective_risk,
                        reason=decision.reason,
                        data_involved={
                            "capability": spec.capability,
                            "tool_id": spec.id,
                            "input_keys": sorted(
                                (step.input_payload or {}).keys()
                            ),
                        },
                    )
                    db.commit()
                    return _OUTCOME_PAUSED

            # Budget gate — runs on both first visit and resume so late-edited
            # budget limits still take effect.
            budget_decision = self._deps.budget.check(task)
            if not budget_decision.ok:
                events.append(
                    event_type=EventType.BUDGET_EXCEEDED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={
                        "reason": budget_decision.reason,
                        "limit": budget_decision.limit or {},
                        "used": budget_decision.used or {},
                    },
                    actor_type=ActorType.SYSTEM,
                )
                step.error = f"budget: {budget_decision.reason}"
                steps_repo.transition(step, StepStatus.FAILED)
                events.append(
                    event_type=EventType.STEP_FAILED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={"error": step.error},
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
                return _OUTCOME_BLOCKED

            input_payload = step.input_payload or {}
            try:
                validate_payload(
                    input_payload,
                    spec.input_schema,
                    tool_id=spec.id,
                    direction="input",
                )
            except ToolValidationError as exc:
                step.error = str(exc)
                # Make sure the step is in a state we can fail from.
                if StepStatus(step.status) in {
                    StepStatus.PENDING,
                    StepStatus.READY,
                }:
                    steps_repo.transition(step, StepStatus.FAILED)
                else:
                    step.status = StepStatus.FAILED.value
                events.append(
                    event_type=EventType.TOOL_FAILED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={
                        "tool_id": spec.id,
                        "stage": "input_validation",
                        "errors": exc.errors,
                    },
                    actor_type=ActorType.SYSTEM,
                )
                events.append(
                    event_type=EventType.STEP_FAILED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={"error": str(exc)},
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
                raise RuntimeError(f"step {step_id} failed: {exc}") from exc

            # PENDING→READY is only valid on the first visit; on resume the
            # step is already READY (approval manager put it there).
            if StepStatus(step.status) == StepStatus.PENDING:
                steps_repo.transition(step, StepStatus.READY)
            steps_repo.transition(step, StepStatus.RUNNING)

            events.append(
                event_type=EventType.TOOL_STARTED,
                task_id=task_id,
                step_id=step_id,
                payload={
                    "tool_id": spec.id,
                    "input_keys": sorted(input_payload.keys()),
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
                input_payload=input_payload,
            )
            db.commit()

        # Phase B — execute outside the DB session.
        output: dict[str, Any] | None = None
        error: str | None = None
        validation_errors: list[str] | None = None
        try:
            output = executor.execute(ctx)
            validate_payload(
                output,
                spec.output_schema,
                tool_id=spec.id,
                direction="output",
            )
        except ToolValidationError as exc:
            log.warning("step %s output failed validation: %s", step_id, exc)
            validation_errors = exc.errors
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - per-step isolation
            log.exception("step %s failed", step_id)
            error = f"{type(exc).__name__}: {exc}"

        # Phase C — persist result, update budget, emit terminal events.
        with self._session() as db:
            steps_repo = StepRepository(db)
            tasks_repo = TaskRepository(db)
            events = EventRepository(db)
            step = _require_step(steps_repo, step_id)
            task = _require_task(tasks_repo, task_id)

            # Count this as a consumed step regardless of outcome — failed
            # attempts still burn budget.
            self._deps.budget.record_step(task)

            if error is None:
                step.output_payload = output
                events.append(
                    event_type=EventType.TOOL_COMPLETED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={
                        "tool_id": spec.id,
                        "output_keys": sorted((output or {}).keys()),
                    },
                    actor_type=ActorType.SYSTEM,
                )
                steps_repo.transition(step, StepStatus.COMPLETED)
                events.append(
                    event_type=EventType.STEP_COMPLETED,
                    task_id=task_id,
                    step_id=step_id,
                    payload={"output": output},
                    actor_type=ActorType.SYSTEM,
                )
                db.commit()
                return _OUTCOME_COMPLETED

            step.error = error
            tool_failure_payload: dict[str, Any] = {
                "tool_id": spec.id,
                "stage": (
                    "output_validation" if validation_errors else "execution"
                ),
                "error": error,
            }
            if validation_errors is not None:
                tool_failure_payload["errors"] = validation_errors
            events.append(
                event_type=EventType.TOOL_FAILED,
                task_id=task_id,
                step_id=step_id,
                payload=tool_failure_payload,
                actor_type=ActorType.SYSTEM,
            )
            steps_repo.transition(step, StepStatus.FAILED)
            events.append(
                event_type=EventType.STEP_FAILED,
                task_id=task_id,
                step_id=step_id,
                payload={"error": error},
                actor_type=ActorType.SYSTEM,
            )
            db.commit()
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
                tasks = TaskRepository(db)
                events = EventRepository(db)
                task = tasks.get(task_id)
                if task is not None:
                    self._deps.budget.record_llm(
                        task, cost_usd=response.usage.cost_usd
                    )
                events.append(
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
