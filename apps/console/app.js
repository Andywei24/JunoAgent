const state = {
  tasks: [],
  selectedTaskId: null,
  task: null,
  steps: [],
  events: [],
  stream: null,
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
els.cancelTask.addEventListener("click", cancelSelectedTask);

loadTasks();

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
