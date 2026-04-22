"""Stage 2 end-to-end verification.

Drives the full Core Brain MVP loop through the in-process engine:

  * Build the service container (mock LLM + default prompt registry + engine)
  * Create a user + task
  * Run the orchestrator synchronously
  * Assert the task reaches ``completed`` with a populated ``final_output``
  * Assert the expected events were emitted in order (task.created,
    goal.parsed, plan.generated, step.started, step.completed, task.completed)
  * Assert every plan step ran to ``completed`` and recorded a tool id

Runs against the real Postgres database (requires the Stage 1 schema) but
does not require ``ANTHROPIC_API_KEY``; the mock provider supplies
deterministic canned responses.

Usage::

    python scripts/verify_stage2.py
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Callable

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    load_dotenv()
except Exception:
    pass

from brain_api.config import get_settings
from brain_api.services import build_services
from brain_core.enums import EventType, StepStatus, TaskStatus
from brain_db.repositories import (
    EventRepository,
    StepRepository,
    TaskRepository,
    UserRepository,
)


GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def _section(title: str) -> None:
    print(f"\n{CYAN}{title}{RESET}")


def run_check(name: str, fn: Callable[[], None]) -> bool:
    try:
        fn()
    except Exception as exc:
        _fail(f"{name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False
    _ok(name)
    return True


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print(f"{RED}DATABASE_URL is not set. Copy .env.example to .env first.{RESET}")
        return 2

    print(f"{CYAN}Brain Agent Platform — Stage 2 verification{RESET}")
    # Force mock provider regardless of env so this script works offline.
    os.environ["LLM_PROVIDER"] = "mock"

    settings = get_settings()
    services = build_services(settings)
    factory = services.session_factory

    failures: list[str] = []

    _section("1. Seed user + task")

    task_id_holder: dict[str, str] = {}

    def seed() -> None:
        with factory() as db:
            users = UserRepository(db)
            tasks = TaskRepository(db)
            user = users.upsert_dev_user("user_stage2", email="stage2@local")
            task = tasks.create(
                user_id=user.id,
                goal="Summarize the core differences between REST and GraphQL.",
            )
            task_id_holder["id"] = task.id
            db.commit()

    if not run_check("seed dev user + task row", seed):
        failures.append("seed")

    _section("2. Run orchestrator")

    def run_orchestrator() -> None:
        services.orchestrator.run_task(task_id_holder["id"])

    if not run_check("orchestrator completes synchronously", run_orchestrator):
        failures.append("orchestrator")

    _section("3. Verify final state")

    def check_task_completed() -> None:
        with factory() as db:
            task = TaskRepository(db).get(task_id_holder["id"])
            assert task is not None, "task row vanished"
            assert task.status == TaskStatus.COMPLETED.value, (
                f"expected completed, got {task.status}; "
                f"failure_reason={task.failure_reason!r}"
            )
            assert task.parsed_goal, "parsed_goal was not populated"
            assert task.final_output, "final_output was not populated"
            assert "step_summaries" in task.final_output

    def check_steps_completed() -> None:
        with factory() as db:
            steps = StepRepository(db).list_for_task(task_id_holder["id"])
            assert steps, "no steps created"
            for s in steps:
                assert s.status == StepStatus.COMPLETED.value, (
                    f"step {s.id} ended in status {s.status}"
                )
                assert s.output_payload is not None, f"step {s.id} has no output"

    def check_tool_selection_events() -> None:
        with factory() as db:
            rows = EventRepository(db).list_for_task(
                task_id_holder["id"], limit=2000
            )
            selected = [
                r for r in rows if r.event_type == EventType.TOOL_SELECTED.value
            ]
            assert selected, "no tool.selected events emitted"
            for r in selected:
                assert r.payload.get("tool_id"), (
                    f"tool.selected event {r.id} missing tool_id in payload"
                )

    def check_event_sequence() -> None:
        with factory() as db:
            rows = EventRepository(db).list_for_task(
                task_id_holder["id"], limit=2000
            )
            kinds = [r.event_type for r in rows]
            required_in_order = [
                EventType.TASK_CREATED.value,
                EventType.GOAL_PARSED.value,
                EventType.PLAN_GENERATED.value,
                EventType.STEP_STARTED.value,
                EventType.STEP_COMPLETED.value,
                EventType.TASK_COMPLETED.value,
            ]
            idx = 0
            for k in kinds:
                if idx < len(required_in_order) and k == required_in_order[idx]:
                    idx += 1
            if idx != len(required_in_order):
                raise AssertionError(
                    f"missing required event ordering; got kinds={kinds}"
                )
            # Sequences must be strictly increasing.
            seqs = [r.sequence for r in rows]
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
                f"event sequences out of order: {seqs}"
            )

    def check_llm_events_recorded() -> None:
        with factory() as db:
            rows = EventRepository(db).list_for_task(
                task_id_holder["id"], limit=2000
            )
            llm_events = [
                r for r in rows if r.event_type == EventType.LLM_CALLED.value
            ]
            # goal_parser + planner + one per step
            with factory() as db2:
                step_count = len(
                    StepRepository(db2).list_for_task(task_id_holder["id"])
                )
            expected = 2 + step_count
            assert len(llm_events) >= expected, (
                f"expected at least {expected} llm.called events, got {len(llm_events)}"
            )

    for name, fn in [
        ("task reached status=completed with final_output", check_task_completed),
        ("all steps completed with output_payload populated", check_steps_completed),
        ("tool.selected events carry tool_id in payload", check_tool_selection_events),
        ("required events appear in order with increasing sequences",
         check_event_sequence),
        ("llm.called events emitted for each LLM turn", check_llm_events_recorded),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    _section("Summary")
    if failures:
        print(f"{RED}FAILED{RESET} — {len(failures)} check(s) did not pass.")
        for n in failures:
            print(f"  - {n}")
        return 1

    print(f"{GREEN}All checks passed.{RESET}")
    print(f"{DIM}Task id: {task_id_holder['id']}{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
