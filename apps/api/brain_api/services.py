"""Process-wide service singletons used across the API.

These exist once per FastAPI app and are reused across requests — the LLM
service, prompt registry, tool router, orchestrator, and background runner
are all stateless w.r.t. request data, but expensive to rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from brain_api.config import Settings
from brain_db import session as db_session
from brain_db.repositories import ToolRepository
from brain_engine.approvals import ApprovalManager
from brain_engine.budget import BudgetController
from brain_engine.executors import (
    CompareItemsExecutor,
    LLMReasoningExecutor,
    SummarizeTextExecutor,
)
from brain_engine.orchestrator import Orchestrator, OrchestratorDeps
from brain_engine.policy import PolicyEngine
from brain_engine.runner import TaskRunner
from brain_engine.tool_router import ToolRouter
from brain_engine.tool_spec import ToolSpec
from brain_llm.client import LLMClient
from brain_llm.providers.mock import build_default_mock
from brain_llm.service import LLMService
from brain_prompts.registry import PromptRegistry, default_registry


@dataclass
class Services:
    settings: Settings
    session_factory: sessionmaker[OrmSession]
    llm: LLMService
    prompts: PromptRegistry
    tool_router: ToolRouter
    policy: PolicyEngine
    budget: BudgetController
    approvals: ApprovalManager
    orchestrator: Orchestrator
    runner: TaskRunner


def build_services(settings: Settings) -> Services:
    if db_session.SessionLocal is None:
        db_session.init_engine(settings.database_url)
    assert db_session.SessionLocal is not None
    factory = db_session.SessionLocal

    primary, fallbacks = _build_providers(settings)
    llm = LLMService(primary=primary, fallbacks=fallbacks)

    prompts = default_registry()
    tool_router = ToolRouter()
    tool_router.register(LLMReasoningExecutor(llm, prompts))
    tool_router.register(SummarizeTextExecutor(llm, prompts))
    tool_router.register(CompareItemsExecutor(llm, prompts))

    _sync_tool_registry(factory, tool_router.list_specs())

    policy = PolicyEngine()
    budget = BudgetController()
    approvals = ApprovalManager()

    orchestrator = Orchestrator(
        OrchestratorDeps(
            session_factory=factory,
            llm=llm,
            prompts=prompts,
            tool_router=tool_router,
            policy=policy,
            budget=budget,
            approvals=approvals,
        )
    )
    runner = TaskRunner(orchestrator)

    return Services(
        settings=settings,
        session_factory=factory,
        llm=llm,
        prompts=prompts,
        tool_router=tool_router,
        policy=policy,
        budget=budget,
        approvals=approvals,
        orchestrator=orchestrator,
        runner=runner,
    )


def _sync_tool_registry(
    factory: sessionmaker[OrmSession], specs: list[ToolSpec]
) -> None:
    """Upsert every registered :class:`ToolSpec` into the ``tools`` table.

    Keeps code as the source of truth: each deploy writes the current set of
    specs to the DB so steps can FK their ``selected_tool_id`` to a real row.
    """
    with factory() as db:
        repo = ToolRepository(db)
        for spec in specs:
            repo.upsert(
                id=spec.id,
                name=spec.name,
                description=spec.description,
                capability_type=spec.capability_type.value,
                backend_type=spec.backend_type.value,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                risk_level=spec.risk_level.value,
                timeout_seconds=spec.timeout_seconds,
                version=spec.version,
            )
        db.commit()


def _build_providers(settings: Settings) -> tuple[LLMClient, list[LLMClient]]:
    """Pick providers based on settings.

    ``LLM_PROVIDER`` ∈ {``mock``, ``anthropic``}; defaults to ``mock`` so the
    service boots without API keys. When ``anthropic`` is selected but the
    SDK/key is missing, we log and fall back to mock rather than crashing
    the app.
    """
    choice = getattr(settings, "llm_provider", "mock").lower()
    mock = build_default_mock()
    if choice == "anthropic":
        try:
            from brain_llm.providers.anthropic import AnthropicProvider

            primary: LLMClient = AnthropicProvider()
            # Keep mock as a safety net so the loop still completes offline.
            return primary, [mock]
        except Exception:  # noqa: BLE001 — boot-time fallback
            import logging

            logging.getLogger(__name__).warning(
                "anthropic provider unavailable; falling back to mock",
                exc_info=True,
            )
    return mock, []
