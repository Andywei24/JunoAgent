# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.10 package for the Juno Brain agent platform. The API app lives in `apps/api/brain_api`, with route handlers under `routes/` and service wiring in `services.py`. Shared packages are split by responsibility: `packages/core/brain_core` for domain types and state machines, `packages/db/brain_db` for SQLAlchemy models, sessions, repositories, and Alembic migrations, `packages/engine/brain_engine` for orchestration and planning, `packages/llm/brain_llm` for provider integrations, and `packages/prompts/brain_prompts` for prompt templates. Verification scripts live in `scripts/`.

## Build, Test, and Development Commands

- `python -m venv .venv && source .venv/bin/activate`: create and enter a local virtual environment.
- `pip install -e ".[dev]"`: install the package plus pytest, Ruff, and mypy.
- `docker compose up -d postgres`: start the local PostgreSQL 16 service.
- `alembic upgrade head`: apply database migrations from `packages/db/brain_db/migrations`.
- `uvicorn brain_api.main:app --reload`: run the FastAPI app locally after installing the package.
- `pytest`: run tests from `tests/` as configured in `pyproject.toml`.
- `python scripts/verify_stage1.py` and `python scripts/verify_stage2.py`: run end-to-end stage checks against the local database.

## Coding Style & Naming Conventions

Use Ruff with a 100-character line length and Python 3.10 target. Keep imports sorted by Ruff (`I` rules) and prefer modern typing syntax such as `str | None`. Modules, functions, variables, and repository methods use snake_case; classes use PascalCase. Keep domain enums and state transitions centralized in `brain_core`.

## Testing Guidelines

Add pytest tests under `tests/`, matching source areas where possible, for example `tests/engine/test_orchestrator.py` or `tests/db/test_repositories.py`. Use `pytest-asyncio` for async API or service behavior. For database behavior, prefer focused repository tests plus the existing stage verification scripts. Run `pytest` and the relevant `scripts/verify_stage*.py` before opening a PR.

## Commit & Pull Request Guidelines

Recent commits use short, lowercase, imperative summaries such as `stage 2 implementation`. Keep commits focused and mention the stage or subsystem when useful. Pull requests should include a concise description, linked issue or roadmap item when applicable, migration notes for DB changes, test or verification commands run, and screenshots or sample API output for user-visible API changes.

## Security & Configuration Tips

Runtime settings are read from environment variables and optional `.env` via `brain_api.config`. Do not commit real provider keys. Use `LLM_PROVIDER=mock` for deterministic local development; set `ANTHROPIC_API_KEY` only in local or deployment secrets when using the Anthropic provider.
