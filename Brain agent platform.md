# Brain Agent Platform

## Technical Architecture and Software Development Plan

| Field | Value |
| --- | --- |
| Document status | Draft |
| Audience | Founder, engineering, product, and future contributors |
| Primary objective | Define the first production-ready architecture for a personal agent "brain" platform that can plan, coordinate, execute, observe, and improve autonomous or semi-autonomous tasks. |

---

## 1. Executive Summary

The Brain Agent Platform is the central intelligence and coordination layer for a personal agent system. It accepts user goals, converts them into structured plans, coordinates one or more agents, selects tools, manages memory and context, enforces policy and budget limits, tracks execution state, records events, supports replay, and exposes the platform through APIs and a web console.

The first phase should focus on building the brain itself, without depending on a desktop agent. Desktop, browser, CLI, or other external workers can be added later through a Worker Gateway once the core workflow, event, memory, and policy foundations are stable.

The key architectural principle is separation of concerns:

- The **Orchestrator** controls task execution.
- The **Planner** creates structured task plans.
- The **Workflow Engine** manages state transitions.
- The **LLM Service** provides managed model access.
- The **Memory System** provides durable and semantic context.
- The **Tool Router** selects and invokes capabilities.
- The **Policy, Budget, and Approval services** enforce control boundaries.
- The **Event, Audit, Replay, and Observability layers** make behavior inspectable.
- The **Worker Gateway** provides a future interface to external executors.

---

## 2. Goals and Non-Goals

### 2.1 Goals

The platform should:

- Accept user goals through an API, SDK, or web console.
- Normalize raw goals into structured task specifications.
- Generate executable plans with clear steps, dependencies, and expected outputs.
- Execute workflows through deterministic state transitions.
- Coordinate sub-agents when parallel or role-based work is useful.
- Route actions to internal tools, model calls, memory retrieval, or future workers.
- Maintain session, working, semantic, and long-term memory.
- Enforce cost, retry, tool-use, risk, and permission limits.
- Pause for human approval before sensitive or high-risk actions.
- Record structured events for audit, debugging, replay, and analytics.
- Provide enough observability to understand cost, latency, failures, and quality.
- Support future desktop, browser, CLI, and sandbox workers without redesigning the core.

### 2.2 Non-Goals for Phase One

Phase one should not attempt to implement:

- Full desktop automation.
- Unrestricted local file or operating-system control.
- Fully autonomous high-risk actions without approval.
- Enterprise multi-tenant administration unless needed for early users.
- Complex marketplace functionality for third-party tools.
- Fine-tuned model training or custom model hosting.

These areas can be designed for, but the initial implementation should focus on a reliable core brain platform.

---

## 3. System Context

### 3.1 High-Level Architecture

```text
Client Layer
  |
  v
API Gateway
  |
  v
Brain Orchestrator
  |-- Goal Parser
  |-- Planner
  |-- Workflow Engine
  |-- Multi-Agent Hub
  |-- Tool Router
  |-- LLM Service
  |-- Memory System
  |-- Policy Engine
  |-- Budget Controller
  |-- Approval Manager
  |-- Event / Audit / Replay
  |
  v
Worker Gateway (future)
  |
  v
Desktop / Browser / CLI / Sandbox Workers
```

### 3.2 Primary Data Flow

1. A user submits a goal through the web console, SDK, or API.
2. The API Gateway authenticates the request, validates input, and creates a task.
3. The Orchestrator invokes the Goal Parser to normalize the goal.
4. The Planner generates a task plan with steps, dependencies, risks, and expected outputs.
5. The Workflow Engine persists the plan and starts deterministic execution.
6. For each step, the Orchestrator builds context, checks policy and budget, and chooses an execution path.
7. The Tool Router invokes an internal tool, LLM call, memory operation, or future worker.
8. Results are validated, stored, and emitted as structured events.
9. The Orchestrator either advances, retries, requests approval, pauses, fails, or completes the task.
10. Final output, audit trail, cost, and replay data are available through the console and API.

---

## 4. Core Concepts

### 4.1 Task

A task is the top-level unit of work created from a user goal. It has a durable identity, owner, status, budget, plan, events, and final output.

Example task:

```json
{
  "id": "task_123",
  "user_id": "user_001",
  "goal": "Research three CRM tools and recommend one for a small consulting business.",
  "status": "running",
  "created_at": "2026-04-21T09:00:00Z"
}
```

### 4.2 Plan

A plan is a structured decomposition of a task into executable steps. It should include dependencies, required tools, risk levels, expected outputs, and completion criteria.

### 4.3 Step

A step is one unit of execution inside a plan. Steps may run sequentially or in parallel depending on dependencies.

### 4.4 Agent

An agent is a role-bound reasoning or execution unit assigned to part of a task. Agents may be implemented as LLM-driven loops, specialized workflows, or future external workers. Multiple agents should be used only when decomposition creates clear value.

### 4.5 Tool

A tool is a registered capability with a schema, permissions, timeout rules, and execution backend. Tools should be invoked through the Tool Router rather than directly from scattered application code.

### 4.6 Memory Item

A memory item is persisted context that can be retrieved later. It may represent a user preference, task summary, document summary, decision, reusable plan, or learned pattern.

### 4.7 Event

An event is an immutable record of something important that happened. Events are the foundation for streaming, audit, replay, metrics, and debugging.

---

## 5. Component Architecture

### 5.1 Client Layer

The Client Layer lets users and applications interact with the platform.

Primary interfaces:

- Web console.
- REST API.
- SDK.
- Event stream.
- Future desktop or team dashboard.

Responsibilities:

- Submit tasks.
- Display live progress.
- Show current plans and step status.
- Stream events.
- Request and collect approvals.
- Show cost and token usage.
- Inspect sub-agent activity.
- Replay historical runs.
- Display final outputs.

### 5.2 API Gateway

The API Gateway is the secure entry point into the system.

Responsibilities:

- Authentication.
- Authorization.
- Request validation.
- Rate limiting.
- Session identification.
- Task creation.
- Event streaming.
- Approval submission.
- SDK support.
- Future worker registration.

Recommended implementation:

- REST for core task and administration APIs.
- Server-Sent Events or WebSockets for live event streaming.
- OpenAPI schema for public contracts.

### 5.3 Brain Orchestrator

The Brain Orchestrator is the central control system. It transforms a user goal into a controlled, recoverable, observable workflow.

Responsibilities:

- Coordinate goal parsing, planning, execution, retries, approvals, and completion.
- Maintain task-level execution control.
- Decide when to call the Planner, Multi-Agent Hub, Tool Router, Memory System, or LLM Service.
- Enforce workflow-level policy and budget checks.
- Persist checkpoints.
- Emit events for every meaningful transition.

The Orchestrator should not directly contain provider SDK logic, tool-specific implementation, or UI concerns. It should coordinate services through stable interfaces.

### 5.4 Goal Parser

The Goal Parser translates raw user input into structured intent.

It should identify:

- Main objective.
- Required deliverables.
- Constraints.
- Task type.
- Required inputs.
- Missing assumptions.
- Priority.
- Risk level.
- Suggested tools or capabilities.

Example:

```json
{
  "objective": "Analyze retrospectives",
  "input_type": "documents",
  "scope": "last three project retrospectives",
  "deliverable": "recurring issues and recommendations",
  "risk_level": "low",
  "candidate_capabilities": ["document_retrieval", "summarization", "clustering"]
}
```

### 5.5 Planner

The Planner converts structured intent into an executable plan.

Responsibilities:

- Generate steps.
- Define dependencies.
- Identify parallelizable work.
- Define expected outputs per step.
- Mark steps that require approval.
- Estimate rough cost and time.
- Recommend tools, agents, or workers.
- Define completion criteria.

The Planner should generate task structure, not low-level desktop actions. Low-level UI or operating-system actions should be delegated later to workers or tool runtimes.

### 5.6 Workflow Engine / Task State Machine

The Workflow Engine controls the lifecycle of tasks and steps through explicit state transitions.

Task states:

- `created`
- `parsing`
- `planning`
- `running`
- `waiting_for_tool`
- `waiting_for_approval`
- `paused`
- `retrying`
- `completed`
- `failed`
- `cancelled`

Step states:

- `pending`
- `ready`
- `running`
- `blocked`
- `waiting_for_approval`
- `completed`
- `failed`
- `skipped`
- `cancelled`

Responsibilities:

- Persist state transitions.
- Enforce valid transitions.
- Track current active steps.
- Manage retries.
- Handle cancellation.
- Store checkpoints.
- Resume tasks after restart.
- Prevent duplicate execution where idempotency matters.

The Planner defines what should happen. The Workflow Engine controls what is happening now.

### 5.7 Multi-Agent Hub

The Multi-Agent Hub manages collaboration between agents within a task.

Use cases:

- Parallel research.
- Independent verification.
- Critique and review.
- Role-based synthesis.
- Conflict resolution.

Responsibilities:

- Spawn sub-agents.
- Assign roles and scopes.
- Manage shared task context.
- Prevent duplicate work.
- Collect intermediate outputs.
- Merge or reconcile results.
- Decide when agent collaboration is complete.

Design constraint:

- Do not use multiple agents by default. Use them when decomposition improves latency, quality, verification, or specialization.

### 5.8 Tool Router

The Tool Router selects and invokes the best available capability for a step.

Responsibilities:

- Match a step to a registered tool or backend.
- Validate tool input and output.
- Check whether the tool is allowed.
- Check whether approval is required.
- Apply timeout and retry rules.
- Route to internal tools, LLM calls, memory operations, or future workers.
- Provide fallback behavior when a tool is unavailable.

Example routing:

```text
document question -> memory/document retrieval
web research -> browser/search tool
structured reasoning -> LLM Service
local code execution -> sandbox tool
desktop UI action -> future desktop worker
```

### 5.9 Skills / Tool Registry

The Tool Registry is the catalog of capabilities the platform can use.

Each tool definition should include:

- Tool name.
- Description.
- Capability type.
- Input schema.
- Output schema.
- Safety level.
- Required permissions.
- Execution backend.
- Timeout.
- Retry policy.
- Cost model.
- Version.

Example tools:

- `search_documents`
- `summarize_text`
- `compare_items`
- `call_external_api`
- `run_python_sandbox`
- `desktop.click_element` (future)
- `desktop.capture_window` (future)

### 5.10 LLM Service

The LLM Service is the controlled model access layer.

Responsibilities:

- Provider abstraction.
- Model routing.
- Prompt assembly integration.
- Structured output handling.
- Retry on transient failure or malformed output.
- Token estimation.
- Cost tracking.
- Response normalization.
- Provider fallback.

The Orchestrator, Planner, and agents should request capabilities from the LLM Service rather than calling model providers directly.

### 5.11 Model Router

The Model Router selects the best model for a request.

Inputs:

- Task type.
- Required quality.
- Latency target.
- Cost budget.
- Context length.
- Structured output requirement.
- Provider availability.
- Risk level.

Example decisions:

- Summarization: small or medium model.
- Complex planning: stronger reasoning model.
- JSON extraction: model with reliable structured output.
- Failed provider: fallback to alternative provider or retry later.

### 5.12 Prompt Runtime / Prompt Library

The Prompt Runtime manages prompt templates and prompt assembly.

Responsibilities:

- Version prompts.
- Compose system, role, task, tool, and context sections.
- Insert memory and task state safely.
- Track prompt versions in events.
- Support evaluation and regression testing.

Prompts should not be hardcoded across unrelated services. Centralized prompt management makes behavior easier to tune, test, and debug.

### 5.13 Memory System

The Memory System stores and retrieves context across a task, session, and long-term usage.

Memory types:

- **Session memory:** events and summaries from the current task run.
- **Working memory:** current active context used for immediate reasoning.
- **Semantic memory:** embedding-backed retrieval over past tasks, documents, and summaries.
- **Long-term memory:** persistent user preferences, stable facts, reusable plans, and learned patterns.

Responsibilities:

- Store task summaries.
- Store user preferences.
- Store previous task outcomes.
- Retrieve relevant memories for new tasks.
- Summarize long runs.
- Deduplicate memory items.
- Apply privacy and retention rules.

### 5.14 Context Builder

The Context Builder selects the information sent to a model for a specific step.

Responsibilities:

- Retrieve relevant memory items.
- Include task goal, plan, and active step state.
- Include recent events or summaries.
- Include intermediate outputs.
- Stay within token budget.
- Prefer high-signal context over raw history.

The Context Builder is critical because memory is only useful when the right context is selected at the right time.

### 5.15 Budget Controller

The Budget Controller prevents runaway cost and resource use.

It should track:

- Token usage.
- Model cost.
- Tool invocation count.
- Retry count.
- Sub-agent count.
- Wall-clock runtime.
- Compute usage.

Example policies:

- Maximum cost per task.
- Maximum retries per step.
- Maximum sub-agents per task.
- Maximum runtime per task.
- Downgrade model after a cost threshold.
- Stop or request approval when budget is nearly exhausted.

### 5.16 Policy Engine

The Policy Engine determines what is allowed, blocked, or approval-gated.

Policy categories:

- Tool permissions.
- Data access restrictions.
- External network calls.
- File operations.
- Code execution.
- Worker actions.
- Role-based permissions.
- Sensitive data handling.

Example policies:

- External API calls require permission.
- Code execution is allowed only in a sandbox.
- File deletion requires approval.
- Payment, submission, or irreversible actions require approval.
- Sensitive data export is blocked or redacted.

### 5.17 Approval Manager

The Approval Manager handles human confirmation for sensitive actions.

Responsibilities:

- Pause workflows.
- Generate approval requests.
- Explain the proposed action.
- Show risk category and affected data.
- Accept approval or rejection.
- Resume, modify, or cancel the workflow.
- Record approval decisions in the audit log.

Approval request fields should include:

- Task ID.
- Step ID.
- Proposed action.
- Reason for approval.
- Risk level.
- Data involved.
- Timeout or expiration.
- Approver identity.

### 5.18 Event Bus / Event Store

The Event Bus and Event Store record important system activity as structured events.

Event examples:

- `task.created`
- `goal.parsed`
- `plan.generated`
- `step.started`
- `llm.called`
- `tool.selected`
- `tool.completed`
- `approval.requested`
- `approval.approved`
- `step.completed`
- `step.failed`
- `task.completed`
- `task.failed`

Responsibilities:

- Persist immutable event records.
- Stream events to clients.
- Support replay.
- Support audit.
- Feed metrics and analytics.
- Help reconstruct task state.

### 5.19 Audit Log

The Audit Log is the trustworthy record of decisions and actions.

It should record:

- Who initiated a task.
- What goal was submitted.
- Which plan was generated.
- Which tools and models were used.
- Which approvals were requested and granted.
- What data or external systems were touched.
- What outputs were produced.
- When major state transitions occurred.

Audit logs should be append-only and protected from accidental mutation.

### 5.20 Replay System

The Replay System reconstructs historical runs for debugging and improvement.

Replay should allow operators to inspect:

- Original user goal.
- Parsed intent.
- Generated plan.
- Step transitions.
- Prompt versions.
- Model responses.
- Tool calls.
- Retry decisions.
- Approval decisions.
- Final output.

Replay is essential because agent failures are often caused by gradual drift, weak context selection, or incorrect tool choice rather than a single obvious exception.

### 5.21 Observability Layer

The Observability Layer tracks system health and behavior.

Metrics and traces should cover:

- Task throughput.
- Task latency.
- Step latency.
- Tool latency.
- Model latency.
- Provider failure rate.
- Retry count.
- Cost per task.
- Token usage.
- Approval wait time.
- Worker availability.

Recommended tools:

- OpenTelemetry for traces.
- Structured logs for application events.
- Prometheus-compatible metrics.
- Grafana or equivalent dashboards.

### 5.22 Database Layer

The Database Layer stores durable structured state.

Recommended default:

- PostgreSQL for relational state, JSON fields, transactions, and event storage.

Core tables:

- `users`
- `sessions`
- `tasks`
- `task_steps`
- `agents`
- `tools`
- `approvals`
- `events`
- `memories`
- `budgets`
- `prompt_versions`
- `worker_registrations` (future)

The database is the recovery backbone. If the Orchestrator crashes, persisted state and events should make it possible to resume or safely fail a task.

### 5.23 Cache / Coordination Layer

The Cache and Coordination Layer provides fast temporary state.

Recommended default:

- Redis or compatible service.

Use cases:

- Rate limiting.
- Distributed locks.
- Session cache.
- Stream buffering.
- Deduplication keys.
- Short-lived workflow coordination.
- Worker heartbeat tracking.

Durable state should remain in PostgreSQL. Redis should not be the only copy of important task state.

### 5.24 Vector Store

The Vector Store supports semantic retrieval.

Stored embeddings may represent:

- Memory items.
- Task summaries.
- Documents.
- Agent notes.
- Reusable examples.
- Prior decisions.

The Vector Store complements PostgreSQL. It should store references to canonical records rather than becoming the only source of truth.

### 5.25 Worker Gateway

The Worker Gateway is the future bridge between the brain platform and external executors.

Phase-one status:

- Define the interface early.
- Implement a stub or simple registration model only if useful.
- Do not block the brain platform on desktop automation.

Future responsibilities:

- Worker registration.
- Capability discovery.
- Worker authentication.
- Heartbeats.
- Task assignment.
- Result streaming.
- Cancellation.
- Version management.
- Worker health checks.

Future worker types:

- Windows desktop worker.
- Browser automation worker.
- CLI worker.
- Code sandbox worker.
- Mobile or remote environment worker.

### 5.26 Future Desktop Worker

The desktop worker will be an external execution endpoint, not part of the core brain.

Future capabilities:

- Observe desktop state.
- Capture screenshots.
- Inspect UI trees when available.
- Execute clicks, typing, and navigation.
- Return structured state and evidence.
- Request approval for risky actions.
- Report progress and errors.

The desktop worker should consume the same execution protocol as other workers. This prevents desktop automation from becoming a special-case dependency inside the Orchestrator.

### 5.27 Web Console

The Web Console is the operator-facing UI.

Core screens:

- Task creation.
- Live task execution.
- Plan and step view.
- Agent activity view.
- Event stream.
- Approval queue.
- Cost and token usage.
- Replay viewer.
- Final result viewer.
- Tool and worker status.

The console is important even for an API-first product because agent systems need inspection, debugging, and trust-building interfaces.

### 5.28 SDK Layer

The SDK allows other applications to use the platform programmatically.

Responsibilities:

- Create tasks.
- Stream events.
- Retrieve task status.
- Submit approvals.
- Read final results.
- Register tools or workers in future phases.

Initial SDK language:

- TypeScript is a practical first choice if the web console and API are also TypeScript-based.
- Python can be added when data, automation, or notebook users become important.

---

## 6. Suggested Data Model

### 6.1 Task

Fields:

- `id`
- `user_id`
- `session_id`
- `goal`
- `parsed_goal`
- `status`
- `priority`
- `risk_level`
- `budget_limit`
- `budget_used`
- `created_at`
- `updated_at`
- `completed_at`
- `final_output`
- `failure_reason`

### 6.2 Task Step

Fields:

- `id`
- `task_id`
- `parent_step_id`
- `name`
- `description`
- `status`
- `sequence_order`
- `dependencies`
- `assigned_agent_id`
- `required_capability`
- `selected_tool_id`
- `risk_level`
- `approval_required`
- `input_payload`
- `output_payload`
- `error`
- `retry_count`
- `started_at`
- `completed_at`

### 6.3 Event

Fields:

- `id`
- `task_id`
- `step_id`
- `agent_id`
- `event_type`
- `payload`
- `created_at`
- `actor_type`
- `actor_id`
- `correlation_id`
- `trace_id`

### 6.4 Tool Definition

Fields:

- `id`
- `name`
- `description`
- `capability_type`
- `input_schema`
- `output_schema`
- `backend_type`
- `risk_level`
- `required_permissions`
- `timeout_seconds`
- `retry_policy`
- `version`
- `enabled`

### 6.5 Memory Item

Fields:

- `id`
- `user_id`
- `task_id`
- `memory_type`
- `content`
- `summary`
- `metadata`
- `embedding_ref`
- `importance`
- `expires_at`
- `created_at`
- `updated_at`

### 6.6 Approval

Fields:

- `id`
- `task_id`
- `step_id`
- `status`
- `requested_action`
- `risk_level`
- `reason`
- `requested_by`
- `approved_by`
- `expires_at`
- `created_at`
- `resolved_at`

---

## 7. API Surface

### 7.1 Task APIs

```text
POST   /v1/tasks
GET    /v1/tasks/{task_id}
GET    /v1/tasks/{task_id}/steps
POST   /v1/tasks/{task_id}/cancel
GET    /v1/tasks/{task_id}/result
```

### 7.2 Event APIs

```text
GET    /v1/tasks/{task_id}/events
GET    /v1/tasks/{task_id}/events/stream
```

### 7.3 Approval APIs

```text
GET    /v1/approvals
POST   /v1/approvals/{approval_id}/approve
POST   /v1/approvals/{approval_id}/reject
```

### 7.4 Memory APIs

```text
GET    /v1/memories
POST   /v1/memories
GET    /v1/memories/search
DELETE /v1/memories/{memory_id}
```

### 7.5 Tool APIs

```text
GET    /v1/tools
POST   /v1/tools
PATCH  /v1/tools/{tool_id}
```

### 7.6 Future Worker APIs

```text
POST   /v1/workers/register
POST   /v1/workers/{worker_id}/heartbeat
GET    /v1/workers/{worker_id}/assignments
POST   /v1/workers/{worker_id}/results
POST   /v1/workers/{worker_id}/events
```

---

## 8. Key Execution Flows

### 8.1 Task Creation and Planning

1. User submits a goal.
2. API Gateway validates the request.
3. A `task.created` event is stored.
4. Orchestrator calls the Goal Parser.
5. A `goal.parsed` event is stored.
6. Orchestrator calls the Planner.
7. Plan and steps are persisted.
8. A `plan.generated` event is stored.
9. Workflow Engine marks eligible steps as `ready`.

### 8.2 Step Execution

1. Workflow Engine selects a `ready` step.
2. Context Builder prepares task, memory, and event context.
3. Budget Controller checks remaining limits.
4. Policy Engine checks whether the action is allowed.
5. Approval Manager pauses the step if approval is required.
6. Tool Router selects a tool or backend.
7. Tool or model call executes.
8. Output is validated.
9. Step output is stored.
10. Event Store records success or failure.
11. Workflow Engine advances dependent steps.

### 8.3 Approval Flow

1. Policy Engine marks an action as approval-gated.
2. Approval Manager creates an approval request.
3. Workflow Engine moves the step to `waiting_for_approval`.
4. Client displays the approval request.
5. User approves or rejects the request.
6. Audit Log records the decision.
7. Workflow Engine resumes, modifies, or cancels the step.

### 8.4 Failure and Retry Flow

1. A step fails due to tool error, model error, validation error, timeout, or policy rejection.
2. Workflow Engine checks retry policy and retry count.
3. Retryable failures move to `retrying`.
4. Non-retryable failures move the step to `failed`.
5. Orchestrator decides whether to re-plan, skip, request user input, or fail the task.
6. Event Store records the failure and decision.

### 8.5 Replay Flow

1. User opens a historical task.
2. Replay System loads task, steps, events, prompts, tool calls, and outputs.
3. UI reconstructs the execution timeline.
4. User inspects decisions, retries, approvals, and final result.
5. Insights can be used to improve prompts, tools, policies, or planning logic.

---

## 9. Reliability and Safety Requirements

### 9.1 Reliability

The platform should:

- Persist task state before executing risky or expensive operations.
- Make step execution idempotent where possible.
- Use retries only for failures that are likely transient.
- Apply timeouts to model and tool calls.
- Support cancellation.
- Resume safely after process restart.
- Preserve enough state to explain failed tasks.

### 9.2 Safety

The platform should:

- Require approval for high-risk actions.
- Run code only in sandboxed environments.
- Restrict sensitive data export.
- Log all external actions.
- Redact secrets from logs and prompts.
- Use least-privilege credentials for tools and workers.
- Keep model output advisory until validated by deterministic code or policy checks.

### 9.3 Security

Baseline security requirements:

- Authenticate every API request.
- Authorize access to task, memory, event, and approval data.
- Encrypt secrets at rest.
- Avoid storing raw provider credentials in application logs.
- Validate all tool inputs against schemas.
- Treat worker results as untrusted input.
- Protect event and audit logs from mutation.

### 9.4 Privacy

The Memory System should support:

- User-controlled deletion.
- Memory expiration.
- Sensitive memory classification.
- Redaction before model calls when required.
- Clear separation between private user memory and shared system knowledge.

---

## 10. Observability and Quality Metrics

### 10.1 Operational Metrics

Track:

- Number of tasks created.
- Number of tasks completed.
- Task success rate.
- Average task duration.
- Step failure rate.
- Tool failure rate.
- Model provider failure rate.
- Retry rate.
- Approval wait time.
- Worker health in future phases.

### 10.2 Cost Metrics

Track:

- Cost per task.
- Cost per step.
- Cost by model.
- Token usage by model.
- Tool execution cost.
- Cost saved by model routing or caching.

### 10.3 Quality Metrics

Track:

- User acceptance of final outputs.
- Number of tasks requiring manual correction.
- Planner revision rate.
- Failed validation rate.
- Replay-identified root causes.
- Frequency of policy blocks.

---

## 11. Recommended Technology Stack

This is a practical default stack, not a permanent constraint.

### 11.1 Backend

- TypeScript with Node.js for API, orchestration, and SDK alignment.
- Fastify or NestJS for API structure.
- PostgreSQL for durable state.
- Redis for cache, locks, and coordination.
- Queue system such as BullMQ, Temporal, or a lightweight internal queue depending on complexity.

### 11.2 Workflow

Two viable options:

- Start with a simple explicit state machine if phase-one workflows are controlled and small.
- Move to Temporal or another durable workflow engine when workflows become long-running, distributed, or highly retry-sensitive.

### 11.3 Frontend

- React or Next.js for the web console.
- Server-Sent Events or WebSockets for live task updates.

### 11.4 AI Infrastructure

- LLM provider abstraction in the LLM Service.
- Prompt versioning stored in PostgreSQL.
- Embeddings through the LLM Service.
- Vector store through PostgreSQL with pgvector or a dedicated vector database when scale requires it.

### 11.5 Observability

- OpenTelemetry traces.
- Structured JSON logs.
- Prometheus-compatible metrics.
- Grafana dashboards or equivalent.

---

## 12. Phase Plan

### 12.1 Phase One: Core Brain MVP

Build:

- API Gateway.
- Task and event schemas.
- Basic Orchestrator.
- Goal Parser.
- Planner.
- Workflow Engine.
- LLM Service.
- Prompt Runtime.
- Basic Web Console.
- Event stream.
- PostgreSQL persistence.

Success criteria:

- A user can create a task.
- The system can parse the goal, generate a plan, execute simple steps, and produce a final result.
- The console can show live events and final output.
- A failed task leaves enough events to debug what happened.

### 12.2 Phase Two: Control and Memory

Build:

- Memory System.
- Context Builder.
- Tool Registry.
- Tool Router.
- Budget Controller.
- Policy Engine.
- Approval Manager.
- Basic replay view.

Success criteria:

- The system can retrieve useful prior context.
- Tool calls are schema-validated and logged.
- Budget limits stop runaway tasks.
- Approval-gated actions pause and resume correctly.
- Historical runs can be inspected.

### 12.3 Phase Three: Multi-Agent and Production Hardening

Build:

- Multi-Agent Hub.
- Better step parallelism.
- Advanced replay.
- Observability dashboards.
- Evaluation harness.
- Model routing optimization.
- More robust retry and re-planning.

Success criteria:

- Complex tasks can be split across specialized agents.
- Operators can see cost, latency, failures, and provider health.
- Prompt and planning changes can be evaluated against historical scenarios.

### 12.4 Phase Four: Worker Gateway and External Execution

Build:

- Worker Gateway.
- Worker registration and heartbeat.
- Capability discovery.
- Assignment protocol.
- Browser, CLI, sandbox, or desktop worker prototype.
- Worker event streaming.
- Worker approval gates.

Success criteria:

- External workers can register capabilities.
- The brain can assign work to a worker through a stable protocol.
- Worker actions are policy-checked, budgeted, logged, and replayable.

### 12.5 Phase Five: Desktop Worker

Build:

- Windows desktop worker.
- Screenshot capture.
- UI tree inspection where available.
- Controlled click/type/navigation actions.
- Desktop-specific approval gates.
- Robust error reporting and recovery.

Success criteria:

- The desktop worker can execute bounded UI tasks.
- Risky or irreversible actions require approval.
- The brain platform remains worker-agnostic.

---

## 13. Implementation Priorities

Recommended build order:

1. Define database schema for tasks, steps, events, approvals, tools, and memories.
2. Implement task creation API.
3. Implement append-only event storage.
4. Implement basic Orchestrator.
5. Implement Goal Parser and Planner through the LLM Service.
6. Implement Workflow Engine with explicit task and step states.
7. Implement live event streaming to the web console.
8. Implement final result storage and retrieval.
9. Add Tool Registry and Tool Router.
10. Add Budget Controller.
11. Add Policy Engine and Approval Manager.
12. Add Memory System and Context Builder.
13. Add Replay System.
14. Add Multi-Agent Hub.
15. Add Worker Gateway.
16. Add desktop, browser, CLI, or sandbox workers.

---

## 14. Design Decisions

### 14.1 Build the Brain Before the Desktop Worker

The desktop worker should not drive the architecture. The brain platform needs durable workflows, planning, policy, budget control, replay, and observability before it can safely control external environments.

### 14.2 Use Events as a First-Class System Primitive

Events should not be treated as optional logs. They are needed for streaming, debugging, replay, audit, metrics, and user trust.

### 14.3 Keep LLM Calls Behind a Service Boundary

Direct model SDK calls should not spread through the codebase. A central LLM Service makes model routing, cost tracking, retries, schema validation, and provider changes manageable.

### 14.4 Make Tools Declarative

Tools should be registered with schemas, permissions, risk levels, and execution backends. This allows the platform to validate use, inspect capabilities, and enforce policy consistently.

### 14.5 Treat External Workers as Untrusted Executors

Workers should authenticate, declare capabilities, receive bounded assignments, return structured evidence, and be subject to policy and approval gates.

---

## 15. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Plans are vague or not executable | Tasks stall or produce weak output | Require structured plan schema and completion criteria |
| Model output is malformed | Workflow errors | Use schema validation, retries, and fallback prompts |
| Costs grow unpredictably | User loses trust | Enforce task budgets, model routing, and retry limits |
| Memory retrieval adds noise | Lower answer quality | Use relevance scoring, summarization, and context budgets |
| Too many agents increase complexity | More cost and coordination overhead | Use multi-agent execution only when it has clear value |
| Tool calls are unsafe | Security or data risk | Use Tool Registry, Policy Engine, and Approval Manager |
| Event logs are incomplete | Replay and debugging fail | Emit events for every important state transition |
| Desktop automation arrives too early | Core architecture becomes coupled to UI actions | Build Worker Gateway after core brain primitives are stable |

---

## 16. Open Questions

- Should the first backend be TypeScript, Python, or a hybrid?
- Should workflow durability start with a custom state machine or Temporal?
- Which model providers should be supported in the first release?
- Should memory be user-scoped only, or should there also be shared project memory?
- What actions must always require approval?
- What is the default maximum budget per task?
- Should the first worker be browser, CLI, sandbox, or desktop?
- What evaluation set should be used to measure planning quality?

---

## 17. Summary

The Brain Agent Platform should be built as a durable orchestration system, not as a collection of prompts and tool calls. The first milestone is a reliable brain that can parse goals, plan work, execute controlled steps, track events, manage model access, and produce inspectable results.

Once that core is stable, memory, policy, approval, replay, multi-agent coordination, and worker execution can be added in layers. This approach keeps the architecture extensible and makes future desktop automation a consumer of the platform rather than the foundation of it.
