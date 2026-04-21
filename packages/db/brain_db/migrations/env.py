"""Alembic migration environment.

Imports `brain_db.models` so `target_metadata` sees every table, and resolves
the database URL from `DATABASE_URL` (or `-x dburl=...`).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from brain_db.session import Base
from brain_db import models  # noqa: F401  -- ensure tables are registered

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    xargs = context.get_x_argument(as_dictionary=True)
    url = xargs.get("dburl") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No database URL. Set DATABASE_URL or pass -x dburl=... to alembic."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = _db_url()

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
