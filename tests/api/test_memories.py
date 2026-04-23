"""Memory HTTP route tests.

Exercises the four endpoints end-to-end against a real app instance and DB.
Cleanup runs after the module so dev data isn't polluted.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from brain_api.config import get_settings
from brain_api.deps import CurrentUser, get_current_user
from brain_api.main import create_app
from brain_db.repositories import MemoryRepository
from brain_db.session import SessionLocal


@pytest.fixture()
def authed_client():
    app = create_app()
    user_id = f"user_memapi_{uuid.uuid4().hex[:8]}"

    def _override() -> CurrentUser:
        return CurrentUser(id=user_id, email=f"{user_id}@test")

    # Seed the user row so FKs resolve.
    with SessionLocal() as db:  # type: ignore[misc]
        from brain_db.repositories import UserRepository

        UserRepository(db).upsert_dev_user(user_id, email=f"{user_id}@test")
        db.commit()

    app.dependency_overrides[get_current_user] = _override
    with TestClient(app) as client:
        yield client, user_id

    # Teardown.
    with SessionLocal() as db:  # type: ignore[misc]
        repo = MemoryRepository(db)
        for row in repo.list_for_user(user_id, limit=500):
            db.delete(row)
        db.commit()


def test_create_and_list_memory(authed_client) -> None:
    client, user_id = authed_client
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
    item = r.json()
    assert item["id"].startswith("mem_")
    assert item["user_id"] == user_id
    # Embedding must not leak.
    assert "embedding" not in item["metadata"]

    r = client.get("/v1/memories")
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()]
    assert item["id"] in ids


def test_invalid_memory_type_is_rejected(authed_client) -> None:
    client, _ = authed_client
    r = client.post(
        "/v1/memories",
        json={"content": "anything", "memory_type": "bogus"},
    )
    assert r.status_code == 422


def test_search_returns_ranked_hits(authed_client) -> None:
    client, _ = authed_client
    for content, summary in [
        ("Compared GraphQL and REST for a 5-person team.", "graphql vs rest"),
        ("Reviewed banana bread recipes.", "banana bread"),
    ]:
        client.post(
            "/v1/memories",
            json={"content": content, "summary": summary, "memory_type": "long_term"},
        )

    r = client.get("/v1/memories/search", params={"q": "graphql rest tradeoffs"})
    assert r.status_code == 200
    hits = r.json()
    assert hits, "expected at least one hit"
    top = hits[0]
    assert "graphql" in (top["item"]["summary"] or "").lower()


def test_delete_memory(authed_client) -> None:
    client, _ = authed_client
    created = client.post(
        "/v1/memories",
        json={"content": "ephemeral note", "memory_type": "working"},
    ).json()
    mid = created["id"]

    r = client.delete(f"/v1/memories/{mid}")
    assert r.status_code == 204

    r = client.get("/v1/memories")
    assert mid not in [row["id"] for row in r.json()]


def test_other_users_memory_is_not_visible(authed_client) -> None:
    client, user_id = authed_client
    # Write a memory for a different user directly.
    other = f"user_other_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:  # type: ignore[misc]
        from brain_core.enums import MemoryType
        from brain_db.repositories import UserRepository

        UserRepository(db).upsert_dev_user(other)
        repo = MemoryRepository(db)
        row = repo.create(
            user_id=other,
            memory_type=MemoryType.LONG_TERM,
            content="secret note for another user",
        )
        db.commit()
        other_id = row.id

    # List only returns this user's own rows.
    r = client.get("/v1/memories")
    assert other_id not in [m["id"] for m in r.json()]

    # Delete of someone else's memory 404s.
    r = client.delete(f"/v1/memories/{other_id}")
    assert r.status_code == 404

    # Clean up the other user's row.
    with SessionLocal() as db:  # type: ignore[misc]
        MemoryRepository(db).delete(other_id)
        db.commit()
