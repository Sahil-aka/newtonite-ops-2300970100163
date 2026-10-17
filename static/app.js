const state = {
  token: sessionStorage.getItem("newtonite_token"),
  user: null,
  teams: [],
  members: [],
  teamId: "",
  role: "viewer",
  queue: "all",
  items: [],
  nextCursor: null,
  searchTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const safe = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const humanize = (value = "") => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const initials = (value = "?") => value.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && state.token) {
    signOut();
    throw new Error("Your session expired. Please sign in again.");
  }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const detail = payload?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : "The request could not be completed.");
  }
  return payload;
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function showLogin(message = "") {
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
  $("#login-form").hidden = false;
  $("#signup-form").hidden = true;
  $("#show-signup").closest(".login-hint").hidden = false;
  $("#login-view h1").textContent = "Welcome back";
  $("#login-view > .login-card > .muted").textContent = "Sign in to see what needs your team's attention.";
  $("#login-error").textContent = message;
}

function showSignup() {
  $("#login-form").hidden = true;
  $("#signup-form").hidden = false;
  $("#show-signup").closest(".login-hint").hidden = true;
  $("#login-view h1").textContent = "Create your account";
  $("#login-view > .login-card > .muted").textContent = "Join the Operations workspace and get started.";
  $("#signup-error").textContent = "";
}

function showApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
}

function signOut() {
  sessionStorage.removeItem("newtonite_token");
  state.token = null;
  state.user = null;
  showLogin();
}

function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toast.classList.remove("show"), 3200);
}

async function startApp() {
  if (!state.token) return showLogin();
  try {
    state.user = await api("/auth/me");
    state.teams = await api("/teams");
    if (!state.teams.length) {
      showApp();
      $("#team-picker").innerHTML = '<option value="">No teams available</option>';
      $("#item-rows").innerHTML = '<tr><td colspan="6" class="team-empty">Your account is not a member of any team yet.</td></tr>';
      return;
    }
    const existing = state.teams.find((team) => team.team_id === state.teamId);
    state.teamId = existing?.team_id || state.teams[0].team_id;
    state.role = state.teams.find((team) => team.team_id === state.teamId)?.role || "viewer";
    await loadTeamMembers();
    renderTeams();
    renderUser();
    showApp();
    await loadItems();
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) showLogin(error.message);
  }
}

async function loadTeamMembers() {
  state.members = await api(`/teams/${state.teamId}/members`);
}

function renderTeams() {
  $("#team-picker").innerHTML = state.teams.map((team) =>
    `<option value="${safe(team.team_id)}" ${team.team_id === state.teamId ? "selected" : ""}>${safe(team.team_name)} · ${safe(humanize(team.role))}</option>`,
  ).join("");
  const team = state.teams.find((entry) => entry.team_id === state.teamId);
  $("#current-team-name").textContent = team?.team_name || "Team";
  $("#user-role").textContent = humanize(team?.role || "member");
  $("#new-item-button").hidden = team?.role === "viewer";
}

function renderUser() {
  const name = state.user?.display_name || state.user?.email || "Team member";
  $("#user-name").textContent = name;
  $("#user-avatar").textContent = initials(name);
  $("#topbar-avatar").textContent = initials(name);
  const date = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date());
  $("#today-label").textContent = `${date.toUpperCase()} · YOUR TEAM WORKSPACE`;
}

function queryForList(cursor = null) {
  const params = new URLSearchParams({ team_id: state.teamId, limit: "25" });
  const status = $("#status-filter").value;
  const priority = $("#priority-filter").value;
  const query = $("#search-input").value.trim();
  if (status) params.set("status", status);
  if (priority) params.set("priority", priority);
  if (query) params.set("q", query);
  if (state.queue === "mine") params.set("assignee_id", state.user.id);
  if (state.queue === "urgent") {
    params.set("priority", "urgent");
    params.set("unassigned", "true");
  }
  if (state.queue === "approval") params.set("status", "awaiting_approval");
  if (cursor) params.set("cursor", cursor);
  return params.toString();
}

async function loadItems({ append = false } = {}) {
  if (!state.teamId) return;
  const tbody = $("#item-rows");
  if (!append) {
    tbody.innerHTML = '<tr><td colspan="6" class="team-empty">Loading work items…</td></tr>';
    state.items = [];
  }
  try {
    const query = queryForList(append ? state.nextCursor : null);
    const page = await api(`/items?${query}`);
    state.items = append ? [...state.items, ...page.items] : page.items;
    state.nextCursor = page.next_cursor;
    renderItems();
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="6" class="team-empty">${safe(error.message)}</td></tr>`;
    notify(error.message);
  }
}

function updateListTitle() {
  const titles = { all: "All work items", mine: "Assigned to me", urgent: "Unassigned urgent", approval: "Awaiting approval" };
  $("#list-title").textContent = titles[state.queue];
}

function renderItems() {
  const rows = $("#item-rows");
  const items = state.items;
  const mine = items.filter((item) => item.assignee_id === state.user.id).length;
  const urgent = items.filter((item) => item.priority === "urgent" && !item.assignee_id).length;
  const approval = items.filter((item) => item.status === "awaiting_approval").length;
  $("#visible-count").textContent = items.length;
  $("#urgent-count").textContent = urgent;
  $("#approval-count").textContent = approval;
  $("#mine-count").textContent = mine;
  $("#result-badge").textContent = `${items.length} ${items.length === 1 ? "item" : "items"}`;
  $("#list-caption").textContent = `Showing ${items.length} item${items.length === 1 ? "" : "s"} on this page`;
  $("#empty-state").hidden = items.length > 0;
  rows.innerHTML = items.map((item) => {
    const assigneeMember = state.members.find((member) => member.id === item.assignee_id);
    const assignee = assigneeMember?.display_name || "Unassigned";
    const initialsText = assigneeMember ? initials(assigneeMember.display_name) : "–";
    const updated = item.updated_at ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(item.updated_at)) : "—";
    const itemIcon = { incident: "ϟ", payment: "$", compliance: "✓", customer_issue: "◌", task: "▤" }[item.item_type] || "▤";
    return `<tr>
      <td><div class="item-cell"><span class="type-mark">${itemIcon}</span><div><div class="item-title">${safe(item.title)}</div><div class="item-sub">${safe(humanize(item.item_type))} · v${item.version}</div></div></div></td>
      <td><span class="priority-pill priority-${safe(item.priority)}">${safe(humanize(item.priority))}</span></td>
      <td><span class="status-pill status-${safe(item.status)}">${safe(humanize(item.status))}</span></td>
      <td><span class="assignee ${item.assignee_id ? "" : "assignee-none"}">${item.assignee_id ? `<span class="assignee-dot">${safe(initialsText)}</span>` : ""}${safe(assignee)}</span></td>
      <td><span class="updated-text">${safe(updated)}</span></td>
      <td><button class="row-open" data-open-item="${safe(item.id)}" aria-label="Open ${safe(item.title)}">↗</button></td>
    </tr>`;
  }).join("");
  $("#load-more").hidden = !state.nextCursor;
  updateListTitle();
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function eventDescription(event) {
  const newValue = event.new_value || {};
  const oldValue = event.old_value || {};
  if (event.event_type === "created") return `Created “${newValue.title || "work item"}”.`;
  if (event.event_type === "claimed") return "Claimed this work item.";
  if (event.event_type === "assigned") {
    const previous = state.members.find((member) => member.id === oldValue.assignee_id)?.display_name || "Unassigned";
    const next = state.members.find((member) => member.id === newValue.assignee_id)?.display_name || "Unassigned";
    return `Reassigned from ${previous} to ${next}.`;
  }
  if (event.event_type === "commented") return `Comment: ${newValue.comment || ""}`;
  if (event.event_type === "transitioned") return `Moved from ${humanize(oldValue.status || "unknown")} to ${humanize(newValue.status || "unknown")}.`;
  if (event.event_type === "updated") return `Updated ${Object.keys(newValue).map(humanize).join(", ") || "this work item"}.`;
  return humanize(event.event_type);
}

async function openDetail(itemId) {
  const content = $("#detail-content");
  content.innerHTML = '<p class="team-empty">Loading item…</p>';
  $("#detail-dialog").showModal();
  try {
    const item = await api(`/items/${itemId}`);
    const isEditor = ["member", "lead", "admin"].includes(state.role);
    const canApprove = state.role === "lead";
    const transitions = { open: "in_progress", in_progress: "awaiting_approval", awaiting_approval: "resolved", resolved: "closed" };
    const next = transitions[item.status];
    const showTransition = next && (item.status !== "awaiting_approval" || canApprove);
    const isUnassigned = !item.assignee_id;
    const activity = item.activity || [];
    const dueValue = item.due_at ? new Date(item.due_at).toISOString().slice(0, 10) : "";
    content.innerHTML = `
      <div class="detail-meta"><span class="priority-pill priority-${safe(item.priority)}">${safe(humanize(item.priority))}</span><span class="status-pill status-${safe(item.status)}">${safe(humanize(item.status))}</span><span class="result-badge">Version ${item.version}</span></div>
      <h2 class="detail-title">${safe(item.title)}</h2>
      <p class="detail-description">${safe(item.description || "No description provided.")}</p>
      <div class="detail-meta"><span class="result-badge">${safe(humanize(item.item_type))}</span><span class="result-badge">Due ${safe(item.due_at ? new Date(item.due_at).toLocaleDateString() : "date not set")}</span><span class="result-badge">Updated ${safe(formatDate(item.updated_at))}</span></div>
      <div class="detail-actions">
        ${isEditor && isUnassigned ? '<button class="button button-primary" id="claim-item">Claim item</button>' : ""}
        ${isEditor && showTransition ? `<button class="button button-secondary" id="transition-item">${item.status === "awaiting_approval" ? "Approve item" : `Move to ${safe(humanize(next))}`}</button>` : ""}
      </div>
      ${isEditor ? `<form id="assign-item-form" class="assign-form"><label for="assignee-picker">Assign to teammate</label><div class="assign-controls"><select id="assignee-picker" name="assignee_id"><option value="">Unassigned</option>${state.members.map((member) => `<option value="${safe(member.id)}" ${member.id === item.assignee_id ? "selected" : ""}>${safe(member.display_name)} · ${safe(humanize(member.role))}</option>`).join("")}</select><button class="button button-secondary" type="submit">Save assignment</button></div><p class="form-error" id="assign-error" role="alert"></p></form>` : ""}
      ${isEditor ? `<form id="edit-item-form"><strong class="activity-heading">Edit work item</strong><div class="edit-grid"><label>Title<input name="title" maxlength="200" required value="${safe(item.title)}" /></label><label>Priority<select name="priority">${["low", "normal", "high", "urgent"].map((p) => `<option value="${p}" ${p === item.priority ? "selected" : ""}>${humanize(p)}</option>`).join("")}</select></label><label>Description<input name="description" maxlength="10000" value="${safe(item.description || "")}" /></label><label>Due date<input name="due_at" type="date" value="${safe(dueValue)}" /></label></div><div class="edit-actions"><button class="button button-secondary" type="submit">Save changes</button></div><p class="form-error" id="edit-error" role="alert"></p></form>` : ""}
      <h3 class="activity-heading">Activity history <span class="result-badge">${activity.length}</span></h3>
      ${activity.length ? `<div class="timeline">${activity.map((event) => {
        const actor = state.members.find((member) => member.id === event.actor_id)?.display_name || "Team member";
        return `<div class="timeline-row"><span class="timeline-mark">·</span><div class="timeline-copy">${safe(eventDescription(event))}<div class="timeline-time">By ${safe(actor)} · ${safe(formatDate(event.created_at))}</div></div></div>`;
      }).join("")}</div>` : '<p class="muted small-copy">No activity recorded yet.</p>'}
      ${isEditor ? '<form id="comment-form" class="form-stack"><label>Add a comment<textarea name="comment" rows="3" maxlength="2000" required placeholder="Share an update with your team…"></textarea></label><p class="form-error" id="comment-error" role="alert"></p><div class="edit-actions"><button class="button button-primary" type="submit">Add comment</button></div></form>' : ""}
    `;
    $("#claim-item")?.addEventListener("click", () => performItemAction(item, "claim"));
    $("#transition-item")?.addEventListener("click", () => performItemAction(item, "transition", next));
    $("#assign-item-form")?.addEventListener("submit", (event) => assignItem(event, item));
    $("#edit-item-form")?.addEventListener("submit", (event) => saveItem(event, item));
    $("#comment-form")?.addEventListener("submit", (event) => addComment(event, item));
  } catch (error) {
    content.innerHTML = `<p class="form-error">${safe(error.message)}</p>`;
  }
}

async function assignItem(event, item) {
  event.preventDefault();
  const assigneeId = new FormData(event.currentTarget).get("assignee_id") || null;
  try {
    await api(`/items/${item.id}/assign`, {
      method: "POST",
      body: JSON.stringify({ expected_version: item.version, assignee_id: assigneeId }),
    });
    notify(assigneeId ? "Work item assigned." : "Work item unassigned.");
    await openDetail(item.id);
    await loadItems();
  } catch (error) {
    $("#assign-error").textContent = error.status === 409
      ? "This item changed. Close and reopen it before assigning."
      : error.message;
  }
}

async function addComment(event, item) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await api(`/items/${item.id}/comments`, {
      method: "POST",
      body: JSON.stringify({ comment: form.get("comment") }),
    });
    notify("Comment added to the activity history.");
    await openDetail(item.id);
    await loadItems();
  } catch (error) {
    $("#comment-error").textContent = error.message;
  }
}

async function performItemAction(item, action, targetStatus) {
  try {
    if (action === "claim") {
      await api(`/items/${item.id}/claim`, { method: "POST" });
      notify("Work item claimed.");
    } else {
      await api(`/items/${item.id}/transition`, {
        method: "POST",
        body: JSON.stringify({ expected_version: item.version, target_status: targetStatus }),
      });
      notify(targetStatus === "resolved" ? "Approval recorded." : `Moved to ${humanize(targetStatus)}.`);
    }
    $("#detail-dialog").close();
    await loadItems();
  } catch (error) {
    notify(error.status === 409 ? "This item changed since you opened it. Close and reopen it to get the latest version." : error.message);
  }
}

async function saveItem(event, item) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const data = {
    expected_version: item.version,
    title: form.get("title"),
    description: form.get("description"),
    priority: form.get("priority"),
    due_at: form.get("due_at") ? `${form.get("due_at")}T00:00:00Z` : null,
  };
  const errorElement = $("#edit-error");
  errorElement.textContent = "";
  try {
    await api(`/items/${item.id}`, { method: "PATCH", body: JSON.stringify(data) });
    $("#detail-dialog").close();
    notify("Work item updated.");
    await loadItems();
  } catch (error) {
    errorElement.textContent = error.status === 409
      ? "This item changed while you were editing. Close and reopen it before saving again."
      : error.message;
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  $("#login-error").textContent = "";
  try {
    const result = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: data.get("email"), password: data.get("password") }),
    });
    state.token = result.access_token;
    sessionStorage.setItem("newtonite_token", state.token);
    await startApp();
  } catch (error) {
    $("#login-error").textContent = error.message;
  }
});

$("#signup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const errorElement = $("#signup-error");
  errorElement.textContent = "";
  try {
    const result = await api("/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        display_name: data.get("display_name"),
        email: data.get("email"),
        password: data.get("password"),
      }),
    });
    state.token = result.access_token;
    sessionStorage.setItem("newtonite_token", state.token);
    await startApp();
  } catch (error) {
    errorElement.textContent = error.message;
  }
});

$("#show-signup").addEventListener("click", showSignup);
$("#show-login").addEventListener("click", () => showLogin());

$("#team-picker").addEventListener("change", async (event) => {
  state.teamId = event.target.value;
  state.role = state.teams.find((team) => team.team_id === state.teamId)?.role || "viewer";
  await loadTeamMembers();
  renderTeams();
  await loadItems();
});

$(".queue-nav").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-queue]");
  if (!button) return;
  state.queue = button.dataset.queue;
  document.querySelectorAll(".queue-link").forEach((link) => link.classList.toggle("active", link === button));
  await loadItems();
});

$("#item-rows").addEventListener("click", (event) => {
  const button = event.target.closest("[data-open-item]");
  if (button) openDetail(button.dataset.openItem);
});

$("#search-input").addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => loadItems(), 300);
});
$("#status-filter").addEventListener("change", () => loadItems());
$("#priority-filter").addEventListener("change", () => loadItems());
$("#clear-filters").addEventListener("click", () => {
  $("#search-input").value = "";
  $("#status-filter").value = "";
  $("#priority-filter").value = "";
  state.queue = "all";
  document.querySelectorAll(".queue-link").forEach((link) => link.classList.toggle("active", link.dataset.queue === "all"));
  loadItems();
});
$("#refresh-button").addEventListener("click", () => loadItems());
$("#load-more").addEventListener("click", () => loadItems({ append: true }));
$("#new-item-button").addEventListener("click", () => {
  $("#create-error").textContent = "";
  $("#create-form").reset();
  $("#create-dialog").showModal();
});
$("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const body = {
    title: data.get("title"),
    description: data.get("description"),
    item_type: data.get("item_type"),
    priority: data.get("priority"),
    due_at: data.get("due_at") ? `${data.get("due_at")}T00:00:00Z` : null,
  };
  try {
    await api(`/teams/${state.teamId}/items`, { method: "POST", body: JSON.stringify(body) });
    $("#create-dialog").close();
    state.queue = "all";
    document.querySelectorAll(".queue-link").forEach((link) => link.classList.toggle("active", link.dataset.queue === "all"));
    $("#search-input").value = "";
    $("#status-filter").value = "";
    $("#priority-filter").value = "";
    notify("Work item created.");
    await loadItems();
  } catch (error) {
    $("#create-error").textContent = error.message;
  }
});
$("#logout-button").addEventListener("click", signOut);
document.querySelectorAll(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
}));
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("#search-input").focus();
  }
});

startApp();
