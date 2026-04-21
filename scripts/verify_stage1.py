"""Stage 1 end-to-end verification.

Exercises everything the foundation promises:

  * DB connectivity through `brain_db.session`
  * Schema presence (all 8 tables + append-only trigger on `events`)
  * UserRepository.upsert_dev_user idempotence
  * TaskRepository.create + valid state-machine transitions
  * StepRepository.create_many + step state transitions
  * EventRepository.append + ordered read-back
  * Invalid state transitions raise StateTransitionError
  * Direct UPDATE / DELETE on `events` is blocked by the DB trigger

Run after `docker compose up -d postgres` and `alembic upgrade head`:

    python scripts/verify_stage1.py

Exits 0 on success, non-zero with a readable error on the first failure.
Safe to run repeatedly — each run creates a fresh task.
"""

from __future__ import annotations

import os
import sys
import traceback
from contextlib import contextmanager
from typing import Callable

# Ensure .env is honored when run outside uvicorn
try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    load_dotenv()
except Exception:
    pass

from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from brain_core.enums import (
    ActorType,
    EventType,
    StepStatus,
    TaskStatus,
)
from brain_core.state_machine import StateTransitionError
from brain_db import session as db_session
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

EXPECTED_TABLES = {
    "users",
    "sessions",
    "tasks",
    "task_steps",
    "events",
    "approvals",
    "tools",
    "memories",
}


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def _section(title: str) -> None:
    print(f"\n{CYAN}{title}{RESET}")


@contextmanager
def step(name: str):
    print(f"  {DIM}· {name}...{RESET}", end="", flush=True)
    try:
        yield
    except Exception:
        print(f"\r  {RED}✗{RESET} {name}                 ")
        raise
    else:
        print(f"\r  {GREEN}✓{RESET} {name}                 ")


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
    url = os.environ.get("DATABASE_URL")
    if not url:
        print(f"{RED}DATABASE_URL is not set. Copy .env.example to .env first.{RESET}")
        return 2

    print(f"{CYAN}Brain Agent Platform — Stage 1 verification{RESET}")
    print(f"{DIM}DATABASE_URL = {url}{RESET}")

    db_session.init_engine(url)
    assert db_session.SessionLocal is not None
    session_factory = db_session.SessionLocal

    failures: list[str] = []

    # ------------------------------------------------------------------
    _section("1. Connectivity + schema")

    def check_connect() -> None:
        with session_factory() as s:
            s.execute(text("SELECT 1")).scalar_one()

    def check_tables() -> None:
        with session_factory() as s:
            insp = inspect(s.bind)
            present = set(insp.get_table_names())
            missing = EXPECTED_TABLES - present
            if missing:
                raise AssertionError(f"missing tables: {sorted(missing)}")

    def check_append_only_trigger() -> None:
        with session_factory() as s:
            rows = s.execute(
                text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = 'events'::regclass"
                    " AND tgname IN ('events_no_update','events_no_delete')"
                )
            ).scalars().all()
            if set(rows) != {"events_no_update", "events_no_delete"}:
                raise AssertionError(f"append-only triggers missing, found: {rows}")

    for name, fn in [
        ("postgres reachable", check_connect),
        ("all 8 tables present", check_tables),
        ("append-only triggers installed on events", check_append_only_trigger),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    if failures:
        print(f"\n{RED}Schema failed. Did you run `alembic upgrade head`?{RESET}")
        return 1

    # ------------------------------------------------------------------
    _section("2. Repositories + state machine (happy path)")

    task_id_holder: dict[str, str] = {}
    step_ids: list[str] = []

    def create_and_transition_task() -> None:
        with session_factory() as s:
            users = UserRepository(s)
            tasks = TaskRepository(s)
            steps = StepRepository(s)
            events = EventRepository(s)

            user = users.upsert_dev_user("user_verify", email="verify@local")
            # Idempotence
            user2 = users.upsert_dev_user("user_verify", email="verify@local")
            assert user.id == user2.id, "upsert_dev_user not idempotent"

            task = tasks.create(
                user_id=user.id,
                goal="Verify Stage 1 foundation.",
                budget_limit={"max_cost_usd": 1.0},
            )
            task_id_holder["id"] = task.id
            assert task.status == TaskStatus.CREATED.value

            # created -> parsing -> planning -> running
            tasks.transition(task, TaskStatus.PARSING)
            events.append(
                event_type=EventType.TASK_CREATED,
                task_id=task.id,
                payload={"goal": task.goal},
                actor_type=ActorType.SYSTEM,
                actor_id="verify-script",
            )
            tasks.transition(task, TaskStatus.PLANNING)
            events.append(
                event_type=EventType.GOAL_PARSED,
                task_id=task.id,
                payload={"objective": "verify"},
                actor_type=ActorType.SYSTEM,
            )

            made = steps.create_many(
                task.id,
                [
                    {"name": "step one", "sequence_order": 0},
                    {"name": "step two", "sequence_order": 1, "dependencies": []},
                ],
            )
            step_ids.extend(s_.id for s_ in made)
            events.append(
                event_type=EventType.PLAN_GENERATED,
                task_id=task.id,
                payload={"step_count": len(made)},
            )

            tasks.transition(task, TaskStatus.RUNNING)
            first = made[0]
            steps.transition(first, StepStatus.READY)
            steps.transition(first, StepStatus.RUNNING)
            events.append(
                event_type=EventType.STEP_STARTED,
                task_id=task.id,
                step_id=first.id,
            )
            steps.transition(first, StepStatus.COMPLETED)
            events.append(
                event_type=EventType.STEP_COMPLETED,
                task_id=task.id,
                step_id=first.id,
                payload={"output": "ok"},
            )

            tasks.transition(task, TaskStatus.COMPLETED)
            events.append(
                event_type=EventType.TASK_COMPLETED,
                task_id=task.id,
                payload={"summary": "verified"},
            )
            s.commit()

    def read_events_back() -> None:
        task_id = task_id_holder["id"]
        with session_factory() as s:
            events = EventRepository(s)
            rows = events.list_for_task(task_id)
            kinds = [r.event_type for r in rows]
            expected = [
                EventType.TASK_CREATED.value,
                EventType.GOAL_PARSED.value,
                EventType.PLAN_GENERATED.value,
                EventType.STEP_STARTED.value,
                EventType.STEP_COMPLETED.value,
                EventType.TASK_COMPLETED.value,
            ]
            if kinds != expected:
                raise AssertionError(f"event order wrong: {kinds} != {expected}")
            # Sequences must be strictly increasing
            seqs = [r.sequence for r in rows]
            if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
                raise AssertionError(f"event sequences not strictly increasing: {seqs}")

    for name, fn in [
        ("create user + task + steps + 6 events, walk state machine to completed",
         create_and_transition_task),
        ("events read back in sequence order", read_events_back),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    _section("3. Negative paths")

    def invalid_transition_raises() -> None:
        with session_factory() as s:
            tasks = TaskRepository(s)
            task = tasks.get(task_id_holder["id"])
            assert task is not None
            try:
                tasks.transition(task, TaskStatus.RUNNING)  # completed -> running
            except StateTransitionError:
                return
            raise AssertionError("expected StateTransitionError from completed->running")

    def event_update_blocked() -> None:
        with session_factory() as s:
            try:
                s.execute(
                    text(
                        "UPDATE events SET payload = '{}'::jsonb WHERE task_id = :t"
                    ),
                    {"t": task_id_holder["id"]},
                )
                s.commit()
            except DBAPIError as exc:
                s.rollback()
                if "append-only" not in str(exc).lower():
                    raise AssertionError(
                        f"UPDATE blocked but wrong reason: {exc}"
                    ) from exc
                return
            raise AssertionError("UPDATE on events was not blocked")

    def event_delete_blocked() -> None:
        with session_factory() as s:
            try:
                s.execute(
                    text("DELETE FROM events WHERE task_id = :t"),
                    {"t": task_id_holder["id"]},
                )
                s.commit()
            except DBAPIError as exc:
                s.rollback()
                if "append-only" not in str(exc).lower():
                    raise AssertionError(
                        f"DELETE blocked but wrong reason: {exc}"
                    ) from exc
                return
            raise AssertionError("DELETE on events was not blocked")

    for name, fn in [
        ("invalid task transition raises StateTransitionError", invalid_transition_raises),
        ("direct UPDATE on events is blocked by trigger", event_update_blocked),
        ("direct DELETE on events is blocked by trigger", event_delete_blocked),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    _section("Summary")
    if failures:
        print(f"{RED}FAILED{RESET} — {len(failures)} check(s) did not pass:")
        for n in failures:
            print(f"  - {n}")
        return 1

    print(f"{GREEN}All checks passed.{RESET}")
    print(f"{DIM}Task created during this run: {task_id_holder['id']}{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
