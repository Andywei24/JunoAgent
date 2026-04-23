# JunoAgent

JunoAgent is a Python-first brain agent platform. It is built as a durable backend workflow system rather than a chat-only agent loop: a user submits a goal, the backend parses it, generates a plan, executes steps through registered tools, records append-only events, and stores the final result for inspection and replay.

The current repo includes:

- A FastAPI backend
- A PostgreSQL-backed task, step, event, tool, and approval model
- An in-process orchestrator and background runner
- A minimal browser console served from the API
- Mock-LLM-driven verification scripts so the core flow can run offline

## What The System Does

At a high level, the runtime looks like this:

```text
Create task
  -> parse goal
  -> generate plan
  -> create steps
  -> select tools
  -> execute steps
  -> emit events
  -> store final output
```

The architecture is split across a few clear package boundaries:

```text
apps/api          FastAPI app, routes, middleware, service wiring
apps/console      Static operator console served at /console
packages/core     Domain types, enums, IDs, state machines
packages/db       SQLAlchemy models, migrations, repositories
packages/llm      LLM client/service abstraction and providers
packages/prompts  Prompt registry and prompt templates
packages/engine   Orchestrator, runner, tools, policy, budget, approvals
scripts           Stage verification scripts
tests             Focused API tests
```

## Current Feature Set

Implemented in the current workspace:

- Stage 1 foundation:
  - FastAPI app bootstrapping
  - PostgreSQL schema and Alembic migrations
  - append-only event store
  - task and step state machines
  - structured logging and request context middleware
  - `/health` and `/ready`
- Stage 2 core brain loop:
  - `POST /v1/tasks`
  - task detail, steps, events, result, cancel
  - SSE event streaming
  - goal parser, planner, orchestrator, step execution
  - mock LLM provider for deterministic local runs
- Stage 3 console:
  - static operator UI at `/console/`
  - task creation, task list, task detail, plan view, live events
- Stage 4 tools:
  - tool registry synced from in-process `ToolSpec`s into the database
  - schema-validated tool execution
  - built-in tools: `llm_reasoning`, `summarize_text`, `compare_items`
  - `GET /v1/tools`
- Stage 5 controls:
  - policy engine
  - budget controller
  - approval manager
  - `GET /v1/approvals`
  - `POST /v1/approvals/{id}/approve`
  - `POST /v1/approvals/{id}/reject`

## Requirements

- Python 3.10+
- Docker Desktop or another local Docker runtime
- PostgreSQL is provided through `docker compose`

## Local Setup

1. Create and activate a virtual environment.

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

2. Install the project in editable mode.

```bash
pip install -e ".[dev]"
```

If you want the optional Anthropic provider available:

```bash
pip install -e ".[dev,anthropic]"
```

3. Copy the environment template.

```bash
cp .env.example .env
```

4. Start PostgreSQL.

```bash
docker compose up -d postgres
```

5. Apply migrations.

```bash
python -m alembic upgrade head
```

## Run The API

```bash
python -m uvicorn brain_api.main:app --reload --host 127.0.0.1 --port 8000
```

Useful URLs after boot:

- API root redirect: `http://127.0.0.1:8000/`
- Console: `http://127.0.0.1:8000/console/`
- Health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/ready`

By default the app uses the mock provider:

```text
LLM_PROVIDER=mock
```

That means the task flow can run locally without external model credentials.

## API Walkthrough

Create a task:

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks \
  -H "content-type: application/json" \
  -d '{"goal":"Compare REST and GraphQL for a small engineering team.","priority":0}'
```

List tasks:

```bash
curl http://127.0.0.1:8000/v1/tasks
```

Inspect one task:

```bash
curl http://127.0.0.1:8000/v1/tasks/<task_id>
curl http://127.0.0.1:8000/v1/tasks/<task_id>/steps
curl http://127.0.0.1:8000/v1/tasks/<task_id>/events
curl http://127.0.0.1:8000/v1/tasks/<task_id>/result
```

Watch live events:

```bash
curl -N http://127.0.0.1:8000/v1/tasks/<task_id>/events/stream
```

Inspect tool registry:

```bash
curl http://127.0.0.1:8000/v1/tools
```

Inspect pending approvals:

```bash
curl http://127.0.0.1:8000/v1/approvals
```

Approve or reject:

```bash
curl -X POST http://127.0.0.1:8000/v1/approvals/<approval_id>/approve
curl -X POST http://127.0.0.1:8000/v1/approvals/<approval_id>/reject \
  -H "content-type: application/json" \
  -d '{"reason":"Rejecting this action for now."}'
```

## Verification

The repo includes incremental verification scripts for the staged implementation.

Stage 1:

```bash
python scripts/verify_stage1.py
```

Stage 2:

```bash
python scripts/verify_stage2.py
```

Stage 4:

```bash
python scripts/verify_stage4.py
```

Stage 5:

```bash
python scripts/verify_stage5.py
```

These scripts expect:

- `DATABASE_URL` to point at the local Postgres instance
- migrations already applied
- `LLM_PROVIDER=mock` or the default `.env` settings

They verify the system end to end against the real database and in-process engine.

## Tests And Checks

Run unit/API tests:

```bash
pytest
```

Run lint:

```bash
ruff check apps packages scripts tests
```

Compile-check the Python packages:

```bash
python -m compileall apps packages scripts
```

## Configuration

The main settings live in [`.env.example`](./.env.example):

- `APP_ENV`
- `APP_NAME`
- `LOG_LEVEL`
- `LOG_FORMAT`
- `API_HOST`
- `API_PORT`
- `DATABASE_URL`
- `DEV_USER_ID`
- `DEV_USER_EMAIL`
- `LLM_PROVIDER`
- `ANTHROPIC_API_KEY`

Until real authentication is added, every request is attributed to the configured dev user.

## Notes

- The console is intentionally minimal. It is an operator view over the API, not a polished product UI yet.
- The event store is central to the design. Most important state transitions and tool actions are emitted as events.
- The backend architecture is deliberately workflow-first, so future browser, desktop, or worker automation can plug into the platform without becoming the platform.

## Related Docs

- [Brain agent platform.md](<./Brain agent platform.md>)
- [Brain agent implementation roadmap.md](<./Brain agent implementation roadmap.md>)
- [JunoAgent planned architecture and design patterns.md](<./JunoAgent planned architecture and design patterns.md>)
