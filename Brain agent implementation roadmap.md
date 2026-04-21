# Brain Agent Implementation Roadmap

This roadmap translates the architecture in `Brain agent platform.md` into an implementation sequence.

The project should start with a narrow but real brain loop that proves the platform can accept a goal, create a plan, execute steps, emit events, and produce an inspectable result. Desktop, browser, and multi-agent complexity should come later.

## Recommended Start

Use a Python-first backend with a frontend workspace:

```text
apps/
  api/          Python backend, preferably FastAPI
  console/      React/Next.js web console

packages/
  core/         Python domain types, task state machine, events
  db/           Python database schema, migrations, repositories
  llm/          Python LLM service abstraction
  prompts/      prompt templates and prompt versions
  sdk/          future SDKs, starting with Python and later TypeScript if needed
```

Backend requirement:

- The backend must use Python as the primary programming language.
- FastAPI is the recommended API framework unless a later implementation decision chooses another Python framework.
- Backend domain logic, orchestration, workflow execution, LLM access, policy, budget, memory, and tool routing should live in Python packages.
- TypeScript should be limited to the web console and optional future SDKs.

Start with:

1. PostgreSQL schema.
2. Append-only event store.
3. Task creation API.
4. Basic orchestrator.
5. Goal parser and planner using the LLM service.
6. Simple workflow execution.
7. Live event stream.
8. Minimal web console.

The first usable milestone should be:

```text
User submits a goal -> system parses it -> generates a structured plan -> executes simple LLM-backed steps -> streams events -> stores final output -> exposes replayable task history.
```

## Stage 1: Foundation

Build the base platform primitives.

Deliverables:

- Repo scaffold.
- Backend API service.
- PostgreSQL migrations.
- Core domain models:
  - `Task`
  - `TaskStep`
  - `Event`
  - `Approval`
  - `ToolDefinition`
  - `MemoryItem`
- Event store.
- Task state machine.
- Basic auth placeholder or local dev user.
- Health check and structured logging.

Do this before any agent logic. The platform needs durable state first.

## Stage 2: Core Brain MVP

Build the first end-to-end brain loop.

Deliverables:

- `POST /v1/tasks`
- `GET /v1/tasks/:id`
- `GET /v1/tasks/:id/events`
- `GET /v1/tasks/:id/events/stream`
- Goal Parser.
- Planner.
- LLM Service abstraction.
- Prompt Runtime.
- Workflow Engine.
- Simple step executor.
- Final result storage.

At this stage, tools can be minimal. For example, one internal `llm_reasoning` tool is enough to execute simple planning and synthesis steps.

Success criteria:

- Create a task from a user goal.
- Persist task and events.
- Generate a structured plan.
- Execute steps in order.
- Store final result.
- Debug the full run from events.

## Stage 3: Basic Web Console

Build the operator UI early because agent systems need visibility.

Screens:

- Task creation.
- Task list.
- Task detail.
- Plan and step status.
- Live event stream.
- Final output view.

Keep it simple, but real. The console should make it obvious what the brain is doing.

## Stage 4: Tool Registry and Tool Router

Move from LLM-only execution to declared capabilities.

Deliverables:

- Tool registry table.
- Tool schemas.
- Tool Router.
- Input/output validation.
- Tool execution events:
  - `tool.selected`
  - `tool.started`
  - `tool.completed`
  - `tool.failed`
- Built-in tools:
  - `llm_reasoning`
  - `summarize_text`
  - `compare_items`
  - `memory_search`, later

This is where the system starts becoming a platform rather than a prompt wrapper.

## Stage 5: Policy, Budget, and Approvals

Add control boundaries before adding powerful tools.

Deliverables:

- Budget Controller.
- Policy Engine.
- Approval Manager.
- Approval APIs:
  - `GET /v1/approvals`
  - `POST /v1/approvals/:id/approve`
  - `POST /v1/approvals/:id/reject`
- Step pause and resume behavior.
- Budget events and approval events.

Success criteria:

- Expensive or risky steps can pause.
- User can approve or reject.
- Budget limits can stop a task.
- All decisions are auditable.

## Stage 6: Memory and Context Builder

Only add memory after the execution loop is stable.

Deliverables:

- Memory storage.
- Manual memory API.
- Task summary memory.
- Semantic search, probably with PostgreSQL and pgvector first.
- Context Builder that selects:
  - task goal
  - active step
  - relevant memories
  - recent events
  - prior outputs

Success criteria:

- New tasks can reuse useful past context.
- Memory does not flood prompts.
- Memory reads and writes are logged.

## Stage 7: Replay and Debugging

Turn event history into an operator tool.

Deliverables:

- Replay API.
- Timeline reconstruction.
- Prompt and version visibility.
- Tool call visibility.
- Failure and retry inspection.

This matters because agent failures are usually not just exceptions. They are often bad plans, weak context, wrong tools, or policy gaps.

## Stage 8: Multi-Agent Hub

Add this only after single-agent workflows are solid.

Deliverables:

- Agent records.
- Agent roles.
- Scoped subtask assignment.
- Parallel step execution.
- Result merging.
- Critique and review agent pattern.

Use multi-agent execution selectively:

- Parallel research.
- Independent verification.
- Synthesis after multiple branches.
- Critique of final answer.

Do not make every task multi-agent by default.

## Stage 9: Worker Gateway

Now define external execution.

Deliverables:

- Worker registration.
- Heartbeats.
- Capability discovery.
- Assignment protocol.
- Worker events.
- Worker result validation.
- Worker auth.

Start with a simple CLI or sandbox worker before desktop automation.

## Stage 10: Desktop and Browser Workers

Desktop should be last, not first.

Deliverables:

- Screenshot capture.
- UI state observation.
- Controlled click and type actions.
- Approval gates.
- Worker-side error reporting.
- Evidence capture.
- Replayable external actions.

The brain should not know desktop details. It should only assign bounded work to a worker capability.

## First Sprint

Sprint 1 should focus on proving the backend loop and event model.

Tasks:

1. Scaffold Python backend workspace with a web console workspace.
2. Add API app.
3. Add PostgreSQL migrations.
4. Define core domain types.
5. Implement task creation.
6. Implement append-only events.
7. Implement basic task state machine.
8. Add `GET /tasks/:id/events`.
9. Add a tiny orchestrator that emits:
   - `task.created`
   - `goal.parsed`
   - `plan.generated`
   - `step.started`
   - `step.completed`
   - `task.completed`

Do not build the web console first unless it is needed for a demo. First prove the backend loop and event model.
