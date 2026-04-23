"""Memory System — Stage 6.

Wraps :class:`brain_db.repositories.MemoryRepository` with the business
logic needed by the orchestrator:

  * emit ``memory.written`` / ``memory.retrieved`` events on every I/O;
  * generate and attach a cheap deterministic embedding so semantic search
    works out of the box (no pgvector install required);
  * summarize a completed task into a long-lived memory item so later tasks
    can reuse the outcome.

The embedder is intentionally simple — a hashed bag-of-words vector — so
tests are reproducible and the service boots offline. Swapping in a real
embedding model later is a drop-in: implement the
:class:`TextEmbedder` protocol and hand it to the service.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from sqlalchemy.orm import Session as OrmSession

from brain_core.enums import ActorType, EventType, MemoryType
from brain_db import models
from brain_db.repositories import EventRepository, MemoryRepository


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


class TextEmbedder(Protocol):
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic hashing-trick embedder.

    Each token contributes ±1 to a fixed number of buckets. The vector is
    then L2-normalized. Not fancy, but sufficient for cosine ranking of
    task summaries and user notes in local/dev deployments.
    """

    _TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for token in self._TOKEN_RE.findall(text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class MemoryHit:
    """A ranked search hit — the ORM row plus the score that ranked it."""

    item: models.MemoryItem
    score: float


class MemoryService:
    """High-level API over :class:`MemoryRepository`."""

    def __init__(self, embedder: TextEmbedder | None = None) -> None:
        self._embedder = embedder or HashingEmbedder()

    # -- writes -----------------------------------------------------------

    def write(
        self,
        db: OrmSession,
        *,
        user_id: str,
        memory_type: MemoryType,
        content: str,
        task_id: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.0,
    ) -> models.MemoryItem:
        if not content.strip():
            raise ValueError("memory content must not be empty")
        repo = MemoryRepository(db)
        embedding = self._embedder.embed(content)
        item = repo.create(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            task_id=task_id,
            summary=summary,
            metadata=metadata,
            embedding=embedding,
            importance=importance,
        )
        EventRepository(db).append(
            event_type=EventType.MEMORY_WRITTEN,
            task_id=task_id,
            payload={
                "memory_id": item.id,
                "memory_type": memory_type.value,
                "summary": summary or _first_line(content),
                "importance": importance,
            },
            actor_type=ActorType.SYSTEM,
        )
        return item

    def delete(self, db: OrmSession, memory_id: str) -> bool:
        return MemoryRepository(db).delete(memory_id)

    # -- reads ------------------------------------------------------------

    def list_for_user(
        self,
        db: OrmSession,
        user_id: str,
        *,
        memory_type: MemoryType | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[models.MemoryItem]:
        return MemoryRepository(db).list_for_user(
            user_id,
            memory_type=memory_type,
            task_id=task_id,
            limit=limit,
        )

    def search(
        self,
        db: OrmSession,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        memory_type: MemoryType | None = None,
        task_id: str | None = None,
        min_score: float = 0.0,
        event_task_id: str | None = None,
        event_step_id: str | None = None,
    ) -> list[MemoryHit]:
        """Rank the user's memories against ``query``.

        Pure-Python cosine over the stored hashing embeddings, with a
        keyword-overlap fallback when a candidate has no embedding. Emits
        a single ``memory.retrieved`` event summarizing what was picked.

        ``event_task_id`` / ``event_step_id`` tag the ``memory.retrieved``
        event. Separate from ``task_id`` (which scopes *which* memories to
        search) so callers can search cross-task memories while still
        attributing the retrieval event to the current task.
        """
        query = query.strip()
        if not query:
            return []
        repo = MemoryRepository(db)
        candidates = repo.candidates_for_search(
            user_id, memory_type=memory_type, limit=200
        )
        query_vec = self._embedder.embed(query)
        query_tokens = set(HashingEmbedder._TOKEN_RE.findall(query.lower()))

        hits: list[MemoryHit] = []
        for item in candidates:
            if task_id and item.task_id != task_id:
                continue
            score = self._score(item, query_vec, query_tokens)
            if score <= min_score:
                continue
            hits.append(MemoryHit(item=item, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:limit]

        EventRepository(db).append(
            event_type=EventType.MEMORY_RETRIEVED,
            task_id=event_task_id or task_id,
            step_id=event_step_id,
            payload={
                "query": query[:400],
                "hit_ids": [h.item.id for h in hits],
                "hit_count": len(hits),
                "top_score": hits[0].score if hits else 0.0,
            },
            actor_type=ActorType.SYSTEM,
        )
        return hits

    # -- summaries --------------------------------------------------------

    def summarize_task(
        self, db: OrmSession, task: models.Task
    ) -> models.MemoryItem | None:
        """Write a long-term memory summarizing ``task``.

        Returns ``None`` if the task doesn't produce something worth
        remembering (empty final_output on a failed run, etc.).
        """
        content = _compose_task_summary(task)
        if not content:
            return None
        summary = (task.goal or "")[:160]
        return self.write(
            db,
            user_id=task.user_id,
            memory_type=MemoryType.LONG_TERM,
            content=content,
            task_id=task.id,
            summary=summary,
            metadata={
                "source": "task_summary",
                "risk_level": task.risk_level,
                "status": task.status,
            },
            importance=_summary_importance(task),
        )

    # -- internals --------------------------------------------------------

    def _score(
        self,
        item: models.MemoryItem,
        query_vec: list[float],
        query_tokens: set[str],
    ) -> float:
        meta = item.meta or {}
        embedding = meta.get(MemoryRepository.EMBEDDING_KEY)
        if isinstance(embedding, list) and embedding:
            sim = cosine(query_vec, embedding)
        else:
            sim = _keyword_overlap(item, query_tokens)
        # Importance nudges ties but never dominates.
        return sim + 0.05 * float(item.importance or 0.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return text[:200]


def _keyword_overlap(item: models.MemoryItem, query_tokens: Iterable[str]) -> float:
    q = set(query_tokens)
    if not q:
        return 0.0
    haystack = " ".join(
        filter(None, (item.summary, item.content))
    ).lower()
    item_tokens = set(HashingEmbedder._TOKEN_RE.findall(haystack))
    if not item_tokens:
        return 0.0
    intersection = q & item_tokens
    return len(intersection) / math.sqrt(len(q) * len(item_tokens))


def _compose_task_summary(task: models.Task) -> str:
    lines = [f"Goal: {task.goal}"]
    parsed = task.parsed_goal or {}
    intent = parsed.get("intent")
    if intent:
        lines.append(f"Intent: {intent}")
    final = task.final_output or {}
    if isinstance(final, dict):
        summary = final.get("summary") or final.get("final_answer")
        if summary:
            lines.append(f"Outcome: {summary}")
        highlights = final.get("highlights") or []
        if isinstance(highlights, list) and highlights:
            lines.append("Highlights: " + "; ".join(str(h) for h in highlights[:3]))
    lines.append(f"Status: {task.status}")
    text = "\n".join(lines).strip()
    return text if len(text) > len("Goal: ") else ""


def _summary_importance(task: models.Task) -> float:
    # Completed tasks earn more weight than failures.
    if task.status == "completed":
        return 0.5
    if task.status == "failed":
        return 0.2
    return 0.1


__all__ = [
    "HashingEmbedder",
    "MemoryHit",
    "MemoryService",
    "TextEmbedder",
    "cosine",
]
