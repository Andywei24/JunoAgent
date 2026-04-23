"""PolicyEngine unit tests.

The engine only reads three fields (``step.risk_level``,
``step.approval_required``, ``tool.risk_level``), so we stub both with
lightweight objects instead of touching the DB.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain_core.enums import RiskLevel, ToolBackendType, ToolCapabilityType
from brain_engine.policy import PolicyAction, PolicyEngine
from brain_engine.tool_spec import ToolSpec


def _spec(*, risk: RiskLevel = RiskLevel.LOW) -> ToolSpec:
    return ToolSpec(
        id="tool_fake",
        name="fake",
        description="fake tool for tests",
        capability="fake",
        capability_type=ToolCapabilityType.REASONING,
        backend_type=ToolBackendType.INTERNAL,
        risk_level=risk,
        input_schema={},
        output_schema={},
    )


def _step(*, risk: str = "low", approval_required: bool = False) -> SimpleNamespace:
    return SimpleNamespace(risk_level=risk, approval_required=approval_required)


def test_low_risk_is_allowed() -> None:
    decision = PolicyEngine().evaluate(step=_step(), tool_spec=_spec())
    assert decision.action == PolicyAction.ALLOW
    assert decision.effective_risk == "low"


def test_approval_required_flag_forces_approval_even_when_low_risk() -> None:
    decision = PolicyEngine().evaluate(
        step=_step(approval_required=True), tool_spec=_spec()
    )
    assert decision.action == PolicyAction.REQUIRE_APPROVAL
    assert "approval_required" in decision.reason


def test_medium_step_risk_triggers_approval() -> None:
    decision = PolicyEngine().evaluate(step=_step(risk="medium"), tool_spec=_spec())
    assert decision.action == PolicyAction.REQUIRE_APPROVAL
    assert decision.effective_risk == "medium"


def test_high_tool_risk_trumps_low_step_risk() -> None:
    # Effective risk = max(step, tool) — a high-risk tool should still gate
    # even when the step label claims low.
    decision = PolicyEngine().evaluate(
        step=_step(risk="low"), tool_spec=_spec(risk=RiskLevel.HIGH)
    )
    assert decision.action == PolicyAction.REQUIRE_APPROVAL
    assert decision.effective_risk == "high"


def test_critical_risk_is_blocked() -> None:
    decision = PolicyEngine().evaluate(step=_step(risk="critical"), tool_spec=_spec())
    assert decision.action == PolicyAction.BLOCK
    assert decision.effective_risk == "critical"


def test_critical_tool_risk_blocks_low_step() -> None:
    decision = PolicyEngine().evaluate(
        step=_step(risk="low"), tool_spec=_spec(risk=RiskLevel.CRITICAL)
    )
    assert decision.action == PolicyAction.BLOCK


def test_custom_approval_threshold_high_allows_medium() -> None:
    engine = PolicyEngine(approval_threshold=RiskLevel.HIGH)
    decision = engine.evaluate(step=_step(risk="medium"), tool_spec=_spec())
    assert decision.action == PolicyAction.ALLOW


@pytest.mark.parametrize(
    "risk,expected",
    [
        ("low", PolicyAction.ALLOW),
        ("medium", PolicyAction.REQUIRE_APPROVAL),
        ("high", PolicyAction.REQUIRE_APPROVAL),
        ("critical", PolicyAction.BLOCK),
    ],
)
def test_risk_level_table(risk: str, expected: PolicyAction) -> None:
    decision = PolicyEngine().evaluate(step=_step(risk=risk), tool_spec=_spec())
    assert decision.action == expected
