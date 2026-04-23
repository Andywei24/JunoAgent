"""Stage 6 end-to-end verification.

Exercises the Memory + Context Builder layer on top of the Stage 5 loop:

  * Summarize-on-finalize — a completed task writes a ``long_term`` memory
    so later tasks can recall it.
  * Cross-task memory recall — a second task's ContextBuilder surfaces the
    first task's summary when the goals overlap, and a ``memory.retrieved``
    event is attributed to the current task.
  * Memory API — ``POST`` / ``GET`` / ``GET /search`` / ``DELETE`` under
    ``/v1/memories`` all round-trip for the current user and do not leak
    the stored embedding vector.
  * Cross-user isolation — User A's memories are invisible to user B.

Uses the mock LLM provider. Each check is hermetic: scenario-scoped users
and tasks, with memory rows torn down at the end.
"""

from __future__ import annotations

import os
import sys
import traceback
import uuid
from typing import Any, Callable

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    load_dotenv()
except Exception:
    pass

from brain_api.config import get_settings
from brain_api.services import build_services
from brain_core.enums import EventType, MemoryType, TaskStatus
from brain_db.repositories import (
    EventRepository,
    MemoryRepository,
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

    print(f"{CYAN}Brain Agent Platform — Stage 6 verification{RESET}")
    os.environ["LLM_PROVIDER"] = "mock"

    settings = get_settings()
    services = build_services(settings)
    factory = services.session_factory

    failures: list[str] = []
    created_user_ids: list[str] = []

    def _new_user(label: str) -> str:
        uid = f"user_stage6_{label}_{uuid.uuid4().hex[:6]}"
        with factory() as db:
            UserRepository(db).upsert_dev_user(uid, email=f"{uid}@local")
            db.commit()
        created_user_ids.append(uid)
        return uid

    # ------------------------------------------------------------------
    # 1. Summarize-on-finalize + cross-task recall.
    # ------------------------------------------------------------------
    _section("1. Summary write + cross-task recall")

    recall_user: dict[str, str] = {}
    first_task: dict[str, str] = {}
    second_task: dict[str, str] = {}

    def seed_user_and_run_first_task() -> None:
        uid = _new_user("recall")
        recall_user["id"] = uid
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=uid,
                goal="Compare two CRMs (HubSpot vs Salesforce) for a 5-person team.",
            )
            first_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(first_task["id"])

    def first_task_completed() -> None:
        with factory() as db:
            task = TaskRepository(db).get(first_task["id"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value, task.status
            assert task.final_output, "expected final_output on completed task"

    def summary_memory_written() -> None:
        uid = recall_user["id"]
        with factory() as db:
            mems = MemoryRepository(db).list_for_user(uid, limit=50)
            summaries = [m for m in mems if m.task_id == first_task["id"]]
            assert summaries, "expected a task summary memory to exist"
            m = summaries[0]
            assert m.memory_type == MemoryType.LONG_TERM.value, m.memory_type
            assert (m.meta or {}).get("source") == "task_summary"
            # Embedding must be attached for semantic search.
            assert isinstance((m.meta or {}).get("embedding"), list)
            # memory.written event was emitted with this task_id.
            events = EventRepository(db).list_for_task(first_task["id"], limit=500)
            written = [
                e for e in events
                if e.event_type == EventType.MEMORY_WRITTEN.value
            ]
            assert written, "expected a memory.written event for the summary"

    def second_task_recalls_prior_summary() -> None:
        uid = recall_user["id"]
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=uid,
                goal="Compare CRMs for another small team and recommend one.",
            )
            second_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(second_task["id"])

        with factory() as db:
            events = EventRepository(db).list_for_task(second_task["id"], limit=500)
            retrieved = [
                e for e in events
                if e.event_type == EventType.MEMORY_RETRIEVED.value
            ]
            assert retrieved, "expected a memory.retrieved event on the second task"
            # At least one retrieval should have surfaced the first task's summary.
            hit_task_ids: set[str] = set()
            for ev in retrieved:
                for mid in (ev.payload or {}).get("hit_ids", []):
                    row = MemoryRepository(db).get(mid)
                    if row is not None and row.task_id:
                        hit_task_ids.add(row.task_id)
            assert first_task["id"] in hit_task_ids, (
                f"first task summary never surfaced; hit tasks={hit_task_ids!r}"
            )

    for name, fn in [
        ("first task runs to completion", seed_user_and_run_first_task),
        ("task completed with final_output", first_task_completed),
        ("summarize_task wrote a long-term memory + event", summary_memory_written),
        ("second task's context builder surfaces the first summary", second_task_recalls_prior_summary),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # 2. Memory API round-trip.
    # ------------------------------------------------------------------
    _section("2. Memory HTTP API")

    api_user: dict[str, str] = {}
    api_state: dict[str, Any] = {}

    def _client_for(user_id: str):
        from fastapi.testclient import TestClient

        from brain_api.deps import CurrentUser, get_current_user
        from brain_api.main import app

        def _override() -> CurrentUser:
            return CurrentUser(id=user_id, email=f"{user_id}@local")

        app.dependency_overrides[get_current_user] = _override
        return TestClient(app), app

    def api_create_memory() -> None:
        uid = _new_user("api")
        api_user["id"] = uid
        client, app = _client_for(uid)
        try:
            r = client.post(
                "/v1/memories",
                json={
                    "content": "Prefer GraphQL for small teams because onboarding is faster.",
                    "memory_type": "long_term",
                    "summary": "graphql small teams",
                    "importance": 0.4,
                },
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["id"].startswith("mem_")
            assert body["user_id"] == uid
            # Embedding must not leak to the API.
            assert "embedding" not in body["metadata"]
            api_state["memory_id"] = body["id"]
        finally:
            app.dependency_overrides.clear()

    def api_list_and_search() -> None:
        uid = api_user["id"]
        client, app = _client_for(uid)
        try:
            # Seed a second, unrelated memory so search has to pick.
            client.post(
                "/v1/memories",
                json={
                    "content": "Reviewed banana bread recipes; walnut version preferred.",
                    "memory_type": "long_term",
                    "summary": "banana bread recipe",
                },
            )
            r = client.get("/v1/memories")
            assert r.status_code == 200
            ids = [row["id"] for row in r.json()]
            assert api_state["memory_id"] in ids

            r = client.get("/v1/memories/search", params={"q": "graphql rest tradeoffs"})
            assert r.status_code == 200, r.text
            hits = r.json()
            assert hits, "expected at least one search hit"
            top = hits[0]
            assert "graphql" in (top["item"]["summary"] or "").lower()
        finally:
            app.dependency_overrides.clear()

    def api_delete_memory() -> None:
        uid = api_user["id"]
        client, app = _client_for(uid)
        mid = api_state["memory_id"]
        try:
            r = client.delete(f"/v1/memories/{mid}")
            assert r.status_code == 204
            r = client.get("/v1/memories")
            assert mid not in [row["id"] for row in r.json()]
        finally:
            app.dependency_overrides.clear()

    def api_cross_user_isolation() -> None:
        uid_a = api_user["id"]
        uid_b = _new_user("api_other")
        # Write a memory as user B directly.
        with factory() as db:
            repo = MemoryRepository(db)
            row = repo.create(
                user_id=uid_b,
                memory_type=MemoryType.LONG_TERM,
                content="secret note for another user",
            )
            db.commit()
            other_id = row.id

        client, app = _client_for(uid_a)
        try:
            r = client.get("/v1/memories")
            assert other_id not in [m["id"] for m in r.json()]
            r = client.delete(f"/v1/memories/{other_id}")
            assert r.status_code == 404
        finally:
            app.dependency_overrides.clear()

    for name, fn in [
        ("POST /v1/memories creates + redacts embedding", api_create_memory),
        ("GET /v1/memories and /search return user rows", api_list_and_search),
        ("DELETE /v1/memories/{id} removes the row", api_delete_memory),
        ("cross-user memory is invisible + undeletable", api_cross_user_isolation),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # Teardown — delete everything we wrote so re-running stays clean.
    # ------------------------------------------------------------------
    try:
        with factory() as db:
            repo = MemoryRepository(db)
            for uid in created_user_ids:
                for row in repo.list_for_user(uid, limit=500):
                    db.delete(row)
            db.commit()
    except Exception:
        pass

    _section("Summary")
    if failures:
        print(f"{RED}FAILED{RESET} — {len(failures)} check(s) did not pass.")
        for n in failures:
            print(f"  - {n}")
        return 1

    print(f"{GREEN}All checks passed.{RESET}")
    print(
        f"{DIM}Users: recall={recall_user.get('id')}, api={api_user.get('id')}"
        f" · Tasks: first={first_task.get('id')}, second={second_task.get('id')}{RESET}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
