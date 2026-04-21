"""Structured logging via structlog.

Renders JSON in production-like environments and a readable format otherwise.
Every log line carries `app`, `env`, and (when available) `correlation_id` and
`trace_id` from the request-scoped context.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars


def configure_logging(*, level: str = "INFO", fmt: str = "json", app: str = "juno-brain",
                      env: str = "dev") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",
        force=True,
    )

    processors: list[Any] = [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_static(app=app, env=env),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _inject_static(**kv: Any):
    def processor(_, __, event_dict):  # type: ignore[no-untyped-def]
        for k, v in kv.items():
            event_dict.setdefault(k, v)
        return event_dict

    return processor


def bind_request_context(**kwargs: Any) -> None:
    """Attach correlation/trace IDs to the current request's log context."""
    bind_contextvars(**{k: v for k, v in kwargs.items() if v is not None})


def clear_request_context() -> None:
    clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
