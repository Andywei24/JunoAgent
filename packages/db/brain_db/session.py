"""SQLAlchemy engine + session factory.

The engine is built lazily from `DATABASE_URL` so unit tests and Alembic can
override it without importing the FastAPI app. `init_engine` lets the API
process bind an engine explicitly at startup; `get_session` yields a scoped
session for FastAPI's dependency injection.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Create (or rebuild) the process-wide engine and session factory."""
    global engine, SessionLocal

    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env or pass database_url="
        )

    engine = create_engine(url, echo=echo, pool_pre_ping=True, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session and commits/rolls back on exit."""
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None  # for type checkers

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
