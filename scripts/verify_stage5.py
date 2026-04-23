"""Stage 5 end-to-end verification.

Exercises the Policy / Budget / Approval layer on top of the Stage 4 loop:

  * Happy path — low-risk plan runs to completion (regression for Stage 4).
  * Approval pause/resume — a step flagged ``approval_required=True`` causes
    the orchestrator to pause the task; :class:`ApprovalManager.approve`
    resumes it and the task finishes.
  * Approval rejection — rejecting pins the task to ``cancelled``.
  * Budget enforcement — ``max_steps=1`` stops the second step and raises
    a ``budget.exceeded`` event; task ends ``failed``.
  * Policy block — ``risk_level=critical`` on a step triggers a
    ``policy.blocked`` event; task ends ``failed``.
  * Approvals API — ``GET /v1/approvals`` returns pending items for the
    current user.

All checks use the mock LLM provider; we monkey-patch individual planner
responders to steer the plan per scenario and restore them afterwards so
each check is hermetic.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    load_dotenv()
except Exception:
    pass

from brain_api.config import get_settings
from brain_api.services import build_services
from brain_core.enums import (
    ApprovalStatus,
    EventType,
    StepStatus,
    TaskStatus,
)
from brain_db.repositories import (
    ApprovalRepository,
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


def _plan_with(steps: list[dict[str, Any]]) -> Callable:
    def _planner(_request):
        return {
            "steps": steps,
            "completion_criteria": "stage 5 verification plan",
        }

    return _planner


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print(f"{RED}DATABASE_URL is not set. Copy .env.example to .env first.{RESET}")
        return 2

    print(f"{CYAN}Brain Agent Platform — Stage 5 verification{RESET}")
    os.environ["LLM_PROVIDER"] = "mock"

    settings = get_settings()
    services = build_services(settings)
    factory = services.session_factory
    mock = services.llm._primary  # type: ignore[attr-defined]
    original_planner = mock._responders.get("planner/v1")

    def _install_planner(planner_fn: Callable) -> None:
        mock.register("planner/v1", planner_fn)

    def _restore_planner() -> None:
        if original_planner is not None:
            mock.register("planner/v1", original_planner)

    failures: list[str] = []

    with factory() as db:
        user = UserRepository(db).upsert_dev_user(
            "user_stage5", email="stage5@local"
        )
        user_id = user.id
        db.commit()

    # ------------------------------------------------------------------
    # 1. Happy path regression — full Stage 4 flow still green.
    # ------------------------------------------------------------------
    _section("1. Happy path (regression)")

    happy_task: dict[str, str] = {}

    def happy_seed_and_run() -> None:
        _restore_planner()
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=user_id,
                goal="Summarize REST vs GraphQL for a small team.",
            )
            happy_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(happy_task["id"])

    def happy_completes() -> None:
        with factory() as db:
            task = TaskRepository(db).get(happy_task["id"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value, task.status
            assert task.final_output

    for name, fn in [
        ("low-risk task runs end-to-end", happy_seed_and_run),
        ("task completed", happy_completes),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # 2. Approval pause/resume via ApprovalManager.
    # ------------------------------------------------------------------
    _section("2. Approval pause + resume")

    approval_steps = [
        {
            "name": "Decompose goal",
            "required_capability": "llm_reasoning",
            "risk_level": "low",
            "approval_required": False,
            "input_payload": {"instruction": "decompose_goal"},
        },
        {
            "name": "Sensitive compare",
            "required_capability": "compare_items",
            "risk_level": "low",
            # Planner flagged this step for human review.
            "approval_required": True,
            "input_payload": {
                "items": ["option_a", "option_b"],
                "criteria": ["clarity"],
            },
        },
        {
            "name": "Summarize draft",
            "required_capability": "summarize_text",
            "risk_level": "low",
            "approval_required": False,
            "input_payload": {
                "text": "Draft answer after review",
                "focus": "user takeaways",
            },
        },
    ]

    approve_task: dict[str, str] = {}

    def approval_seed_and_run() -> None:
        _install_planner(_plan_with(approval_steps))
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=user_id,
                goal="Approval-gated compare-and-summarize flow.",
            )
            approve_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(approve_task["id"])

    def approval_task_paused() -> None:
        with factory() as db:
            task = TaskRepository(db).get(approve_task["id"])
            assert task is not None
            assert task.status == TaskStatus.WAITING_FOR_APPROVAL.value, (
                f"expected waiting_for_approval, got {task.status}"
            )
            steps = StepRepository(db).list_for_task(approve_task["id"])
            paused = [
                s for s in steps
                if s.status == StepStatus.WAITING_FOR_APPROVAL.value
            ]
            assert len(paused) == 1, (
                f"expected exactly 1 paused step, got {len(paused)}"
            )
            # First step should already be completed.
            assert steps[0].status == StepStatus.COMPLETED.value, steps[0].status
            # Third step should not have started yet.
            assert steps[2].status == StepStatus.PENDING.value, steps[2].status

    def approval_row_exists() -> None:
        with factory() as db:
            approvals = ApprovalRepository(db).list_for_task(approve_task["id"])
            assert len(approvals) == 1, (
                f"expected 1 approval, got {len(approvals)}"
            )
            ap = approvals[0]
            assert ap.status == ApprovalStatus.PENDING.value, ap.status
            assert ap.step_id, "approval missing step_id"

    def approval_event_emitted() -> None:
        with factory() as db:
            rows = EventRepository(db).list_for_task(
                approve_task["id"], limit=2000
            )
            reqs = [
                r for r in rows
                if r.event_type == EventType.APPROVAL_REQUESTED.value
            ]
            assert len(reqs) == 1, (
                f"expected 1 approval.requested event, got {len(reqs)}"
            )

    def approve_and_resume() -> None:
        with factory() as db:
            ap = ApprovalRepository(db).list_for_task(approve_task["id"])[0]
            services.approvals.approve(db, ap.id, approver_id=user_id)
            db.commit()
        services.orchestrator.run_task(approve_task["id"])

    def approved_task_completes() -> None:
        with factory() as db:
            task = TaskRepository(db).get(approve_task["id"])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value, (
                f"expected completed, got {task.status}"
            )
            steps = StepRepository(db).list_for_task(approve_task["id"])
            for s in steps:
                assert s.status == StepStatus.COMPLETED.value, (
                    f"step {s.id} ended {s.status}"
                )
            rows = EventRepository(db).list_for_task(
                approve_task["id"], limit=2000
            )
            approved = [
                r for r in rows
                if r.event_type == EventType.APPROVAL_APPROVED.value
            ]
            assert len(approved) == 1, (
                f"expected 1 approval.approved event, got {len(approved)}"
            )

    for name, fn in [
        ("approval-gated task pauses", approval_seed_and_run),
        ("task + step both land in waiting_for_approval", approval_task_paused),
        ("pending approval row exists", approval_row_exists),
        ("approval.requested event emitted", approval_event_emitted),
        ("approving + resuming completes the task", approve_and_resume),
        ("all steps completed after resume", approved_task_completes),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # 3. Approval rejection cancels the task.
    # ------------------------------------------------------------------
    _section("3. Approval rejection")

    reject_task: dict[str, str] = {}

    def rejection_seed_and_run() -> None:
        _install_planner(_plan_with(approval_steps))
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=user_id,
                goal="Reject-this-approval flow.",
            )
            reject_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(reject_task["id"])

    def reject_and_verify() -> None:
        with factory() as db:
            ap = ApprovalRepository(db).list_for_task(reject_task["id"])[0]
            services.approvals.reject(
                db, ap.id, approver_id=user_id, reason="nope"
            )
            db.commit()
        with factory() as db:
            task = TaskRepository(db).get(reject_task["id"])
            assert task is not None
            assert task.status == TaskStatus.CANCELLED.value, (
                f"expected cancelled, got {task.status}"
            )
            steps = StepRepository(db).list_for_task(reject_task["id"])
            gated = [s for s in steps if s.approval_required]
            assert gated and gated[0].status == StepStatus.CANCELLED.value, (
                f"gated step status={gated[0].status if gated else 'n/a'}"
            )
            # Third step never ran.
            assert steps[2].status == StepStatus.PENDING.value, steps[2].status
            rows = EventRepository(db).list_for_task(reject_task["id"], limit=2000)
            rejects = [
                r for r in rows
                if r.event_type == EventType.APPROVAL_REJECTED.value
            ]
            assert len(rejects) == 1, (
                f"expected 1 approval.rejected event, got {len(rejects)}"
            )

    for name, fn in [
        ("rejection flow pauses task", rejection_seed_and_run),
        ("rejecting cancels the task and step", reject_and_verify),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # 4. Budget enforcement — max_steps stops mid-run.
    # ------------------------------------------------------------------
    _section("4. Budget enforcement")

    budget_task: dict[str, str] = {}

    def budget_seed_and_run() -> None:
        _restore_planner()  # default 3-step plan
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=user_id,
                goal="Budget-capped task.",
                budget_limit={"max_steps": 1},
            )
            budget_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(budget_task["id"])

    def budget_enforced() -> None:
        with factory() as db:
            task = TaskRepository(db).get(budget_task["id"])
            assert task is not None
            assert task.status == TaskStatus.FAILED.value, (
                f"expected failed, got {task.status}"
            )
            assert task.budget_used.get("max_steps") == 1, (
                f"expected 1 step recorded, got {task.budget_used}"
            )
            rows = EventRepository(db).list_for_task(budget_task["id"], limit=2000)
            exceeded = [
                r for r in rows
                if r.event_type == EventType.BUDGET_EXCEEDED.value
            ]
            assert len(exceeded) == 1, (
                f"expected 1 budget.exceeded event, got {len(exceeded)}"
            )
            steps = StepRepository(db).list_for_task(budget_task["id"])
            completed = [s for s in steps if s.status == StepStatus.COMPLETED.value]
            failed = [s for s in steps if s.status == StepStatus.FAILED.value]
            assert len(completed) == 1, (
                f"expected 1 completed step, got {len(completed)}"
            )
            assert len(failed) >= 1, "expected the over-budget step to be failed"

    for name, fn in [
        ("task with max_steps=1 runs", budget_seed_and_run),
        ("budget.exceeded event halts the task", budget_enforced),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # 5. Policy block on critical-risk step.
    # ------------------------------------------------------------------
    _section("5. Policy block on critical risk")

    critical_steps = [
        {
            "name": "Restate goal",
            "required_capability": "llm_reasoning",
            "risk_level": "low",
            "approval_required": False,
            "input_payload": {"instruction": "restate"},
        },
        {
            "name": "Critical ops action",
            "required_capability": "llm_reasoning",
            "risk_level": "critical",
            "approval_required": False,
            "input_payload": {"instruction": "danger"},
        },
    ]
    block_task: dict[str, str] = {}

    def block_seed_and_run() -> None:
        _install_planner(_plan_with(critical_steps))
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=user_id, goal="Policy-blocked task."
            )
            block_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(block_task["id"])

    def block_enforced() -> None:
        with factory() as db:
            task = TaskRepository(db).get(block_task["id"])
            assert task is not None
            assert task.status == TaskStatus.FAILED.value, (
                f"expected failed, got {task.status}"
            )
            rows = EventRepository(db).list_for_task(block_task["id"], limit=2000)
            blocked = [
                r for r in rows
                if r.event_type == EventType.POLICY_BLOCKED.value
            ]
            assert len(blocked) == 1, (
                f"expected 1 policy.blocked event, got {len(blocked)}"
            )
            steps = StepRepository(db).list_for_task(block_task["id"])
            critical = [s for s in steps if (s.risk_level or "").lower() == "critical"]
            assert critical and critical[0].status == StepStatus.FAILED.value, (
                f"critical step status={critical[0].status if critical else 'n/a'}"
            )

    for name, fn in [
        ("critical-risk task runs", block_seed_and_run),
        ("policy.blocked event halts the task", block_enforced),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # ------------------------------------------------------------------
    # 6. API: GET /v1/approvals returns pending for this user.
    # ------------------------------------------------------------------
    _section("6. Approvals API")

    api_task: dict[str, str] = {}

    def api_seed_pending() -> None:
        _install_planner(_plan_with(approval_steps))
        with factory() as db:
            task = TaskRepository(db).create(
                user_id=user_id, goal="API approvals surface test."
            )
            api_task["id"] = task.id
            db.commit()
        services.orchestrator.run_task(api_task["id"])

    def api_list_pending() -> None:
        # Monkey-patch get_current_user so the TestClient sees user_stage5.
        from fastapi.testclient import TestClient

        from brain_api.deps import CurrentUser, get_current_user
        from brain_api.main import app

        def _override():
            return CurrentUser(id=user_id, email="stage5@local")

        app.dependency_overrides[get_current_user] = _override
        try:
            client = TestClient(app)
            resp = client.get("/v1/approvals")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert isinstance(body, list) and body, (
                f"expected at least 1 approval, got {body!r}"
            )
            ours = [a for a in body if a["task_id"] == api_task["id"]]
            assert ours, f"our approval not in response: {body!r}"
            ap = ours[0]
            assert ap["status"] == ApprovalStatus.PENDING.value
            assert ap["risk_level"]
            assert ap["requested_action"]
        finally:
            app.dependency_overrides.clear()

    for name, fn in [
        ("seed a pending approval via orchestrator", api_seed_pending),
        ("GET /v1/approvals lists pending", api_list_pending),
    ]:
        if not run_check(name, fn):
            failures.append(name)

    # Clean up the pending approval to leave the DB tidy for a second run.
    try:
        with factory() as db:
            for tid in (api_task.get("id"),):
                if not tid:
                    continue
                for ap in ApprovalRepository(db).list_for_task(tid):
                    if ap.status == ApprovalStatus.PENDING.value:
                        services.approvals.reject(
                            db, ap.id, approver_id=user_id, reason="verify cleanup"
                        )
            db.commit()
    except Exception:
        pass

    _restore_planner()

    _section("Summary")
    if failures:
        print(f"{RED}FAILED{RESET} — {len(failures)} check(s) did not pass.")
        for n in failures:
            print(f"  - {n}")
        return 1

    print(f"{GREEN}All checks passed.{RESET}")
    print(
        f"{DIM}Task ids: happy={happy_task.get('id')}, "
        f"approve={approve_task.get('id')}, reject={reject_task.get('id')}, "
        f"budget={budget_task.get('id')}, block={block_task.get('id')}, "
        f"api={api_task.get('id')}{RESET}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
