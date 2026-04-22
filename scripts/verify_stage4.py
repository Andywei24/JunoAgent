"""Stage 4 end-to-end verification.

Exercises the tool registry + router + validation + full tool-lifecycle
event set:

  * Builds services (which syncs registered ToolSpecs into the `tools` table)
  * Runs a task through the orchestrator and confirms steps dispatch across
    multiple capabilities (``llm_reasoning``, ``summarize_text``,
    ``compare_items``)
  * Verifies every step has ``selected_tool_id`` set and it FKs into ``tools``
  * Verifies the event stream contains tool.selected → tool.started →
    tool.completed per step, plus the Stage 2 task/step ordering
  * Runs a negative case: a step with malformed input_payload is rejected
    by the input validator before execution

Runs against Postgres + mock LLM; no network required.
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
from brain_core.enums import ActorType, EventType, StepStatus, TaskStatus
from brain_db.repositories import (
    EventRepository,
    StepRepository,
    TaskRepository,
    ToolRepository,
    UserRepository,
)
from brain_engine.tool_router import ToolExecutionContext


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

    print(f"{CYAN}Brain Agent Platform — Stage 4 verification{RESET}")
    os.environ["LLM_PROVIDER"] = "mock"

    settings = get_settings()
    services = build_services(settings)
    factory = services.session_factory

    failures: list[str] = []
    expected_tool_ids = {
        "tool_llm_reasoning",
        "tool_summarize_text",
        "tool_compare_items",
    }

    _section("1. Tool registry synced to DB")

    def check_tools_table() -> None:
        with factory() as db:
            rows = ToolRepository(db).list_enabled()
            ids = {r.id for r in rows}
            missing = expected_tool_ids - ids
            assert not missing, f"missing tools in registry: {missing}"
            for r in rows:
                if r.id in expected_tool_ids:
                    assert r.input_schema, f"tool {r.id} has empty input_schema"
                    assert r.output_schema, f"tool {r.id} has empty output_schema"

    if not run_check("built-in tools persisted with schemas", check_tools_table):
        failures.append("tool-registry-sync")

    _section("2. Happy path: multi-capability plan")

    task_id_holder: dict[str, str] = {}

    def seed_and_run() -> None:
        with factory() as db:
            user = UserRepository(db).upsert_dev_user(
                "user_stage4", email="stage4@local"
            )
            task = TaskRepository(db).create(
                user_id=user.id,
                goal="Compare REST and GraphQL and recommend one for a small team.",
            )
            task_id_holder["id"] = task.id
            db.commit()
        services.orchestrator.run_task(task_id_holder["id"])

    if not run_check("orchestrator completes multi-capability plan", seed_and_run):
        failures.append("orchestrator")

    def check_task_completed() -> None:
        with factory() as db:
            task = TaskRepository(db).get(task_id_holder["id"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value, (
                f"expected completed, got {task.status}; "
                f"failure_reason={task.failure_reason!r}"
            )
            assert task.final_output

    def check_steps_used_distinct_tools() -> None:
        with factory() as db:
            steps = StepRepository(db).list_for_task(task_id_holder["id"])
            assert steps, "no steps created"
            tool_ids = set()
            for s in steps:
                assert s.status == StepStatus.COMPLETED.value, (
                    f"step {s.id} ended {s.status}"
                )
                assert s.selected_tool_id, f"step {s.id} missing selected_tool_id"
                assert s.selected_tool_id in expected_tool_ids, (
                    f"step {s.id} has unknown tool_id {s.selected_tool_id!r}"
                )
                tool_ids.add(s.selected_tool_id)
            # Plan exercises at least two distinct capabilities.
            assert len(tool_ids) >= 2, (
                f"plan only used {len(tool_ids)} tool(s): {tool_ids}"
            )

    def check_tool_lifecycle_events() -> None:
        with factory() as db:
            rows = EventRepository(db).list_for_task(
                task_id_holder["id"], limit=2000
            )
        # Each step must emit tool.selected -> tool.started -> tool.completed
        # in order before step.completed.
        by_step: dict[str, list[str]] = {}
        for r in rows:
            if r.step_id and r.event_type.startswith("tool."):
                by_step.setdefault(r.step_id, []).append(r.event_type)
        assert by_step, "no tool.* events emitted"
        for step_id, kinds in by_step.items():
            required = [
                EventType.TOOL_SELECTED.value,
                EventType.TOOL_STARTED.value,
                EventType.TOOL_COMPLETED.value,
            ]
            idx = 0
            for k in kinds:
                if idx < len(required) and k == required[idx]:
                    idx += 1
            assert idx == len(required), (
                f"step {step_id} missing tool-lifecycle ordering; got {kinds}"
            )

    for name, fn in [
        ("task completed with final_output", check_task_completed),
        ("steps used distinct tools (FKs resolve)", check_steps_used_distinct_tools),
        (
            "tool.selected → tool.started → tool.completed per step",
            check_tool_lifecycle_events,
        ),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    _section("3. Input validation rejects malformed payload")

    def check_input_validation() -> None:
        from brain_engine.tool_spec import ToolValidationError

        executor = services.tool_router.resolve("summarize_text")
        ctx = ToolExecutionContext(
            task_id="task_validation_probe",
            step_id="step_validation_probe",
            goal="negative test",
            step_name="malformed input",
            input_payload={"focus": "missing text field"},  # no "text"
        )
        # validate_payload is what the orchestrator uses — drive it directly.
        from brain_engine.tool_spec import validate_payload

        try:
            validate_payload(
                ctx.input_payload,
                executor.spec.input_schema,
                tool_id=executor.spec.id,
                direction="input",
            )
        except ToolValidationError as exc:
            assert any("text" in e for e in exc.errors), (
                f"expected 'text' in validation errors, got {exc.errors}"
            )
            return
        raise AssertionError("validator did not reject missing required field")

    if not run_check("missing required input field rejected", check_input_validation):
        failures.append("input-validation")

    _section("4. GET /v1/tools surfaces the registry")

    def check_tools_endpoint_shape() -> None:
        from fastapi.testclient import TestClient

        from brain_api.main import app

        client = TestClient(app)
        resp = client.get("/v1/tools")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = {row["id"] for row in body}
        missing = expected_tool_ids - ids
        assert not missing, f"tools endpoint missing {missing}"
        for row in body:
            assert row["enabled"] is True
            assert row["input_schema"] and row["output_schema"]

    if not run_check("/v1/tools lists registered tools", check_tools_endpoint_shape):
        failures.append("tools-endpoint")

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
