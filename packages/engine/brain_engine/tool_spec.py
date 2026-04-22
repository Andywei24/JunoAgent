"""Tool specs + lightweight JSON-schema validation.

A :class:`ToolSpec` is the declared shape of a tool: its id, capability tag,
risk level, and the JSON schemas it accepts/returns. Specs are the source of
truth for the `tools` table — :func:`brain_api.services.build_services`
registers every executor's spec into the registry on boot.

The validator is a deliberately small subset of JSON Schema: enough to
catch "LLM-produced plan step has the wrong input shape" without pulling in
a full validation library. Supports ``type`` (object/array/string/number/
integer/boolean/null), ``required``, ``properties``, ``items``, ``enum``,
and ``additionalProperties: false``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brain_core.enums import RiskLevel, ToolBackendType, ToolCapabilityType


@dataclass(slots=True, frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    capability: str
    capability_type: ToolCapabilityType
    backend_type: ToolBackendType
    risk_level: RiskLevel = RiskLevel.LOW
    version: str = "1"
    timeout_seconds: int = 30
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


class ToolValidationError(ValueError):
    """Raised when an input or output payload fails schema validation."""

    def __init__(self, tool_id: str, direction: str, errors: list[str]) -> None:
        self.tool_id = tool_id
        self.direction = direction
        self.errors = errors
        super().__init__(
            f"{direction} validation failed for {tool_id}: {'; '.join(errors)}"
        )


_TYPE_TO_PY: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list, tuple),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def validate_payload(
    payload: Any, schema: dict[str, Any] | None, *, tool_id: str, direction: str
) -> None:
    """Validate ``payload`` against a small JSON-schema subset.

    Empty/None schema is treated as "accept anything" — that's the default for
    executors that don't care to constrain their I/O.
    """
    if not schema:
        return
    errors: list[str] = []
    _check(payload, schema, path="$", errors=errors)
    if errors:
        raise ToolValidationError(tool_id, direction, errors)


def _check(value: Any, schema: dict[str, Any], *, path: str, errors: list[str]) -> None:
    expected = schema.get("type")
    if expected is not None:
        py_types = _TYPE_TO_PY.get(expected)
        if py_types is None:
            errors.append(f"{path}: unsupported schema type {expected!r}")
            return
        # booleans are ints in Python; keep them distinct for JSON parity.
        if expected != "boolean" and isinstance(value, bool):
            errors.append(f"{path}: expected {expected}, got boolean")
            return
        if not isinstance(value, py_types):
            errors.append(
                f"{path}: expected {expected}, got {type(value).__name__}"
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")

    if expected == "object" and isinstance(value, dict):
        props: dict[str, Any] = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required field {name!r}")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(props)
            if extras:
                errors.append(f"{path}: unexpected fields {sorted(extras)}")
        for key, sub in props.items():
            if key in value:
                _check(value[key], sub, path=f"{path}.{key}", errors=errors)

    if expected == "array" and isinstance(value, (list, tuple)):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(value):
                _check(item, items_schema, path=f"{path}[{i}]", errors=errors)


__all__ = ["ToolSpec", "ToolValidationError", "validate_payload"]
