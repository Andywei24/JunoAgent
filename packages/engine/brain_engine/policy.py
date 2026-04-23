"""Policy engine.

Decides, for each step, whether it may run, needs human approval, or is
blocked outright. Stage 5 keeps the rules compact and risk-driven; future
stages can layer per-capability deny-lists, per-user scopes, or
data-sensitivity checks on top without changing the orchestrator call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from brain_core.enums import RiskLevel
from brain_db import models

from brain_engine.tool_spec import ToolSpec


_RISK_ORDER: dict[str, int] = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
    RiskLevel.CRITICAL.value: 3,
}


class PolicyAction(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


@dataclass(slots=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    effective_risk: str


class PolicyEngine:
    """Risk-threshold-based gatekeeper.

    Rules (first match wins):
      1. Effective risk ``critical`` → BLOCK.
      2. ``step.approval_required`` is True → REQUIRE_APPROVAL.
      3. Effective risk ≥ ``approval_threshold`` (default ``medium``) →
         REQUIRE_APPROVAL.
      4. Otherwise → ALLOW.

    "Effective risk" is the higher of ``step.risk_level`` and
    ``tool.risk_level`` so a risky tool can't be smuggled in under a
    low-risk step label.
    """

    def __init__(
        self,
        *,
        approval_threshold: RiskLevel = RiskLevel.MEDIUM,
        block_threshold: RiskLevel = RiskLevel.CRITICAL,
    ) -> None:
        self._approval = _RISK_ORDER[approval_threshold.value]
        self._block = _RISK_ORDER[block_threshold.value]

    def evaluate(
        self, *, step: models.TaskStep, tool_spec: ToolSpec
    ) -> PolicyDecision:
        step_risk = _RISK_ORDER.get((step.risk_level or "low").lower(), 0)
        tool_risk = _RISK_ORDER.get(tool_spec.risk_level.value, 0)
        effective = max(step_risk, tool_risk)
        effective_name = _name_for(effective)

        if effective >= self._block:
            return PolicyDecision(
                action=PolicyAction.BLOCK,
                reason=(
                    f"effective risk {effective_name!r} meets block threshold"
                ),
                effective_risk=effective_name,
            )
        if step.approval_required:
            return PolicyDecision(
                action=PolicyAction.REQUIRE_APPROVAL,
                reason="step flagged approval_required=True by planner",
                effective_risk=effective_name,
            )
        if effective >= self._approval:
            return PolicyDecision(
                action=PolicyAction.REQUIRE_APPROVAL,
                reason=(
                    f"effective risk {effective_name!r} meets approval threshold"
                ),
                effective_risk=effective_name,
            )
        return PolicyDecision(
            action=PolicyAction.ALLOW,
            reason="low-risk step, no approval required",
            effective_risk=effective_name,
        )


def _name_for(level: int) -> str:
    for name, value in _RISK_ORDER.items():
        if value == level:
            return name
    return RiskLevel.LOW.value
