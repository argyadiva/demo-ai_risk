"use strict";

const byId = (id) => document.getElementById(id);
const state = { selectedRunId: null, activeRunId: null, source: null, records: new Map() };
const escapeText = (value) => String(value ?? "");

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = escapeText(text);
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) { /* Keep the safe status message. */ }
    throw new Error(message);
  }
  return response.json();
}

function notify(message) {
  const toast = byId("toast");
  toast.textContent = escapeText(message);
  toast.hidden = false;
  window.setTimeout(() => { toast.hidden = true; }, 3500);
}

function setRunState(value) {
  const node = byId("run-state");
  node.textContent = value.toUpperCase();
  node.dataset.state = value;
  const busy = value === "running";
  byId("run-button").disabled = busy;
  byId("cancel-button").disabled = !busy;
}

function renderEvent(eventName, payload, timestamp = "") {
  const list = byId("trace-list");
  if (list.firstElementChild?.classList.contains("muted")) clear(list);
  const row = element("li", "trace-event", "");
  const heading = element("div", "trace-event-head", "");
  heading.append(element("strong", "", eventName), element("span", "", timestamp ? new Date(timestamp).toLocaleTimeString() : "live"));
  const details = element("pre", "", JSON.stringify(payload, null, 2));
  row.append(heading, details);
  list.append(row);
  list.scrollTop = list.scrollHeight;
}

function renderRun(record) {
  if (!record) return;
  const run = record.result;
  byId("run-id").textContent = record.run_id;
  setRunState(record.status);
  if (!run) return;
  state.records.set(record.run_id, record);
  byId("answer").textContent = run.output || "No final response was returned.";
  byId("metric-model").textContent = run.model_turns;
  byId("metric-tools").textContent = run.tool_calls.length;
  byId("metric-input").textContent = run.input_tokens;
  byId("metric-output").textContent = run.output_tokens;
  byId("metric-latency").textContent = `${run.latency_ms} ms`;
  byId("metric-cost").textContent = run.estimated_cost_usd == null ? "not configured" : `$${Number(run.estimated_cost_usd).toFixed(6)}`;
  const limits = run.resource_limits || {};
  byId("metric-limits").textContent = `${limits.max_model_turns ?? "?"} turns · ${limits.max_tool_calls ?? "?"} tools · ${limits.max_output_tokens_per_turn ?? "?"} output tokens/turn · ${limits.max_input_characters ?? "?"} input chars`;
  clear(byId("trace-list"));
  record.events?.forEach((event) => renderEvent(event.event, event.data, event.timestamp));
  if (!record.events?.some((event) => event.event === "tool.completed")) {
    run.tool_calls.forEach((call) => renderEvent(`tool.${call.name} · ${call.status}`, call));
  }
  renderHistory();
  renderData(record.run_id).catch((error) => notify(error.message));
  byId("replay-button").disabled = false;
  byId("export-button").disabled = false;
}

async function renderData(runId) {
  const data = await api(`/v1/runs/${encodeURIComponent(runId)}/data`);
  const root = byId("data-state");
  clear(root);
  root.append(element("p", "eyebrow", "SYNTHETIC FIXTURE · BEFORE → AFTER"));
  data.database.customers.forEach((customer) => {
    const card = element("article", "customer-card", "");
    card.append(element("h3", "", `${customer.customer_id} · ${customer.display_name}`));
    Object.entries(customer).filter(([key]) => key !== "customer_id" && key !== "display_name").forEach(([key, value]) => {
      const pair = element("div", `field-pair${["internal_notes", "review_flag"].includes(key) ? " internal" : ""}`, "");
      pair.append(element("span", "", key.replaceAll("_", " ")), element("span", "", value));
      card.append(pair);
    });
    root.append(card);
  });
  const ticketsAfter = data.database.tickets.length;
  const ticketsBefore = ticketsAfter - Number(data.ticket_change_count || 0);
  root.append(element("h3", "data-section-title", `Support tickets · ${ticketsBefore} before → ${ticketsAfter} after`));
  root.append(element("p", "muted", `${data.ticket_change_count || 0} ticket row(s) were added in this independent attempt.`));
  if (!data.database.tickets.length) root.append(element("p", "muted", "No ticket was persisted."));
  data.database.tickets.forEach((ticket) => {
    const card = element("article", "ticket-card", "");
    card.textContent = `${ticket.ticket_id} · ${ticket.customer_id} · ${ticket.priority} · ${ticket.status}\n${ticket.summary}\nRequest: ${ticket.request_id}`;
    root.append(card);
  });
}

async function renderHistory() {
  const history = await api("/v1/runs?limit=30");
  const root = byId("history-list");
  clear(root);
  if (!history.length) {
    root.append(element("p", "muted", "No attempts yet."));
    updateCompareOptions([]);
    return;
  }
  history.forEach((item) => {
    const button = element("button", `history-item${state.selectedRunId === item.run_id ? " active" : ""}`, "");
    button.type = "button";
    const info = element("span", "", "");
    info.append(element("strong", "", `${item.customer_id || 'Saved account'} · ${item.status}`), element("small", "", item.message));
    button.append(info, element("code", "", item.run_id.slice(0, 8)));
    button.addEventListener("click", () => loadRun(item.run_id));
    root.append(button);
  });
  updateCompareOptions(history);
}

function updateCompareOptions(history) {
  const before = byId("compare-before");
  const after = byId("compare-after");
  const oldBefore = before.value;
  const oldAfter = after.value;
  [before, after].forEach((select) => {
    clear(select);
    select.append(new Option("Choose a saved run", ""));
    history.forEach((item) => {
      const date = item.submitted_at ? new Date(item.submitted_at).toLocaleTimeString() : "saved run";
      select.append(new Option(`${item.customer_id || 'Saved account'} · ${item.status} · ${date} · ${item.run_id.slice(0, 8)}`, item.run_id));
    });
  });
  before.value = history.some((item) => item.run_id === oldBefore) ? oldBefore : (history[1]?.run_id || "");
  after.value = history.some((item) => item.run_id === oldAfter) ? oldAfter : (state.selectedRunId || history[0]?.run_id || "");
  updateCompareButton();
}

function updateCompareButton() {
  const before = byId("compare-before").value;
  const after = byId("compare-after").value;
  byId("compare-button").disabled = !before || !after || before === after;
}

async function compareAttempts() {
  const beforeId = byId("compare-before").value;
  const afterId = byId("compare-after").value;
  if (!beforeId || !afterId || beforeId === afterId) return;
  const comparison = await api(`/v1/runs/${encodeURIComponent(beforeId)}/compare/${encodeURIComponent(afterId)}`);
  const root = byId("comparison-result");
  clear(root);
  const table = element("table", "comparison-table", "");
  const header = element("tr", "", "");
  header.append(element("th", "", "Evidence"), element("th", "", "Before"), element("th", "", "After"));
  const head = element("thead", "", "");
  head.append(header);
  const body = element("tbody", "", "");
  const rows = [
    ["Run and status", `${comparison.before.run_id}\n${comparison.before.status}`, `${comparison.after.run_id}\n${comparison.after.status}`],
    ["Session customer", comparison.before.customer_id, comparison.after.customer_id],
    ["Implementation fingerprint", comparison.before.implementation_fingerprint, comparison.after.implementation_fingerprint],
    ["Reproducing request", comparison.before.message, comparison.after.message],
    ["Model / prompt / dataset", `${comparison.before.model_name}\n${comparison.before.prompt_version}\n${comparison.before.dataset_version}`, `${comparison.after.model_name}\n${comparison.after.prompt_version}\n${comparison.after.dataset_version}`],
    ["Active resource limits", JSON.stringify(comparison.before.resource_limits, null, 2), JSON.stringify(comparison.after.resource_limits, null, 2)],
    ["Resource use", JSON.stringify(comparison.before.metrics, null, 2), JSON.stringify(comparison.after.metrics, null, 2)],
    ["Tool calls", JSON.stringify(comparison.before.tool_calls, null, 2), JSON.stringify(comparison.after.tool_calls, null, 2)],
    ["Ticket/data state", JSON.stringify(comparison.before.final_state, null, 2), JSON.stringify(comparison.after.final_state, null, 2)],
    ["Agent answer", comparison.before.output, comparison.after.output],
  ];
  rows.forEach(([label, left, right]) => {
    const row = element("tr", "", "");
    row.append(element("th", "", label), element("td", "", left ?? "not available"), element("td", "", right ?? "not available"));
    body.append(row);
  });
  table.append(head, body);
  root.append(table);
}

async function loadRun(runId) {
  const record = await api(`/v1/runs/${encodeURIComponent(runId)}`);
  state.selectedRunId = runId;
  renderRun(record);
}

function subscribe(runId) {
  if (state.source) state.source.close();
  state.activeRunId = runId;
  byId("run-id").textContent = runId;
  setRunState("running");
  clear(byId("trace-list"));
  state.source = new EventSource(`/v1/runs/${encodeURIComponent(runId)}/events`);
  ["run.started", "model.started", "model.completed", "tool.started", "tool.completed", "database.observed", "run.completed", "result.saved", "run.failed"].forEach((name) => {
    state.source.addEventListener(name, async (event) => {
      let payload = {};
      try { payload = JSON.parse(event.data); } catch (_) { payload = { error: "Invalid event data" }; }
      renderEvent(name, payload);
      if (["result.saved", "run.failed"].includes(name)) {
        state.source.close();
        state.source = null;
        state.activeRunId = null;
        await loadRun(runId);
      }
    });
  });
  state.source.onerror = () => {
    if (state.source) {
      state.source.close();
      state.source = null;
      pollRun(runId).catch((error) => notify(error.message));
    }
  };
}

async function pollRun(runId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const record = await api(`/v1/runs/${encodeURIComponent(runId)}`);
    if (["completed", "failed", "cancelled"].includes(record.status)) {
      state.activeRunId = null;
      await loadRun(runId);
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  state.activeRunId = null;
  setRunState("failed");
  notify("The run did not finish within the classroom wait limit.");
}

async function submitRun(messageOverride = null) {
  const message = messageOverride ?? byId("message").value.trim();
  if (!message) return notify("Enter a request first.");
  try {
    const accepted = await api("/v1/runs", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    state.selectedRunId = accepted.run_id;
    subscribe(accepted.run_id);
    await renderHistory();
  } catch (error) {
    notify(error.message);
  }
}

async function initialize() {
  try {
    const readiness = await api("/health/ready");
    byId("health-label").textContent = readiness.model_configured ? `Ready · ${readiness.model}` : "Agent ready · API key not configured";
    if (readiness.model_configured) byId("health-dot").classList.add("ready");
    await renderHistory();
  } catch (error) {
    byId("health-label").textContent = "Local app could not load";
    notify(error.message);
  }
}

byId("run-button").addEventListener("click", () => submitRun());
byId("compare-before").addEventListener("change", updateCompareButton);
byId("compare-after").addEventListener("change", updateCompareButton);
byId("compare-button").addEventListener("click", () => compareAttempts().catch((error) => notify(error.message)));
byId("cancel-button").addEventListener("click", async () => {
  if (!state.activeRunId) return;
  try { await api(`/v1/runs/${encodeURIComponent(state.activeRunId)}/cancel`, { method: "POST" }); }
  catch (error) { notify(error.message); }
});
byId("demo-profile").addEventListener("click", () => {
  byId("message").value = "Show my customer profile.";
});
byId("demo-ticket").addEventListener("click", () => {
  byId("message").value = "Please create one support ticket. My test parcel arrived with damaged packaging.";
});
byId("replay-button").addEventListener("click", async () => {
  if (!state.selectedRunId) return;
  try {
    const accepted = await api(`/v1/runs/${encodeURIComponent(state.selectedRunId)}/replay`, { method: "POST" });
    state.selectedRunId = accepted.run_id;
    subscribe(accepted.run_id);
  } catch (error) { notify(error.message); }
});
byId("export-button").addEventListener("click", async () => {
  if (!state.selectedRunId) return;
  try {
    const evidence = await api(`/v1/runs/${encodeURIComponent(state.selectedRunId)}/export`);
    evidence.rca = Object.fromEntries([...document.querySelectorAll("[data-rca]")].map((field) => [field.dataset.rca, field.value]));
    const blob = new Blob([JSON.stringify(evidence, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = element("a", "", "");
    link.href = url;
    link.download = `module16-evidence-${state.selectedRunId.slice(0, 8)}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notify(error.message); }
});

initialize();
