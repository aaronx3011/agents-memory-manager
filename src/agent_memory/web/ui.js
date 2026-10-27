"use strict";
const $ = (selector) => document.querySelector(selector);
let token = "", projects = [], selected = null, correction = null, offset = 0, searching = false;
let editingProject = null;
function node(tag, text, className) {
  const el = document.createElement(tag); if (text !== undefined) el.textContent = text;
  if (className) el.className = className; return el;
}
function message(text, error = false) {
  const dialogs = [...document.querySelectorAll("dialog[open]")];
  (dialogs.at(-1) || $("main")).append($("#message"));
  $("#message").textContent = text; $("#message").className = `visible${error ? " error" : ""}`;
  clearTimeout(message.timer); message.timer = setTimeout(() => { $("#message").className = ""; }, 8000);
}
async function api(path, data, method) {
  const response = await fetch(path, { method: method || (data ? "POST" : "GET"),
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: data ? JSON.stringify(data) : undefined });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail));
  return value;
}
function guard(fn) { return async (event) => { event?.preventDefault();
  try { await fn(event); } catch (error) { message(error.message, true); } }; }
async function health() {
  try { const result = await (await fetch("/health")).json();
    $("#health").textContent = result.embeddings_ready ? "Local · semantic recall ready" : "Local · embeddings load on first use";
  } catch { $("#health").textContent = "Service unavailable"; }
}
function projectName(id) { return id ? projects.find((p) => p.id === id)?.name || id : "Owner-wide"; }
async function refreshProjects() {
  projects = await api("/api/projects");
  for (const selector of ["#project-filter", "#capture-project", "#credential-projects"]) {
    const select = $(selector), value = select.value;
    while (select.options.length > (selector === "#credential-projects" ? 0 : 1)) select.remove(select.options.length - 1);
    for (const p of projects) { const option = node("option", p.name); option.value = p.id; select.append(option); }
    select.value = projects.some((p) => p.id === value) ? value : "";
  }
  $("#summary").textContent = `${projects.length} registered project${projects.length === 1 ? "" : "s"} · PostgreSQL + local semantic search`;
  renderProjects();
}
function renderProjects() {
  const list = $("#projects-list"); list.replaceChildren();
  for (const project of projects) {
    const item = node("div", undefined, "job");
    item.append(node("h3", project.name), node("p", project.repo_url || "No repository URL", "muted"),
      node("pre", project.aliases.join("\n") || "No directory aliases"));
    const actions = node("div", undefined, "actions");
    const edit = node("button", "Edit", "secondary");
    edit.setAttribute("aria-label", `Edit ${project.name}`);
    edit.onclick = () => editProject(project);
    const remove = node("button", "Remove", "danger");
    remove.setAttribute("aria-label", `Remove ${project.name}`);
    remove.onclick = guard(async () => {
      if (!confirm(`Remove project “${project.name}”? Its identity and access-key grants will be removed. Projects with stored data cannot be removed.`)) return;
      await api(`/api/projects/${project.id}`, undefined, "DELETE");
      await refreshProjects(); await loadRecords(); message("Project removed.");
    });
    actions.append(edit, remove); item.append(actions); list.append(item);
  }
  if (!projects.length) list.append(node("p", "No registered projects. Register your first project to get started.", "empty"));
}
function editProject(project = null) {
  editingProject = project; const form = $("#project-form"); form.reset();
  $("#project-heading").textContent = project ? "Edit project" : "Register a project";
  $("#save-project").textContent = project ? "Save changes" : "Register";
  form.elements.name.value = project?.name || "";
  form.elements.repo_url.value = project?.repo_url || "";
  form.elements.alias.value = project?.aliases.join("\n") || "";
  $("#project-dialog").showModal();
}
async function loadRecords(append = false) {
  if (!append) offset = 0;
  const project = $("#project-filter").value, query = $("#query").value.trim();
  searching = Boolean(query);
  let records;
  if (query) {
    const result = await api("/api/search", { query, project_id: project || null, cross_project: !project, limit: 50 });
    records = result.results; $("#retrieval-mode").textContent = `${result.mode.replaceAll("_", " ")} · ${records.length} matches`;
  } else {
    records = await api(`/api/memories?limit=100&offset=${offset}${project ? `&project_id=${project}` : ""}`);
    $("#retrieval-mode").textContent = "Recent memories · includes candidates and historical states";
  }
  if (!append) $("#records").replaceChildren();
  for (const record of records) {
    const card = node("button", undefined, "record");
    const tags = node("div", undefined, "tags");
    for (const text of [record.type, record.status, record.evidence]) tags.append(node("span", text, "tag"));
    if (record.stale) tags.append(node("span", "Review due", "tag stale"));
    card.append(tags, node("h2", record.title), node("p", record.content),
      node("small", `${projectName(record.project_id)} · revision ${record.revision}`));
    card.onclick = guard(() => showDetail(record.id)); $("#records").append(card);
  }
  if (!$("#records").children.length) $("#records").append(node("div", "No memories yet. Register a project and capture a sourced fact, decision, or workflow.", "empty"));
  $("#load-more").hidden = searching || records.length < 100;
  offset += records.length;
}
async function showDetail(id) {
  selected = await api(`/api/memories/${id}`);
  $("#detail-title").textContent = selected.title;
  const body = $("#detail-body"); body.replaceChildren();
  body.append(node("p", `${projectName(selected.project_id)} · ${selected.type} · ${selected.status} · ${selected.evidence}`),
    node("p", selected.content, "prose"));
  for (const [title, value] of [["Sources", selected.sources], ["Freshness", { verified_at: selected.verified_at, review_after: selected.review_after, stale: selected.stale }], ["Relationships", { supersedes: selected.supersedes, replaced_by: selected.replaced_by, links: selected.links }], ["Revision history", selected.history]]) {
    body.append(node("h3", title), node("pre", JSON.stringify(value, null, 2)));
  }
  $("#correct-button").disabled = selected.status === "superseded";
  $("#promote-button").hidden = selected.status !== "candidate";
  $("#detail-dialog").showModal();
}
function editMemory(record = null) {
  correction = record; const form = $("#memory-form"); form.reset();
  $("#memory-heading").textContent = record ? "Replace with a sourced correction" : "Capture memory";
  form.elements.project_id.value = record?.project_id || $("#project-filter").value;
  form.elements.project_id.disabled = Boolean(record);
  if (record) {
    for (const key of ["type", "title", "content", "evidence"]) form.elements[key].value = record[key];
    form.elements.status.value = "active";
    form.elements.reference.value = record.sources[0].reference;
    form.elements.source_kind.value = record.sources[0].kind;
    form.elements.tags.value = record.tags.join(", ");
    // Verification must be refreshed explicitly for the corrected knowledge.
    if (record.evidence === "verified") form.elements.evidence.value = "reported";
  }
  $("#memory-dialog").showModal();
}
$("#login-form").onsubmit = guard(async () => {
  token = $("#token").value.trim(); await refreshProjects();
  const session = await api("/api/session");
  for (const id of ["#project-button", "#credentials-button", "#export-button"]) $(id).hidden = !session.can_manage;
  $("#token").value = ""; $("#login").hidden = true; $("#workspace").hidden = false;
  await loadRecords(); await health();
});
$("#disconnect").onclick = () => {
  token = ""; projects = []; selected = null; correction = null;
  $("#records").replaceChildren(); $("#detail-body").replaceChildren();
  $("#new-token").textContent = ""; $("#workspace").hidden = true; $("#login").hidden = false;
};
document.querySelectorAll("[data-close]").forEach((el) => { el.onclick = () => el.closest("dialog").close(); });
$("#project-button").onclick = guard(async () => { await refreshProjects(); $("#projects-dialog").showModal(); });
$("#new-project-button").onclick = () => editProject();
$("#project-form").onsubmit = guard(async () => {
  const form = $("#project-form");
  const data = { name: form.elements.name.value.trim(), repo_url: form.elements.repo_url.value.trim() || null,
    aliases: form.elements.alias.value.split("\n").map((alias) => alias.trim()).filter(Boolean) };
  await api(editingProject ? `/api/projects/${editingProject.id}` : "/api/projects", data, editingProject ? "PUT" : "POST");
  form.reset(); $("#project-dialog").close(); await refreshProjects(); await loadRecords(); message(editingProject ? "Project updated." : "Project registered centrally.");
});
$("#create-button").onclick = () => editMemory();
$("#correct-button").onclick = () => { $("#detail-dialog").close(); editMemory(selected); };
$("#memory-form").onsubmit = guard(async () => {
  const form = $("#memory-form"), field = (name) => form.elements[name].value;
  const data = { project_id: correction?.project_id || field("project_id") || null,
    type: field("type"), status: field("status"), title: field("title"), content: field("content"),
    evidence: field("evidence"), sources: [{ kind: field("source_kind"), reference: field("reference") }],
    tags: field("tags").split(",").map((x) => x.trim()).filter(Boolean),
    verified_at: field("verified_at") ? new Date(field("verified_at")).toISOString() : null,
    review_after: field("review_after") ? new Date(field("review_after")).toISOString() : null };
  if (correction) await api(`/api/memories/${correction.id}/correct`, { expected_revision: correction.revision, replacement: data });
  else await api("/api/memories", { ...data, idempotency_key: crypto.randomUUID() });
  $("#memory-dialog").close(); await loadRecords(); message("Memory committed. Background embedding is queued.");
});
$("#promote-button").onclick = guard(async () => {
  await api(`/api/memories/${selected.id}/status`, { expected_revision: selected.revision, status: "active" });
  $("#detail-dialog").close(); await loadRecords(); message("Candidate activated; evidence label preserved.");
});
$("#delete-button").onclick = guard(async () => {
  if (!confirm("Forget this memory, its derived records, history, and linked checkpoints?")) return;
  await api(`/api/memories/${selected.id}`, undefined, "DELETE");
  $("#detail-dialog").close(); await loadRecords(); message("Memory purged from active storage. Historical backups expire separately.");
});
$("#search-form").onsubmit = guard(() => loadRecords());
$("#project-filter").onchange = guard(() => loadRecords());
$("#clear-search").onclick = guard(async () => { $("#query").value = ""; await loadRecords(); });
$("#load-more").onclick = guard(() => loadRecords(true));
$("#jobs-button").onclick = guard(async () => {
  const jobs = await api("/api/jobs"), list = $("#jobs-list"); list.replaceChildren();
  for (const job of jobs) {
    const item = node("div", undefined, "job");
    item.append(node("strong", `${job.kind} · ${job.status}`), node("p", `${job.id} · attempts ${job.attempts}${job.error ? ` · ${job.error}` : ""}`, "muted"));
    if (job.status === "failed") { const retry = node("button", "Retry", "secondary"); retry.onclick = guard(async () => { await api(`/api/jobs/${job.id}/retry`, {}); item.replaceChildren(node("p", "Retry queued")); }); item.append(retry); }
    list.append(item);
  }
  if (!jobs.length) list.append(node("p", "No background jobs.")); $("#jobs-dialog").showModal();
});
async function showCredentials() {
  const list = $("#credentials-list"); list.replaceChildren();
  for (const credential of await api("/api/credentials")) {
    const item = node("div", undefined, "job"); item.append(node("strong", credential.name), node("p", `${credential.all_projects ? "All projects" : credential.project_ids.length + " projects"} · ${credential.can_write ? "read/write" : "read-only"} · ${credential.revoked ? "revoked" : "active"}`));
    if (!credential.revoked) { const revoke = node("button", "Revoke", "secondary"); revoke.onclick = guard(async () => { await api(`/api/credentials/${credential.id}`, undefined, "DELETE"); await showCredentials(); }); item.append(revoke); }
    list.append(item);
  }
}
$("#credentials-button").onclick = guard(async () => { $("#new-token").hidden = true; $("#new-token").textContent = ""; await showCredentials(); $("#credentials-dialog").showModal(); });
$("#credential-form").onsubmit = guard(async () => {
  const form = $("#credential-form"), result = await api("/api/credentials", { name: form.elements.name.value,
    project_ids: [...$("#credential-projects").selectedOptions].map((x) => x.value),
    all_projects: form.elements.all_projects.checked,
    allow_shared: form.elements.allow_shared.checked, can_write: form.elements.can_write.checked });
  $("#new-token").textContent = `Copy this key now; it is only returned once:\n${result.token}`; $("#new-token").hidden = false;
  await showCredentials();
});
$("#export-button").onclick = guard(async () => {
  const data = await api("/api/export"), blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob), link = node("a"); link.href = url; link.download = "agent-memory-export.json"; link.click(); URL.revokeObjectURL(url);
});
health();
