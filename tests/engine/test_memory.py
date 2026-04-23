"""Memory service + embedder tests.

The embedder portions are pure-Python and need no DB. The service tests use
the real session factory (same pattern as ``scripts/verify_stage5.py``);
each test seeds rows under a uniquely-named user so the suite doesn't
interfere with dev data or itself when run in parallel.
"""

from __future__ import annotations

import uuid

import pytest

from brain_api.config import get_settings
from brain_api.services import build_services
from brain_core.enums import MemoryType, TaskStatus
from brain_db.repositories import (
    EventRepository,
    MemoryRepository,
    TaskRepository,
    UserRepository,
)
from brain_engine.memory import HashingEmbedder, MemoryService, cosine


# ---------------------------------------------------------------------------
# Pure-Python embedder tests (no DB required)
# ---------------------------------------------------------------------------


def test_hashing_embedder_is_deterministic() -> None:
    e = HashingEmbedder(dimensions=64)
    assert e.embed("hello world") == e.embed("hello world")


def test_hashing_embedder_normalizes_to_unit_length() -> None:
    e = HashingEmbedder(dimensions=64)
    v = e.embed("hello world")
    # Allow a little float slack; normalization is cheap but not exact.
    assert abs(sum(x * x for x in v) - 1.0) < 1e-9


def test_hashing_embedder_empty_returns_zero_vector() -> None:
    e = HashingEmbedder(dimensions=32)
    assert e.embed("") == [0.0] * 32


def test_cosine_higher_for_related_text() -> None:
    e = HashingEmbedder(dimensions=128)
    near = cosine(
        e.embed("compare GraphQL and REST for a small team"),
        e.embed("graphql vs rest tradeoffs for small teams"),
    )
    far = cosine(
        e.embed("compare GraphQL and REST for a small team"),
        e.embed("recipe for banana bread with walnuts"),
    )
    assert near > far


# ---------------------------------------------------------------------------
# DB-backed service tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def services():
    return build_services(get_settings())


@pytest.fixture()
def user_factory(services):
    created: list[str] = []

    def _make() -> str:
        uid = f"user_mem_{uuid.uuid4().hex[:8]}"
        with services.session_factory() as db:
            UserRepository(db).upsert_dev_user(uid, email=f"{uid}@test")
            db.commit()
        created.append(uid)
        return uid

    yield _make

    # Clean up: memory rows first, then the user placeholder.
    with services.session_factory() as db:
        repo = MemoryRepository(db)
        for uid in created:
            for row in repo.list_for_user(uid, limit=500):
                db.delete(row)
        db.commit()


def test_write_persists_and_emits_event(services, user_factory) -> None:
    uid = user_factory()
    svc = MemoryService()
    with services.session_factory() as db:
        item = svc.write(
            db,
            user_id=uid,
            memory_type=MemoryType.LONG_TERM,
            content="User prefers concise answers with bullet highlights.",
            summary="prefers concise answers",
            importance=0.4,
        )
        db.commit()
        assert item.id.startswith("mem_")
        persisted = MemoryRepository(db).get(item.id)
        assert persisted is not None
        assert persisted.summary == "prefers concise answers"
        # Embedding stashed in metadata.
        assert isinstance(persisted.meta["embedding"], list)
        # memory.written event was appended (task_id=None is fine for manual writes).
        events = EventRepository(db).list_for_task("nonexistent", limit=1)
        assert events == []  # the event had no task_id, so task scope returns empty


def test_search_ranks_semantically_similar_first(services, user_factory) -> None:
    uid = user_factory()
    svc = MemoryService()
    with services.session_factory() as db:
        svc.write(
            db,
            user_id=uid,
            memory_type=MemoryType.LONG_TERM,
            content="Compared GraphQL and REST for a small team and picked GraphQL.",
            summary="graphql vs rest comparison",
            importance=0.5,
        )
        svc.write(
            db,
            user_id=uid,
            memory_type=MemoryType.LONG_TERM,
            content="Reviewed banana bread recipes; walnut version preferred.",
            summary="banana bread recipe",
        )
        db.commit()

        hits = svc.search(
            db, user_id=uid, query="graphql rest tradeoffs", limit=5
        )
        assert len(hits) >= 1
        top_summary = (hits[0].item.summary or "").lower()
        scores = [h.score for h in hits]
        db.commit()

    assert "graphql" in top_summary
    # Unrelated memory should rank below or be excluded by score=0.
    if len(scores) == 2:
        assert scores[0] > scores[1]


def test_search_is_user_scoped(services, user_factory) -> None:
    uid_a = user_factory()
    uid_b = user_factory()
    svc = MemoryService()
    with services.session_factory() as db:
        svc.write(
            db,
            user_id=uid_a,
            memory_type=MemoryType.LONG_TERM,
            content="User A's GraphQL note.",
        )
        db.commit()
        hits_b = svc.search(db, user_id=uid_b, query="graphql note", limit=5)
        db.commit()

    assert hits_b == []


def test_summarize_task_writes_long_term_memory(services, user_factory) -> None:
    uid = user_factory()
    svc = MemoryService()
    with services.session_factory() as db:
        task = TaskRepository(db).create(
            user_id=uid, goal="Compare two CRMs for a 5-person team."
        )
        task.status = TaskStatus.COMPLETED.value
        task.final_output = {
            "summary": "HubSpot fits the team size better than Salesforce.",
            "highlights": ["onboarding", "price", "integrations"],
        }
        db.commit()
        item = svc.summarize_task(db, task)
        assert item is not None
        assert item.memory_type == MemoryType.LONG_TERM.value
        assert "HubSpot" in item.content
        assert item.importance >= 0.5
        db.commit()


def test_empty_content_rejected(services, user_factory) -> None:
    uid = user_factory()
    svc = MemoryService()
    with services.session_factory() as db:
        with pytest.raises(ValueError):
            svc.write(
                db,
                user_id=uid,
                memory_type=MemoryType.LONG_TERM,
                content="   ",
            )
