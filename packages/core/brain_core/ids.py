"""ID generation helpers.

Prefixed IDs make raw log lines and event payloads legible without a schema.
Random suffix is URL-safe base32 so they stay copy-pasteable.
"""

from __future__ import annotations

import secrets
from base64 import b32encode


def _suffix(n_bytes: int = 10) -> str:
    return b32encode(secrets.token_bytes(n_bytes)).decode("ascii").rstrip("=").lower()


def new_task_id() -> str:
    return f"task_{_suffix()}"


def new_step_id() -> str:
    return f"step_{_suffix()}"


def new_event_id() -> str:
    return f"evt_{_suffix()}"


def new_approval_id() -> str:
    return f"apr_{_suffix()}"


def new_memory_id() -> str:
    return f"mem_{_suffix()}"


def new_tool_id() -> str:
    return f"tool_{_suffix()}"


def new_agent_id() -> str:
    return f"agt_{_suffix()}"


def new_session_id() -> str:
    return f"ses_{_suffix()}"


def new_correlation_id() -> str:
    return f"cor_{_suffix(8)}"


def new_trace_id() -> str:
    return f"trc_{_suffix(8)}"
