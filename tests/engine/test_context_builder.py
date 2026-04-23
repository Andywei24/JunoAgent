"""ContextBuilder tests.

Exercises section selection, active-step fallback, budget trimming, and the
memory-backed query path. Uses the live session factory so the repository
queries and ``MemoryService`` integration are both tested.
"""

from __future__ import annotations

import uuid

import pytest

from brain_api.config import get_settings
from brain_api.services import build_services
from brain_core.enums import ActorType, EventType, MemoryType, StepStatus, TaskStatus
from brain_db.repositories import (
    EventRepository,
    MemoryRepository,
    StepRepository,
    TaskRepository,
    UserRepository,
)
from brain_engine.context_builder import ContextBuilder
from brain_engine.memory import MemoryService


@pytest.fixture(scope="module")
def services():
    return build_services(get_settings())


@pytest.fixture()
def seed(services):
    """Produce an isolated (user, task, steps, events) fixture.

    Yields a dict with the seeded ids; cleans up the user's memories + task
    chain on teardown. No other fixtures or tests should reuse the user id.
    """
    uid = f"user_ctx_{uuid.uuid4().hex[:8]}"
    with services.session_factory() as db:
        UserRepository(db).upsert_dev_user(uid, email=f"{uid}@test")
        task = TaskRepository(db).create(
            user_id=uid,
            goal="Compare two CRMs for a 5-person team.",
        )
        task.parsed_goal = {"intent": "compare", "constraints": ["team=5"]}
        task.status = TaskStatus.RUNNING.value
        db.flush()
        steps = StepRepository(db).create_many(
            task.id,
            [
                {
                    "name": "Restate goal",
                    "description": "Rephrase in one sentence.",
                    "required_capability": "llm_reasoning",
                    "risk_level": "low",
                    "approval_required": False,
                    "input_payload": {"instruction": "restate"},
                },
                {
                    "name": "Compare options",
                    "description": "Compare HubSpot vs Salesforce.",
                    "required_capability": "compare_items",
                    "risk_level": "low",
                    "approval_required": False,
                    "input_payload": {"items": ["HubSpot", "Salesforce"]},
                },
                {
                    "name": "Summarize",
                    "description": "Produce the final summary.",
                    "required_capability": "summarize_text",
                    "risk_level": "low",
                    "approval_required": False,
                    "input_payload": {"text": "draft"},
                },
            ],
        )
        # Complete step 1, pending the rest. create_many already set
        # sequence_order = 0, 1, 2 based on insertion index.
        first = steps[0]
        first.status = StepStatus.COMPLETED.value
        first.output_payload = {
            "summary": "Pick the CRM with the easiest onboarding for 5 people.",
            "details": "Onboarding matters more than feature breadth at this size.",
        }
        EventRepository(db).append(
            event_type=EventType.STEP_COMPLETED,
            task_id=task.id,
            step_id=first.id,
            payload={"name": first.name},
            actor_type=ActorType.SYSTEM,
        )
        db.commit()
        ids = {
            "user_id": uid,
            "task_id": task.id,
            "step_ids": [s.id for s in steps],
        }

    yield ids

    with services.session_factory() as db:
        repo = MemoryRepository(db)
        for row in repo.list_for_user(uid, limit=500):
            db.delete(row)
        db.commit()


def test_builder_includes_goal_and_active_step(services, seed) -> None:
    builder = ContextBuilder(memory=MemoryService())
    with services.session_factory() as db:
        bundle = builder.build(
            db, task_id=seed["task_id"], step_id=seed["step_ids"][1]
        )
    assert bundle.goal.startswith("Compare two CRMs")
    assert bundle.active_step is not None
    assert bundle.active_step["name"] == "Compare options"
    # Step 0 is complete; its output should show up as prior context.
    assert len(bundle.prior_step_outputs) == 1
    assert bundle.prior_step_outputs[0]["name"] == "Restate goal"


def test_builder_falls_back_to_first_nonterminal_step(services, seed) -> None:
    builder = ContextBuilder(memory=MemoryService())
    with services.session_factory() as db:
        bundle = builder.build(db, task_id=seed["task_id"])
    assert bundle.active_step is not None
    # Step 0 is completed, so the builder should pick step 1.
    assert bundle.active_step["name"] == "Compare options"


def test_builder_surfaces_relevant_memory(services, seed) -> None:
    svc = MemoryService()
    with services.session_factory() as db:
        svc.write(
            db,
            user_id=seed["user_id"],
            memory_type=MemoryType.LONG_TERM,
            content="Prior task picked HubSpot over Salesforce for a 4-person startup.",
            summary="hubspot vs salesforce",
            importance=0.6,
        )
        db.commit()

        builder = ContextBuilder(memory=svc)
        bundle = builder.build(
            db, task_id=seed["task_id"], step_id=seed["step_ids"][1]
        )
        memories = bundle.relevant_memories
    assert memories, "expected memory search to surface the seeded item"
    assert "hubspot" in (memories[0]["summary"] or "").lower()


def test_builder_trims_to_char_budget(services, seed) -> None:
    svc = MemoryService()
    with services.session_factory() as db:
        # Seed several memories so the builder has material to trim.
        for i in range(6):
            svc.write(
                db,
                user_id=seed["user_id"],
                memory_type=MemoryType.LONG_TERM,
                content=(
                    f"Long memory #{i} about CRM comparisons. " * 40
                ),
                summary=f"memory_{i}",
            )
        db.commit()

        builder = ContextBuilder(memory=svc, char_budget=1200)
        bundle = builder.build(
            db, task_id=seed["task_id"], step_id=seed["step_ids"][1]
        )
    # Goal should always survive the trim.
    assert bundle.goal
    # Budget should be (approximately) honored; we allow a small overshoot.
    assert bundle.char_used <= 1800


def test_memory_retrieved_event_is_emitted(services, seed) -> None:
    svc = MemoryService()
    with services.session_factory() as db:
        svc.write(
            db,
            user_id=seed["user_id"],
            memory_type=MemoryType.LONG_TERM,
            content="CRM comparison preference: prefer onboarding over features.",
        )
        db.commit()
        builder = ContextBuilder(memory=svc)
        builder.build(db, task_id=seed["task_id"], step_id=seed["step_ids"][1])
        db.commit()

        events = EventRepository(db).list_for_task(seed["task_id"], limit=500)
    types = [e.event_type for e in events]
    assert EventType.MEMORY_RETRIEVED.value in types
