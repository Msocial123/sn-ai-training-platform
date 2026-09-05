const API = {
  nowAssist: "/api/now-assist",
  knowledge: "/api/knowledge",
  predictive: "/api/predictive",
  passwordReset: "/api/password-reset",
  virtualAgent: "/api/virtual-agent",
  processMining: "/api/process-mining",
  incidentWatcher: "/api/incident-watcher",
  infraMonitor: "/api/infra-monitor",
};

const panelsEl = document.getElementById("panels");
const tabsEl = document.getElementById("tabs");

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function pill(level) {
  const cls = (level || "").toLowerCase();
  return `<span class="pill ${cls}">${level}</span>`;
}

// ---------------------------------------------------------------- Dashboard

function timeAgo(ts) {
  if (!ts) return "never";
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

async function renderDashboard() {
  const [iw, im, ap] = await Promise.all([
    api(`${API.incidentWatcher}/feed`),
    api(`${API.infraMonitor}/dashboard`),
    api(`${API.infraMonitor}/proposals`),
  ]);
  const totalIncidents = iw.stats.processed + im.stats.incidents_created;
  const byPriority = {};
  iw.feed.filter(i => i.status === "processed").forEach(i => { byPriority[i.priority_level || "P4"] = (byPriority[i.priority_level || "P4"] || 0) + 1; });

  const recentAlerts = ap.proposals.slice(0, 12);

  return `
    <div class="card">
      <h2>Incident Totals</h2>
      <p class="desc">No need to check ServiceNow directly for a count — this is pulled live, every load.</p>
      <div class="stat-grid">
        <div class="stat-card"><div class="num">${totalIncidents}</div><div class="label">Total incidents processed</div></div>
        <div class="stat-card"><div class="num">${im.active_problems}</div><div class="label">Active infra problems tracked</div></div>
        <div class="stat-card"><div class="num">${im.stats.recurrences_deduped}</div><div class="label">Recurrences deduplicated (noise reduced)</div></div>
        <div class="stat-card"><div class="num">${ap.pending_count}</div><div class="label">Pending approvals</div></div>
      </div>
    </div>
    <div class="card">
      <h2>By Priority</h2>
      <div style="display:flex;gap:20px;flex-wrap:wrap;">
        ${["P1", "P2", "P3", "P4"].map(p => `<div>${priorityPill(p)} <strong>${byPriority[p] || 0}</strong></div>`).join("")}
      </div>
    </div>
    <div class="card">
      <h2>Recent Alerts</h2>
      <p class="desc">Every problem Infra Monitor has detected — approved, rejected, or still pending.</p>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Problem</th><th>Location</th><th>Status</th><th>Occurrences</th><th>When</th></tr></thead>
          <tbody>
            ${recentAlerts.length === 0 ? `<tr><td colspan="5">No alerts yet.</td></tr>` : recentAlerts.map(p => `
              <tr>
                <td>${p.problem_type}</td>
                <td><code>${p.namespace}/${p.app_label}</code></td>
                <td>${p.status === "pending" ? `<span class="pill p2">pending</span>` : p.status}</td>
                <td>${p.occurrence_count}</td>
                <td>${timeAgo(p.created_at)}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h2>Pipeline Health</h2>
      <table>
        <tr><th>Loop</th><th>Polls run</th><th>Last poll</th><th>Errors</th></tr>
        <tr><td>Incident Watcher (ServiceNow sync)</td><td>${iw.stats.polls}</td><td>${timeAgo(iw.stats.last_poll_at)}</td><td>${iw.stats.errors}</td></tr>
        <tr><td>Infra Monitor (EKS detection)</td><td>${im.stats.polls}</td><td>${timeAgo(im.stats.last_poll_at)}</td><td>${im.stats.errors}</td></tr>
      </table>
      <p class="desc" style="margin-top:12px;">ServiceNow: ${im.servicenow_configured ? (im.servicenow_last_error ? `configured but currently failing (${im.servicenow_last_error})` : "connected") : "not connected (running on sample data)"}</p>
    </div>
  `;
}

// ---------------------------------------------------------------- Approvals

async function renderApprovals() {
  return `
    <div class="card">
      <h2>Human-in-the-Loop Approvals</h2>
      <p class="desc">Infra Monitor never touches the cluster on its own — every remediation is proposed here first and only executes once a human approves it.</p>
      <div id="ap-pending"><p class="desc">Loading…</p></div>
    </div>
    <div class="card">
      <h2>Recent Decisions</h2>
      <div id="ap-resolved"><p class="desc">Loading…</p></div>
    </div>
  `;
}

function wireApprovals() {
  async function refresh() {
    try {
      const r = await api(`${API.infraMonitor}/proposals`);
      const pendingEl = document.getElementById("ap-pending");
      const resolvedEl = document.getElementById("ap-resolved");
      if (!pendingEl) return; // navigated away

      const pending = r.proposals.filter(p => p.status === "pending");
      const resolved = r.proposals.filter(p => p.status !== "pending").slice(0, 15);

      pendingEl.innerHTML = pending.length === 0
        ? `<p class="desc">Nothing pending right now.</p>`
        : pending.map(p => `
          <div class="result-box" style="margin-bottom:12px;">
            <strong>${p.problem_type}</strong> in <code>${p.namespace}/${p.app_label}</code> ${pill(p.risk === "low" ? "Low" : p.risk)} — seen ${p.occurrence_count}x
            <div style="margin:8px 0;">${p.detail}</div>
            <div style="margin:8px 0;"><em>Proposed action:</em> ${p.action_description}</div>
            ${p.incident_number ? `<div style="margin:8px 0;">ServiceNow: <strong>${p.incident_number}</strong></div>` : ""}
            <button class="primary" data-approve="${p.id}">Approve</button>
            <button class="primary" data-reject="${p.id}" style="background:#c0362c;">Reject</button>
          </div>`).join("");

      resolvedEl.innerHTML = resolved.length === 0
        ? `<p class="desc">No decisions yet.</p>`
        : `<table><tr><th>Problem</th><th>Status</th><th>By</th><th>When</th></tr>${
            resolved.map(p => `<tr><td>${p.problem_type} — ${p.namespace}/${p.app_label}</td><td>${p.status}</td><td>${p.resolved_by || "-"}</td><td>${timeAgo(p.resolved_at)}</td></tr>`).join("")
          }</table>`;

      pendingEl.querySelectorAll("[data-approve]").forEach(btn => btn.addEventListener("click", () => decide(btn.dataset.approve, "approve")));
      pendingEl.querySelectorAll("[data-reject]").forEach(btn => btn.addEventListener("click", () => decide(btn.dataset.reject, "reject")));
    } catch (err) {
      const el = document.getElementById("ap-pending");
      if (el) el.textContent = "Error: " + err.message;
    }
  }

  async function decide(id, action) {
    const actor = prompt(`Your name/id (for the audit trail on this ${action}):`, "trainer");
    if (actor === null) return; // cancelled
    try {
      await api(`${API.infraMonitor}/proposals/${id}/${action}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: actor || "unknown" }),
      });
      loadBadges();
      refresh();
    } catch (err) { alert("Error: " + err.message); }
  }

  refresh();
  const interval = setInterval(refresh, 8000);
  // clean up when navigating away
  const observer = new MutationObserver(() => {
    if (!document.getElementById("ap-pending")) { clearInterval(interval); observer.disconnect(); }
  });
  observer.observe(panelsEl, { childList: true });
}

// ---------------------------------------------------------------- Overview

async function renderOverview() {
  return `
    <div class="card">
      <h2>What this is</h2>
      <p class="desc">A working microservice for each AI agent covered in the training, backed by a shared sample ticket
      dataset. Each agent runs against local sample data today, and will start using live data the moment
      ServiceNow OAuth credentials and an LLM API key are configured as Kubernetes Secrets — no code changes needed.</p>
      <table>
        <tr><th>Agent</th><th>Session</th><th>What it does</th></tr>
        <tr><td>Now Assist</td><td>3</td><td>Case summarization + solution recommendation</td></tr>
        <tr><td>Knowledge Article</td><td>5</td><td>Auto-draft KB articles + duplicate detection</td></tr>
        <tr><td>Predictive Intelligence</td><td>6</td><td>Auto-categorization + priority prediction</td></tr>
        <tr><td>Password Reset</td><td>7</td><td>End-to-end automated reset workflow</td></tr>
        <tr><td>Virtual Agent</td><td>8</td><td>Chat-based ticket status &amp; reset trigger</td></tr>
        <tr><td>Process Mining</td><td>8</td><td>Bottleneck discovery from event logs</td></tr>
      </table>
    </div>
    <div class="card">
      <h2>The agentic AIOps loop (Dashboard + Approvals tabs)</h2>
      <p class="desc">Infra Monitor continuously watches this cluster's own infrastructure for real problems (pod crashes),
      correlates repeated occurrences of the SAME problem into one tracked issue instead of one alert per raw event
      (deduplication / noise reduction), gets an LLM narrative summary, opens a real ServiceNow incident, and proposes
      a fix — but never executes anything on its own. Check the <strong>Approvals</strong> tab to see pending
      remediations and approve or reject them; check <strong>Dashboard</strong> for live totals without needing to
      open ServiceNow directly. The header badge above shows a live pending-approvals count from any tab.</p>
    </div>
  `;
}

// ---------------------------------------------------------------- Live Monitor

let liveMonitorInterval = null;

async function renderLiveMonitor() {
  return `
    <div class="card">
      <h2>Live Incident Monitor</h2>
      <p class="desc">This is the actually-automatic part: a background loop polls for new/open incidents every ~15s,
      summarizes each one via Now Assist with no human involved, and (once ServiceNow is connected) writes the
      result back as a work note. Everything below happened on its own — nothing here was manually triggered.</p>
      <div id="lm-stats" class="result-box empty">Loading…</div>
    </div>
    <div class="card">
      <h2>Simulate a New Incident</h2>
      <p class="desc">Queues a new incident. It is <em>not</em> processed immediately — watch the feed below update on its own within ~15s, proving the loop is real.</p>
      <label for="lm-sim-text">Short description</label>
      <input type="text" id="lm-sim-text" placeholder="e.g. Cannot access shared drive after VPN reconnect" />
      <button class="primary" id="lm-sim-run">Queue Incident</button>
      <div class="result-box empty" id="lm-sim-result">Not queued yet.</div>
    </div>
    <div class="card">
      <h2>Auto-Processed Feed</h2>
      <div id="lm-feed"><p class="desc">Loading…</p></div>
    </div>
  `;
}

function wireLiveMonitor() {
  async function refresh() {
    try {
      const r = await api(`${API.incidentWatcher}/feed`);
      const s = document.getElementById("lm-stats");
      if (s) {
        s.classList.remove("empty");
        const dataSource = r.servicenow_configured
          ? (r.servicenow_last_error ? `ServiceNow configured but failing (${r.servicenow_last_error}) — falling back to sample data` : "live ServiceNow")
          : "sample dataset + simulated incidents";
        s.innerHTML = `Polls run: ${r.stats.polls} · Auto-processed: ${r.stats.processed} · Errors: ${r.stats.errors} · Data source: ${dataSource}`;
      }
      const feedEl = document.getElementById("lm-feed");
      if (!feedEl) return; // user navigated away
      if (r.feed.length === 0) {
        feedEl.innerHTML = `<p class="desc">No new incidents processed yet — all sample incidents are already caught up. Try "Simulate a New Incident" above.</p>`;
        return;
      }
      feedEl.innerHTML = r.feed.map(item => `
        <div class="result-box" style="margin-bottom:10px;">
          <strong>${item.incident_id}</strong> — ${item.short_description}
          ${item.status === "error"
            ? `\n<span style="color:#c0362c">Error: ${item.error}</span>`
            : `\nSummary: ${item.summary}\nRecommended: ${item.recommended_solution}\n${item.written_back_to_servicenow ? "✅ Written back to ServiceNow" : "(not written back — ServiceNow not connected)"} · processed in ${item.processing_seconds}s`}
        </div>`).join("");
    } catch (err) {
      const feedEl = document.getElementById("lm-feed");
      if (feedEl) feedEl.textContent = "Error: " + err.message;
    }
  }

  refresh();
  liveMonitorInterval = setInterval(refresh, 5000);

  document.getElementById("lm-sim-run").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Queueing…";
    const short_description = document.getElementById("lm-sim-text").value || "Simulated incident from the Live Monitor tab";
    const box = document.getElementById("lm-sim-result");
    try {
      const r = await api(`${API.incidentWatcher}/simulate-incident`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ short_description }) });
      box.classList.remove("empty");
      box.textContent = `Queued as ${r.queued_incident_id}. Watch the feed below — it'll be picked up within ~${r.will_be_picked_up_within_seconds}s.`;
    } catch (err) { box.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Queue Incident";
  });
}

// ---------------------------------------------------------------- Now Assist

let nowAssistInterval = null;

function priorityPill(level) {
  const cls = (level || "p4").toLowerCase();
  return `<span class="pill ${cls}">${level || "P4"}</span>`;
}

async function renderNowAssist() {
  const tickets = await api(`${API.nowAssist}/tickets`);
  const options = tickets.map(t => `<option value="${t.id}">${t.id} — ${t.short_description}</option>`).join("");
  return `
    <div class="card">
      <h2>Now Assist — Case Summarization &amp; Recommendation</h2>
      <p class="desc">Pick an incident to run the agent on demand. The agent summarizes it and recommends a resolution based on similar closed tickets.</p>
      <label for="na-ticket">Incident</label>
      <select id="na-ticket">${options}</select>
      <button class="primary" id="na-run">Summarize &amp; Recommend</button>
      <div class="result-box empty" id="na-result">No run yet.</div>
    </div>
    <div class="card">
      <h2>Every Incident — Auto-Summarized, Categorized &amp; Prioritized</h2>
      <p class="desc">This is the live command center: whenever ANY incident occurs — from live ServiceNow, a manual simulation, or Infra Monitor's own detections — it lands here automatically. Now Assist provides the summary + recommended remedy; the Predictive Intelligence agent provides category + P1–P4 priority. Two agents, one pipeline, no manual step required. Refreshes every 6s.</p>
      <div id="na-all-stats" class="result-box empty" style="margin-bottom:16px;">Loading…</div>
      <div class="table-scroll">
        <table id="na-all-table">
          <thead><tr><th>Priority</th><th>ID</th><th>Category</th><th>Incident</th><th>Summary</th><th>Recommended Remedy</th><th>Source</th></tr></thead>
          <tbody id="na-all-tbody"><tr><td colspan="7">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>
  `;
}

function wireNowAssist() {
  document.getElementById("na-run").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Running…";
    const ticket_id = document.getElementById("na-ticket").value;
    const box = document.getElementById("na-result");
    try {
      // use_fast_model: true -- this is a person watching a spinner, and
      // the self-hosted LLM has exactly one CPU inference slot shared
      // with Incident Watcher's background summarization. The slow model
      // measurably lost that contention (timed out, fell back to a
      // template) even with a reduced token budget; the fast model is
      // what actually comes back with real content under real load.
      const r = await api(`${API.nowAssist}/summarize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticket_id, use_fast_model: true }) });
      box.classList.remove("empty");
      box.innerHTML = `<strong>Summary</strong> (${r.source})\n${r.summary}\n\n<strong>Recommended solution</strong> (confidence ${r.confidence}, based on ${r.based_on || "n/a"})\n${r.recommended_solution}`;
    } catch (err) { box.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Summarize & Recommend";
  });

  let seenIds = new Set();
  async function refreshAll() {
    const tbody = document.getElementById("na-all-tbody");
    const statsEl = document.getElementById("na-all-stats");
    if (!tbody) return; // navigated away
    try {
      const r = await api(`${API.incidentWatcher}/feed`);
      const items = r.feed.filter(i => i.status === "processed");
      const byPriority = {};
      items.forEach(i => { byPriority[i.priority_level || "P4"] = (byPriority[i.priority_level || "P4"] || 0) + 1; });
      statsEl.classList.remove("empty");
      statsEl.innerHTML = `<strong>${items.length}</strong> incidents processed — ` +
        ["P1", "P2", "P3", "P4"].map(p => `${priorityPill(p)} ${byPriority[p] || 0}`).join("  ");

      tbody.innerHTML = items.length === 0
        ? `<tr><td colspan="7">No incidents processed yet.</td></tr>`
        : items.map(i => {
            const isFresh = !seenIds.has(i.incident_id + i.processed_at);
            return `<tr class="${isFresh ? "fresh" : ""}">
              <td>${priorityPill(i.priority_level)}</td>
              <td><code>${i.incident_id}</code></td>
              <td>${i.category || "—"}</td>
              <td>${i.short_description}</td>
              <td>${i.summary || "—"}</td>
              <td>${i.recommended_solution || "—"}</td>
              <td>${i.source}${i.written_back_to_servicenow ? " ✅" : ""}</td>
            </tr>`;
          }).join("");
      items.forEach(i => seenIds.add(i.incident_id + i.processed_at));
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7">Error: ${err.message}</td></tr>`;
    }
  }
  refreshAll();
  nowAssistInterval = setInterval(refreshAll, 6000);
}

// ---------------------------------------------------------------- Knowledge Article

async function renderKnowledge() {
  const kb = await api(`${API.knowledge}/kb-library`);
  const options = kb.map(t => `<option value="${t.id}">${t.id} — ${t.title}</option>`).join("");
  return `
    <div class="card">
      <h2>Auto-Draft Knowledge Article</h2>
      <p class="desc">Generate a KB article from a resolved incident's resolution notes.</p>
      <label for="kb-ticket">Resolved incident</label>
      <select id="kb-ticket">${options}</select>
      <button class="primary" id="kb-draft">Draft Article</button>
      <div class="result-box empty" id="kb-result">No draft yet.</div>
    </div>
    <div class="card">
      <h2>Duplicate Detection</h2>
      <p class="desc">Paste a proposed article/incident title to check against the existing KB library.</p>
      <label for="kb-dup-text">Text to check</label>
      <textarea id="kb-dup-text" placeholder="e.g. Employee cannot connect to VPN after changing password"></textarea>
      <button class="primary" id="kb-dup-run">Check for Duplicates</button>
      <div class="result-box empty" id="kb-dup-result">No check yet.</div>
    </div>
  `;
}
function wireKnowledge() {
  document.getElementById("kb-draft").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Drafting…";
    const ticket_id = document.getElementById("kb-ticket").value;
    const box = document.getElementById("kb-result");
    try {
      const r = await api(`${API.knowledge}/draft-article`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticket_id }) });
      box.classList.remove("empty");
      const a = r.article;
      box.innerHTML = a.body
        ? `<strong>${a.title}</strong>\n\n${a.body}`
        : `<strong>${a.title}</strong>\n\n<em>Symptoms:</em> ${a.symptoms}\n\n<em>Root cause & resolution:</em> ${a.root_cause_and_resolution}\n\n<small>${a.llm_note || ""}</small>`;
    } catch (err) { box.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Draft Article";
  });
  document.getElementById("kb-dup-run").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Checking…";
    const text = document.getElementById("kb-dup-text").value;
    const box = document.getElementById("kb-dup-result");
    try {
      const r = await api(`${API.knowledge}/duplicate-check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      box.classList.remove("empty");
      const matches = r.matches.map(m => `  • ${m.id} — ${m.title} (similarity ${m.similarity})`).join("\n");
      box.textContent = `Likely duplicate: ${r.likely_duplicate ? "YES" : "no"}\n\nTop matches:\n${matches}`;
    } catch (err) { box.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Check for Duplicates";
  });
}

// ---------------------------------------------------------------- Predictive Intelligence

async function renderPredictive() {
  return `
    <div class="card">
      <h2>Auto-Categorization &amp; Priority Prediction</h2>
      <p class="desc">Type a short description as an agent might type it into a new incident.</p>
      <label for="pi-text">Short description</label>
      <input type="text" id="pi-text" placeholder="e.g. Unable to access corporate email after password reset" />
      <button class="primary" id="pi-run">Predict</button>
      <div class="result-box empty" id="pi-result">No prediction yet.</div>
    </div>
    <div class="card">
      <h2>Live Demo — Batch Prediction</h2>
      <p class="desc">Runs the classifier over every sample ticket at once.</p>
      <button class="primary" id="pi-batch">Run Batch</button>
      <div id="pi-batch-result"></div>
    </div>
  `;
}
function wirePredictive() {
  document.getElementById("pi-run").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Predicting…";
    const short_description = document.getElementById("pi-text").value;
    const box = document.getElementById("pi-result");
    try {
      const r = await api(`${API.predictive}/predict`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ short_description }) });
      const p = r.prediction;
      box.classList.remove("empty");
      box.innerHTML = `Category: <strong>${p.category} / ${p.subcategory}</strong>\nPriority: ${pill(p.priority)} ${priorityPill(p.priority_level)}\nAssignment group: <strong>${p.assignment_group}</strong>\nConfidence: ${p.confidence}`;
    } catch (err) { box.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Predict";
  });
  document.getElementById("pi-batch").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Running…";
    const target = document.getElementById("pi-batch-result");
    try {
      const rows = await api(`${API.predictive}/predict-batch`);
      target.innerHTML = `<table><tr><th>Ticket</th><th>Category</th><th>Priority</th><th>Group</th><th>Conf.</th></tr>${
        rows.map(r => `<tr><td>${r.short_description}</td><td>${r.prediction.category}</td><td>${pill(r.prediction.priority)} ${priorityPill(r.prediction.priority_level)}</td><td>${r.prediction.assignment_group}</td><td>${r.prediction.confidence}</td></tr>`).join("")
      }</table>`;
    } catch (err) { target.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Run Batch";
  });
}

// ---------------------------------------------------------------- Password Reset

async function renderPasswordReset() {
  return `
    <div class="card">
      <h2>Automated Password-Reset Agent</h2>
      <p class="desc">Simulates the full Flow Designer → Integration Hub/RPA → Approval → Notification workflow. Try username <code>admin</code> to see the approval branch.</p>
      <label for="pr-username">Username</label>
      <input type="text" id="pr-username" placeholder="e.g. jsmith" />
      <button class="primary" id="pr-run">Start Reset Workflow</button>
      <div id="pr-result"></div>
    </div>
  `;
}
function wirePasswordReset() {
  document.getElementById("pr-run").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Running…";
    const username = document.getElementById("pr-username").value || "jsmith";
    const target = document.getElementById("pr-result");
    try {
      const r = await api(`${API.passwordReset}/reset-request`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username }) });
      target.innerHTML = r.log.map(s => `
        <div class="workflow-step">
          <div class="step-dot"></div>
          <div><div class="step-actor">${s.actor}</div><strong>${s.step}</strong><div>${s.detail}</div></div>
        </div>`).join("");
    } catch (err) { target.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Start Reset Workflow";
  });
}

// ---------------------------------------------------------------- Virtual Agent

async function renderVirtualAgent() {
  return `
    <div class="card">
      <h2>Virtual Agent</h2>
      <p class="desc">Try: "what's the status of INC0010001?", "I need a password reset", or "agent" to escalate.</p>
      <div class="chat-log" id="va-log"></div>
      <div class="chat-input-row">
        <input type="text" id="va-input" placeholder="Type a message…" />
        <button class="primary" id="va-send">Send</button>
      </div>
    </div>
  `;
}
function wireVirtualAgent() {
  const log = document.getElementById("va-log");
  const input = document.getElementById("va-input");
  const sessionId = "session-" + Math.random().toString(36).slice(2, 8);

  function addMsg(text, who) {
    const div = document.createElement("div");
    div.className = `chat-msg ${who}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }
  addMsg("Hi! I can check a ticket's status or start a password reset. What do you need?", "bot");

  async function send() {
    const message = input.value.trim();
    if (!message) return;
    addMsg(message, "user");
    input.value = "";
    try {
      const r = await api(`${API.virtualAgent}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id: sessionId }) });
      addMsg(r.reply, "bot");
    } catch (err) { addMsg("Error: " + err.message, "bot"); }
  }
  document.getElementById("va-send").addEventListener("click", send);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
}

// ---------------------------------------------------------------- Process Mining

async function renderProcessMining() {
  return `
    <div class="card">
      <h2>Process Mining — Bottleneck Report</h2>
      <p class="desc">Analyzes step-by-step event timestamps across recent cases to find where time is actually being lost.</p>
      <button class="primary" id="pm-run">Run Analysis</button>
      <div id="pm-result"></div>
    </div>
  `;
}
function wireProcessMining() {
  document.getElementById("pm-run").addEventListener("click", async (e) => {
    const btn = e.target; btn.disabled = true; btn.textContent = "Analyzing…";
    const target = document.getElementById("pm-result");
    try {
      const r = await api(`${API.processMining}/bottleneck-report`);
      const bn = r.bottleneck;
      target.innerHTML = `
        <div class="result-box">Analyzed ${r.cases_analyzed} cases.\n\n<strong>Bottleneck: ${bn.transition}</strong> — avg ${bn.avg_minutes} min (max ${bn.max_minutes} min, n=${bn.sample_size})</div>
        <table><tr><th>Transition</th><th>Avg (min)</th><th>Max (min)</th><th>Cases</th></tr>${
          r.all_transitions.map(t => `<tr><td>${t.transition}</td><td>${t.avg_minutes}</td><td>${t.max_minutes}</td><td>${t.sample_size}</td></tr>`).join("")
        }</table>`;
    } catch (err) { target.textContent = "Error: " + err.message; }
    btn.disabled = false; btn.textContent = "Run Analysis";
  });
}

// ---------------------------------------------------------------- Router

const TABS = {
  overview: { render: renderOverview, wire: null },
  dashboard: { render: renderDashboard, wire: null },
  approvals: { render: renderApprovals, wire: wireApprovals },
  "live-monitor": { render: renderLiveMonitor, wire: wireLiveMonitor },
  "now-assist": { render: renderNowAssist, wire: wireNowAssist },
  knowledge: { render: renderKnowledge, wire: wireKnowledge },
  predictive: { render: renderPredictive, wire: wirePredictive },
  "password-reset": { render: renderPasswordReset, wire: wirePasswordReset },
  "virtual-agent": { render: renderVirtualAgent, wire: wireVirtualAgent },
  "process-mining": { render: renderProcessMining, wire: wireProcessMining },
};

async function showTab(name) {
  if (liveMonitorInterval) { clearInterval(liveMonitorInterval); liveMonitorInterval = null; }
  if (nowAssistInterval) { clearInterval(nowAssistInterval); nowAssistInterval = null; }
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  panelsEl.innerHTML = `<div class="card"><p class="desc">Loading…</p></div>`;
  try {
    const tab = TABS[name];
    panelsEl.innerHTML = await tab.render();
    if (tab.wire) tab.wire();
  } catch (err) {
    panelsEl.innerHTML = `<div class="card"><h2>Error</h2><p>${err.message}</p></div>`;
  }
}

tabsEl.addEventListener("click", (e) => {
  if (e.target.classList.contains("tab")) showTab(e.target.dataset.tab);
});

// Status badges: ping each service's /healthz to show connection state,
// PLUS a live pending-approvals count -- visible from every tab, not just
// the Approvals tab, so activity is never invisible.
async function loadBadges() {
  const el = document.getElementById("status-badges");
  try {
    const [health, proposals] = await Promise.all([
      api(`${API.nowAssist}/healthz`),
      api(`${API.infraMonitor}/proposals`).catch(() => ({ pending_count: 0 })),
    ]);
    const pending = proposals.pending_count || 0;
    el.innerHTML = `
      ${pending > 0 ? `<span class="badge pending" id="badge-pending">⚠ ${pending} pending approval${pending > 1 ? "s" : ""}</span>` : ""}
      <span class="badge ${health.servicenow_configured ? "ok" : "off"}">ServiceNow ${health.servicenow_configured ? "connected" : "not connected"}</span>
      <span class="badge ${health.llm_configured ? "ok" : "off"}">LLM ${health.llm_configured ? "connected" : "not connected"}</span>
    `;
    const badge = document.getElementById("badge-pending");
    if (badge) badge.addEventListener("click", () => showTab("approvals"));
  } catch { el.innerHTML = `<span class="badge off">Status unavailable</span>`; }
}

loadBadges();
setInterval(loadBadges, 10000); // keep the pending-approvals count fresh no matter which tab you're on
showTab("overview");
