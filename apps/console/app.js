const state = {
  tasks: [],
  selectedTaskId: null,
  task: null,
  steps: [],
  events: [],
  stream: null,
  approvals: [],
  memories: [],
};

const EVENT_NAMES = [
  "task.created",
  "task.completed",
  "task.failed",
  "task.cancelled",
  "goal.parsed",
  "plan.generated",
  "step.ready",
  "step.started",
  "step.completed",
  "step.failed",
  "step.skipped",
  "step.retrying",
  "llm.called",
  "tool.selected",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "approval.requested",
  "approval.approved",
  "approval.rejected",
  "policy.blocked",
  "budget.exceeded",
  "memory.written",
  "memory.retrieved",
];

const els = {
  form: document.querySelector("#task-form"),
  goal: document.querySelector("#goal"),
  priority: document.querySelector("#priority"),
  taskList: document.querySelector("#task-list"),
  refreshTasks: document.querySelector("#refresh-tasks"),
  cancelTask: document.querySelector("#cancel-task"),
  emptyState: document.querySelector("#empty-state"),
  taskView: document.querySelector("#task-view"),
  taskTitle: document.querySelector("#task-title"),
  streamState: document.querySelector("#stream-state"),
  detailStatus: document.querySelector("#detail-status"),
  detailRisk: document.querySelector("#detail-risk"),
  detailSteps: document.querySelector("#detail-steps"),
  detailEvents: document.querySelector("#detail-events"),
  detailBudget: document.querySelector("#detail-budget"),
  detailBudgetDetail: document.querySelector("#detail-budget-detail"),
  refreshApprovals: document.querySelector("#refresh-approvals"),
  approvalList: document.querySelector("#approval-list"),
  refreshMemories: document.querySelector("#refresh-memories"),
  memoryList: document.querySelector("#memory-list"),
  planUpdated: document.querySelector("#plan-updated"),
  stepList: document.querySelector("#step-list"),
  finalOutput: document.querySelector("#final-output"),
  parsedGoal: document.querySelector("#parsed-goal"),
  eventList: document.querySelector("#event-list"),
  lastEvent: document.querySelector("#last-event"),
  toast: document.querySelector("#toast"),
};

els.form.addEventListener("submit", createTask);
els.refreshTasks.addEventListener("click", loadTasks);
els.refreshApprovals.addEventListener("click", loadApprovals);
els.refreshMemories.addEventListener("click", loadMemories);
els.cancelTask.addEventListener("click", cancelSelectedTask);

loadTasks();
loadApprovals();
loadMemories();

async function createTask(event) {
  event.preventDefault();
  const goal = els.goal.value.trim();
  if (!goal) return;

  setFormBusy(true);
  try {
    const task = await api("/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal,
        priority: Number.parseInt(els.priority.value || "0", 10),
        budget_limit: {},
      }),
    });
    els.goal.value = "";
    await loadTasks();
    await selectTask(task.id);
    showToast("Task created.");
  } catch (error) {
    showToast(error.message);
  } finally {
    setFormBusy(false);
  }
}

async function loadTasks() {
  try {
    state.tasks = await api("/v1/tasks?limit=100");
    renderTasks();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadApprovals() {
  try {
    state.approvals = await api("/v1/approvals");
    renderApprovals();
  } catch (error) {
    showToast(error.message);
  }
}

async function approveApproval(approvalId) {
  try {
    await api(`/v1/approvals/${encodeURIComponent(approvalId)}/approve`, {
      method: "POST",
    });
    showToast("Approval granted.");
    await loadApprovals();
    if (state.selectedTaskId) await refreshSelectedTask();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadMemories() {
  try {
    state.memories = await api("/v1/memories?limit=50");
    renderMemories();
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteMemory(memoryId) {
  try {
    await api(`/v1/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" });
    showToast("Memory removed.");
    await loadMemories();
  } catch (error) {
    showToast(error.message);
  }
}

async function rejectApproval(approvalId) {
  try {
    await api(`/v1/approvals/${encodeURIComponent(approvalId)}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    showToast("Approval rejected.");
    await loadApprovals();
    if (state.selectedTaskId) await refreshSelectedTask();
  } catch (error) {
    showToast(error.message);
  }
}

async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  closeStream();
  await refreshSelectedTask();
  openStream();
  renderTasks();
}

async function refreshSelectedTask() {
  if (!state.selectedTaskId) return;
  const id = state.selectedTaskId;
  const [task, steps, events] = await Promise.all([
    api(`/v1/tasks/${encodeURIComponent(id)}`),
    api(`/v1/tasks/${encodeURIComponent(id)}/steps`),
    api(`/v1/tasks/${encodeURIComponent(id)}/events?limit=500`),
  ]);
  state.task = task;
  state.steps = steps;
  state.events = events;
  renderDetail();
  await loadTasks();
}

async function cancelSelectedTask() {
  if (!state.selectedTaskId) return;
  try {
    await api(`/v1/tasks/${encodeURIComponent(state.selectedTaskId)}/cancel`, {
      method: "POST",
    });
    await refreshSelectedTask();
    showToast("Task cancelled.");
  } catch (error) {
    showToast(error.message);
  }
}

function openStream() {
  if (!state.selectedTaskId) return;
  const lastSequence = state.events.at(-1)?.sequence || 0;
  const url = `/v1/tasks/${encodeURIComponent(state.selectedTaskId)}/events/stream?after_sequence=${lastSequence}`;
  state.stream = new EventSource(url);
  setStreamState("Stream connected");

  for (const name of EVENT_NAMES) {
    state.stream.addEventListener(name, handleStreamEvent);
  }
  state.stream.addEventListener("stream.end", (event) => {
    const payload = JSON.parse(event.data);
    setStreamState(`Stream ended: ${payload.final_status}`);
    closeStream(false);
    refreshSelectedTask();
  });
  state.stream.onerror = () => {
    setStreamState("Stream reconnecting");
  };
}

function closeStream(updateLabel = true) {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  if (updateLabel) setStreamState("Stream idle");
}

function handleStreamEvent(event) {
  const payload = JSON.parse(event.data);
  if (!state.events.some((item) => item.sequence === payload.sequence)) {
    state.events.push(payload);
  }
  renderEvents();
  refreshSelectedTask();
  if (event.type.startsWith("approval.")) {
    loadApprovals();
  }
  if (event.type === "memory.written") {
    loadMemories();
  }
}

function renderTasks() {
  if (!state.tasks.length) {
    els.taskList.innerHTML = `<p class="muted">No tasks yet.</p>`;
    return;
  }
  els.taskList.replaceChildren(
    ...state.tasks.map((task) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `task-card ${task.id === state.selectedTaskId ? "active" : ""}`;
      button.addEventListener("click", () => selectTask(task.id));
      button.innerHTML = `
        <strong>${escapeHtml(task.goal)}</strong>
        <div class="card-meta">
          ${statusPill(task.status)}
          <span>${formatDate(task.created_at)}</span>
        </div>
      `;
      return button;
    }),
  );
}

function renderDetail() {
  if (!state.task) {
    els.emptyState.hidden = false;
    els.taskView.hidden = true;
    els.cancelTask.hidden = true;
    return;
  }

  els.emptyState.hidden = true;
  els.taskView.hidden = false;
  els.cancelTask.hidden = isTerminal(state.task.status);
  els.taskTitle.textContent = state.task.goal;
  els.detailStatus.innerHTML = statusPill(state.task.status);
  els.detailRisk.textContent = state.task.risk_level || "low";
  els.detailSteps.textContent = String(state.steps.length);
  els.detailEvents.textContent = String(state.events.length);
  els.planUpdated.textContent = state.task.updated_at ? `Updated ${formatDate(state.task.updated_at)}` : "";
  renderBudget(state.task.budget_limit, state.task.budget_used);
  els.parsedGoal.textContent = formatJson(state.task.parsed_goal);
  els.finalOutput.textContent = state.task.final_output
    ? formatJson(state.task.final_output)
    : state.task.failure_reason || "No final output yet.";

  renderSteps();
  renderEvents();
}

function renderSteps() {
  if (!state.steps.length) {
    els.stepList.innerHTML = `<p class="muted">Plan has not been generated yet.</p>`;
    return;
  }
  els.stepList.replaceChildren(
    ...state.steps.map((step, index) => {
      const item = document.createElement("article");
      item.className = "step-item";
      item.innerHTML = `
        <div class="step-index">${index + 1}</div>
        <div>
          <h3>${escapeHtml(step.name)}</h3>
          <p>${escapeHtml(step.description || "No description.")}</p>
          <div class="step-meta">
            ${statusPill(step.status)}
            <span>${escapeHtml(step.required_capability || "reasoning")}</span>
            <span>risk: ${escapeHtml(step.risk_level || "low")}</span>
            ${step.approval_required ? "<span>approval required</span>" : ""}
          </div>
          ${step.error ? `<pre class="event-payload">${escapeHtml(step.error)}</pre>` : ""}
        </div>
      `;
      return item;
    }),
  );
}

function renderBudget(limit, used) {
  limit = limit || {};
  used = used || {};
  const keys = new Set([...Object.keys(limit), ...Object.keys(used)]);
  if (!keys.size) {
    els.detailBudget.textContent = "unbounded";
    els.detailBudgetDetail.textContent = "";
    return;
  }
  const rows = [];
  let headline = "ok";
  for (const key of keys) {
    const u = used[key];
    const l = limit[key];
    if (u !== undefined && l !== undefined) {
      rows.push(`${shortBudgetKey(key)} ${u}/${l}`);
      if (Number(u) >= Number(l)) headline = "at limit";
    } else if (u !== undefined) {
      rows.push(`${shortBudgetKey(key)} ${u}`);
    } else if (l !== undefined) {
      rows.push(`${shortBudgetKey(key)} 0/${l}`);
    }
  }
  els.detailBudget.textContent = headline;
  els.detailBudgetDetail.textContent = rows.join(" · ");
}

function shortBudgetKey(key) {
  return key.replace(/^max_/, "").replaceAll("_", " ");
}

function renderApprovals() {
  if (!state.approvals.length) {
    els.approvalList.innerHTML = `<p class="muted">No pending approvals.</p>`;
    return;
  }
  els.approvalList.replaceChildren(
    ...state.approvals.map((approval) => {
      const item = document.createElement("article");
      item.className = "approval-item";
      const reason = approval.reason || approval.requested_action || "awaiting decision";
      item.innerHTML = `
        <strong>${escapeHtml(approval.requested_action || "approval")}</strong>
        <div class="approval-meta">
          <span>risk: ${escapeHtml(approval.risk_level || "medium")}</span>
          <span>${formatDate(approval.created_at)}</span>
        </div>
        <p class="approval-reason">${escapeHtml(reason)}</p>
        <div class="approval-actions">
          <button type="button" data-action="approve" data-id="${escapeHtml(approval.id)}">Approve</button>
          <button type="button" data-action="reject" data-id="${escapeHtml(approval.id)}">Reject</button>
          <button type="button" data-action="view" data-id="${escapeHtml(approval.task_id)}">View task</button>
        </div>
      `;
      item.querySelector('[data-action="approve"]').addEventListener("click", () =>
        approveApproval(approval.id),
      );
      item.querySelector('[data-action="reject"]').addEventListener("click", () =>
        rejectApproval(approval.id),
      );
      item.querySelector('[data-action="view"]').addEventListener("click", () =>
        selectTask(approval.task_id),
      );
      return item;
    }),
  );
}

function renderMemories() {
  if (!state.memories.length) {
    els.memoryList.innerHTML = `<p class="muted">No memories yet.</p>`;
    return;
  }
  els.memoryList.replaceChildren(
    ...state.memories.map((memory) => {
      const item = document.createElement("article");
      item.className = "memory-item";
      const summary = memory.summary || memory.content.slice(0, 80);
      const importance = Number(memory.importance || 0).toFixed(2);
      item.innerHTML = `
        <strong>${escapeHtml(summary)}</strong>
        <div class="memory-meta">
          <span>${escapeHtml(memory.memory_type)}</span>
          <span>importance ${escapeHtml(importance)}</span>
          <span>${formatDate(memory.created_at)}</span>
          ${memory.task_id ? `<span>task</span>` : ""}
        </div>
        <p class="memory-body">${escapeHtml(memory.content.slice(0, 220))}${memory.content.length > 220 ? "…" : ""}</p>
        <div class="memory-actions">
          ${memory.task_id ? `<button type="button" data-action="view" data-id="${escapeHtml(memory.task_id)}">View task</button>` : ""}
          <button type="button" data-action="delete" data-id="${escapeHtml(memory.id)}">Forget</button>
        </div>
      `;
      item.querySelector('[data-action="delete"]').addEventListener("click", () =>
        deleteMemory(memory.id),
      );
      const viewBtn = item.querySelector('[data-action="view"]');
      if (viewBtn) {
        viewBtn.addEventListener("click", () => selectTask(memory.task_id));
      }
      return item;
    }),
  );
}

function renderEvents() {
  els.detailEvents.textContent = String(state.events.length);
  if (!state.events.length) {
    els.eventList.innerHTML = `<p class="muted">No events recorded yet.</p>`;
    els.lastEvent.textContent = "";
    return;
  }

  els.lastEvent.textContent = `#${state.events.at(-1).sequence}`;
  els.eventList.replaceChildren(
    ...state.events
      .slice()
      .reverse()
      .map((event) => {
        const item = document.createElement("article");
        item.className = "event-item";
        item.innerHTML = `
          <strong>${escapeHtml(event.event_type)}</strong>
          <div class="event-meta">
            <span>#${event.sequence}</span>
            <span>${formatDate(event.created_at)}</span>
            ${event.step_id ? `<span>${escapeHtml(event.step_id)}</span>` : ""}
          </div>
          <pre class="event-payload">${escapeHtml(formatJson(event.payload))}</pre>
        `;
        return item;
      }),
  );
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail || JSON.stringify(body) : body;
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return body;
}

function statusPill(status) {
  return `<span class="status-pill status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function isTerminal(status) {
  return ["completed", "failed", "cancelled"].includes(status);
}

function setFormBusy(isBusy) {
  els.form.querySelector("button").disabled = isBusy;
}

function setStreamState(label) {
  els.streamState.textContent = label;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 3500);
}

function formatJson(value) {
  if (value === null || value === undefined) return "{}";
  return JSON.stringify(value, null, 2);
}

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
