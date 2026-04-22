"""Tool registry routes.

Read-only in Stage 4: the registry is populated from in-process :class:`ToolSpec`
objects at boot, and steps/audit logs reference those rows by id. Later
stages will add mutations for external tool onboarding.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from brain_api.deps import DbSession
from brain_db.repositories import ToolRepository


router = APIRouter(prefix="/v1/tools", tags=["tools"])


class ToolItem(BaseModel):
    id: str
    name: str
    description: str
    capability_type: str
    backend_type: str
    risk_level: str
    version: str
    timeout_seconds: int
    required_permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool


@router.get("", response_model=list[ToolItem])
def list_tools(db: DbSession) -> list[ToolItem]:
    rows = ToolRepository(db).list_enabled()
    return [_item(row) for row in rows]


def _item(tool) -> ToolItem:
    return ToolItem(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        capability_type=tool.capability_type,
        backend_type=tool.backend_type,
        risk_level=tool.risk_level,
        version=tool.version,
        timeout_seconds=tool.timeout_seconds,
        required_permissions=tool.required_permissions or [],
        input_schema=tool.input_schema or {},
        output_schema=tool.output_schema or {},
        enabled=tool.enabled,
    )
