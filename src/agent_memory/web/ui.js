"use strict";
const $ = (selector) => document.querySelector(selector);
let token = "", projects = [], selected = null, correction = null, offset = 0, searching = false;
let editingProject = null, vectorFocus = null, mapState = null;
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
function vectorStatsText(stats) {
  if (!stats) return "No embedding stored yet. Capture queues a background embedding job.";
  return `${stats.dimensions} dimensions · norm ${stats.norm.toFixed(3)} · mean ${stats.mean.toFixed(3)} · standard deviation ${stats.std.toFixed(3)} · range ${stats.min.toFixed(3)} to ${stats.max.toFixed(3)}`;
}
function drawSignal(canvas, values, color = "#8bd5c1") {
  const ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
  ctx.fillStyle = "#0b131f"; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#1c2737"; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (h * i) / 4;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  if (!values || !values.length) {
    ctx.fillStyle = "#95a6bc"; ctx.font = "13px system-ui";
    ctx.fillText("No stored vector values.", 14, h / 2);
    return;
  }
  const mid = h / 2, step = w / values.length;
  const scale = Math.max(values.reduce((peak, value) => Math.max(peak, Math.abs(value)), 0), 1e-6);
  for (let i = 0; i < values.length; i++) {
    const height = Math.max(1, (Math.abs(values[i]) / scale) * (h / 2 - 12));
    ctx.fillStyle = values[i] >= 0 ? color : "#e8a06f";
    ctx.fillRect(i * step, values[i] >= 0 ? mid - height : mid, Math.max(1, step - 0.5), height);
  }
  ctx.strokeStyle = "#40516b";
  ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke();
}
function drawVectorMap(data) {
  const canvas = $("#vector-map"), ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height, pad = 38;
  ctx.fillStyle = "#0b131f"; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#1c2737"; ctx.lineWidth = 1;
  for (let i = 1; i < 5; i++) {
    ctx.beginPath(); ctx.moveTo(pad, pad + ((h - 2 * pad) * i) / 5); ctx.lineTo(w - pad, pad + ((h - 2 * pad) * i) / 5); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(pad + ((w - 2 * pad) * i) / 5, pad); ctx.lineTo(pad + ((w - 2 * pad) * i) / 5, h - pad); ctx.stroke();
  }
  const points = data.projection.points || [];
  if (points.length < 2) {
    ctx.fillStyle = "#95a6bc"; ctx.font = "13px system-ui";
    ctx.fillText("At least two stored embeddings are needed to draw a map.", pad, h / 2);
    return;
  }
  const colors = { record: "#8bd5c1", passage: "#6fa8ff", neighbor: "#c4a2ff" };
  for (const point of points) {
    const x = pad + point.x * (w - 2 * pad), y = pad + point.y * (h - 2 * pad);
    ctx.fillStyle = colors[point.kind] || "#95a6bc";
    ctx.beginPath();
    if (point.kind === "record") {
      ctx.moveTo(x, y - 7); ctx.lineTo(x + 7, y); ctx.lineTo(x, y + 7); ctx.lineTo(x - 7, y);
      ctx.closePath();
    } else {
      ctx.arc(x, y, point.kind === "neighbor" ? 4 : 5, 0, Math.PI * 2);
    }
    ctx.fill();
    if (vectorFocus && vectorFocus.kind === point.kind && vectorFocus.ordinal === point.ordinal) {
      ctx.strokeStyle = "#f2c17b"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.stroke();
      ctx.lineWidth = 1;
    }
  }
  const placed = [];
  ctx.fillStyle = "#b7c7d9"; ctx.font = "11px system-ui";
  const priority = { record: 0, neighbor: 1, passage: 2 };
  for (const point of [...points].sort((a, b) => priority[a.kind] - priority[b.kind])) {
    const x = pad + point.x * (w - 2 * pad), y = pad + point.y * (h - 2 * pad);
    const label = point.kind === "record" ? "memory"
      : point.kind === "passage" ? `P${(point.ordinal ?? 0) + 1}` : `#${point.rank}`;
    const width = ctx.measureText(label).width + 6;
    const box = { left: x + 6, top: y - 14, right: x + 6 + width, bottom: y + 2 };
    if (placed.some((item) => box.left < item.right && box.right > item.left
      && box.top < item.bottom && box.bottom > item.top)) continue;
    placed.push(box);
    ctx.fillText(label, x + 8, y - 6);
  }
  const [pc1 = 0, pc2 = 0] = data.projection.explained || [];
  ctx.fillStyle = "#95a6bc"; ctx.font = "11px system-ui";
  ctx.fillText(`PC2 ${(pc2 * 100).toFixed(1)}%`, 10, 18);
  ctx.fillText(`PC1 ${(pc1 * 100).toFixed(1)}%`, w - 90, h - 10);
}
function renderVectorLegend() {
  const legend = $("#vector-legend"); legend.replaceChildren();
  for (const [color, text] of [["#8bd5c1", "This memory"], ["#6fa8ff", "Passages"], ["#c4a2ff", "Nearest memories"]]) {
    const item = node("span", text); item.style.color = color; legend.append(item);
  }
}
function renderVectorPassages(data) {
  const list = $("#vector-passages"); list.replaceChildren();
  const whole = node("button", undefined, "vector-row");
  whole.append(node("span", "All", "vector-rank"), node("span", "Whole record embedding", "grow"));
  whole.onclick = () => {
    vectorFocus = null; $("#vector-axis").textContent = "Whole memory";
    drawSignal($("#vector-chart"), data.embedding.present ? data.embedding.stats.values : []);
    $("#vector-stats").textContent = vectorStatsText(data.embedding.stats);
    drawVectorMap(data);
    for (const row of list.querySelectorAll(".vector-row")) row.classList.remove("selected");
    whole.classList.add("selected");
  };
  whole.classList.toggle("selected", !vectorFocus);
  list.append(whole);
  for (const passage of data.passages) {
    const row = node("button", undefined, "vector-row"), canvas = document.createElement("canvas");
    canvas.width = 150; canvas.height = 36; canvas.className = "mini-vector";
    drawSignal(canvas, passage.stats?.values, "#6fa8ff");
    const body = node("span", undefined, "grow");
    body.append(node("strong", `Passage ${passage.ordinal + 1}`),
      node("small", `${passage.tokens ?? "?"} tokens · cosine to record ${passage.cosine_to_record == null ? "n/a" : passage.cosine_to_record.toFixed(3)}`),
      node("small", passage.text, "muted vector-preview"));
    row.append(node("span", `P${passage.ordinal + 1}`, "vector-rank"), canvas, body);
    row.onclick = () => {
      vectorFocus = { kind: "passage", ordinal: passage.ordinal };
      $("#vector-axis").textContent = `Passage ${passage.ordinal + 1}`;
      drawSignal($("#vector-chart"), passage.stats?.values, "#6fa8ff");
      $("#vector-stats").textContent = vectorStatsText(passage.stats);
      drawVectorMap(data);
      for (const item of list.querySelectorAll(".vector-row")) item.classList.remove("selected");
      row.classList.add("selected");
    };
    list.append(row);
  }
}
function renderVectorNeighbors(data) {
  const list = $("#vector-neighbors"); list.replaceChildren();
  if (!data.neighbors.length) {
    list.append(node("p", "No comparable memories yet. Capture and embed another memory in this project.", "muted"));
    return;
  }
  for (const neighbor of data.neighbors) {
    const row = node("button", undefined, "vector-row"), body = node("span", undefined, "grow");
    body.append(node("strong", `${projectName(neighbor.project_id)} · ${neighbor.title}`));
    const track = node("span", undefined, "score-track"), fill = node("span", undefined, "score-fill");
    fill.style.width = `${Math.max(0, Math.min(1, neighbor.similarity)) * 100}%`;
    track.append(fill); body.append(track);
    row.append(node("span", `#${neighbor.rank}`, "vector-rank"), body,
      node("small", `${(neighbor.similarity * 100).toFixed(1)}% cosine`, "vector-score"));
    row.title = `Open ${neighbor.title}`;
    row.onclick = guard(async () => { $("#vector-dialog").close(); await showDetail(neighbor.id); });
    list.append(row);
  }
}
async function showVectors() {
  if (!selected) return;
  vectorFocus = null;
  $("#vector-heading").textContent = "Vector representation";
  $("#vector-summary").textContent = "Loading stored embedding…";
  $("#vector-axis").textContent = ""; $("#vector-stats").textContent = "";
  $("#vector-explained").textContent = "";
  $("#vector-passages").replaceChildren(); $("#vector-neighbors").replaceChildren();
  $("#vector-legend").replaceChildren();
  drawSignal($("#vector-chart"), []);
  $("#vector-dialog").showModal();
  const data = await api(`/api/memories/${selected.id}/vectors`);
  const embedding = data.embedding;
  $("#vector-heading").textContent = `Vector representation · ${data.memory.title}`;
  $("#vector-summary").textContent = embedding.present
    ? `${data.embedding_model || embedding.model} · ${embedding.stats.dimensions} dimensions · derived from title and knowledge`
    : (data.job ? `Embedding not stored yet. Latest job: ${data.job.status}.` : "Embedding not stored yet; no job is recorded.");
  $("#vector-axis").textContent = "Whole memory";
  drawSignal($("#vector-chart"), embedding.present ? embedding.stats.values : []);
  $("#vector-stats").textContent = vectorStatsText(embedding.stats);
  const [pc1 = 0, pc2 = 0] = data.projection.explained || [];
  $("#vector-explained").textContent = data.projection.points.length > 1
    ? `PCA of ${data.projection.points.length} vectors · PC1 ${(pc1 * 100).toFixed(1)}% · PC2 ${(pc2 * 100).toFixed(1)}%`
    : "Needs at least two stored vectors.";
  renderVectorLegend(); renderVectorPassages(data);
  drawVectorMap(data); renderVectorNeighbors(data);
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
$("#vector-button").onclick = guard(showVectors);
const celestialTypeColors = {
  episodic: "#6fa8ff", semantic: "#8bd5c1", procedural: "#c4a2ff",
  decision: "#f2c17b", preference: "#ef8fb2",
};
// Categorical palette tuned for the dark map background; assigned by project size.
const celestialPalette = ["#6fa8ff", "#8bd5c1", "#f2c17b", "#ef8fb2", "#c4a2ff", "#ff9f6b",
  "#7fd6f0", "#d4e07a", "#f5a3a3", "#a3c4ff", "#9be29b", "#e3b8ff"];
const celestialEdgeStyles = {
  similarity: ["#7f97b8", 0.22, []],
  relates_to: ["#8bd5c1", 0.7, []],
  derived_from: ["#6fa8ff", 0.75, [5, 4]],
  contradicts: ["#ef8fb2", 0.85, [2, 4]],
};
const celestialEdgeNames = {
  relates_to: "Related", derived_from: "Derived", contradicts: "Contradicts", similarity: "Semantic thread",
};
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
function hashNumber(value) {
  let hash = 2166136261;
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0); hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash);
}
function celestialKey(item, by) { return by === "type" ? item.type : item.project_id || "owner-wide"; }
function celestialGroupName(key, by) { return by === "type" ? key : projectName(key === "owner-wide" ? null : key); }
function celestialColor(item) {
  return mapState.colors[mapState.colorBy].get(celestialKey(item, mapState.colorBy)) || "#95a6bc";
}
function celestialVisible(item) {
  return !mapState.hidden.project.has(celestialKey(item, "project"))
    && !mapState.hidden.type.has(celestialKey(item, "type"));
}
function celestialBackground(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext("2d");
  const glow = ctx.createRadialGradient(width * 0.5, height * 0.45, 20, width * 0.5, height * 0.5, Math.max(width, height) * 0.7);
  glow.addColorStop(0, "#0d1a2b"); glow.addColorStop(1, "#04070d");
  ctx.fillStyle = glow; ctx.fillRect(0, 0, width, height);
  let seed = hashNumber("celestial-map") || 1;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const scale = window.devicePixelRatio || 1;
  for (let index = 0, count = Math.round((width * height) / (5200 * scale * scale)); index < count; index++) {
    ctx.globalAlpha = 0.12 + random() * 0.45;
    ctx.fillStyle = random() > 0.82 ? "#cfe6ff" : "#8fa8c4";
    ctx.beginPath(); ctx.arc(random() * width, random() * height, (random() > 0.94 ? 1.2 : 0.5) * scale, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  return canvas;
}
function celestialOrder(nodes, key) {
  const counts = new Map();
  for (const item of nodes) counts.set(key(item), (counts.get(key(item)) || 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}
function prepareCelestial(data, previous = null) {
  const nodes = data.nodes.map((item) => ({ ...item, degree: 0 }));
  const byId = new Map(nodes.map((item) => [item.id, item]));
  const edges = data.edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target))
    .map((edge) => ({ ...edge, source: byId.get(edge.source), target: byId.get(edge.target) }));
  const relations = new Map(nodes.map((item) => [item, []]));
  for (const edge of edges) {
    edge.source.degree += 1; edge.target.degree += 1;
    relations.get(edge.source).push({ node: edge.target, edge });
    relations.get(edge.target).push({ node: edge.source, edge });
  }
  const projectGroups = celestialOrder(nodes, (item) => celestialKey(item, "project"));
  const typeGroups = celestialOrder(nodes, (item) => item.type);
  // Each project gets its own anchor so constellations read as clusters, not a uniform cloud.
  const anchors = new Map(), spread = 16 * Math.sqrt(nodes.length) + 30;
  projectGroups.forEach(([key], index) => {
    const angle = index * 2.399963229728653, distance = projectGroups.length === 1 ? 0 : spread * Math.sqrt((index + 0.5) / projectGroups.length);
    anchors.set(key, { x: Math.cos(angle) * distance, y: Math.sin(angle) * distance });
  });
  for (const item of nodes) {
    const anchor = anchors.get(celestialKey(item, "project")), jitter = hashNumber(item.id);
    item.radius = 3 + Math.min(7, Math.sqrt(item.degree) * 1.8);
    item.x = anchor.x + ((jitter % 1000) / 1000 - 0.5) * 60;
    item.y = anchor.y + (((jitter >>> 10) % 1000) / 1000 - 0.5) * 60;
  }
  const simulation = d3.forceSimulation(nodes)
    .force("charge", d3.forceManyBody().strength(-22).distanceMax(180))
    .force("link", d3.forceLink(edges).distance((edge) => edge.kind === "similarity" ? 44 : 30)
      .strength((edge) => {
        const crossing = celestialKey(edge.source, "project") !== celestialKey(edge.target, "project");
        return edge.kind === "similarity" ? (crossing ? 0.02 : 0.12) : (crossing ? 0.08 : 0.4);
      }))
    .force("x", d3.forceX((item) => anchors.get(celestialKey(item, "project")).x).strength(0.09))
    .force("y", d3.forceY((item) => anchors.get(celestialKey(item, "project")).y).strength(0.09))
    .force("collide", d3.forceCollide((item) => item.radius + 2.5))
    .stop();
  const ticks = Math.ceil(Math.log(simulation.alphaMin()) / Math.log(1 - simulation.alphaDecay()));
  for (let tick = 0; tick < ticks; tick++) simulation.tick();
  simulation.on("tick", () => drawCelestial());
  return {
    source: data, nodes, edges, byId, relations, simulation,
    colors: {
      project: new Map(projectGroups.map(([key], index) => [key, celestialPalette[index % celestialPalette.length]])),
      type: new Map(typeGroups.map(([key]) => [key, celestialTypeColors[key] || "#95a6bc"])),
    },
    groups: { project: projectGroups, type: typeGroups },
    colorBy: previous?.colorBy || "project", threads: previous?.threads ?? true,
    hidden: previous?.hidden || { project: new Set(), type: new Set() },
    query: previous?.query || "", matches: null, selected: null, hover: null, dragging: null,
    transform: d3.zoomIdentity, width: 0, height: 0, dpr: 1, background: null,
  };
}
function resizeCelestial() {
  if (!mapState) return;
  const canvas = $("#map-canvas"), rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (!rect.width || !rect.height) return;
  const changed = rect.width !== mapState.width || rect.height !== mapState.height || dpr !== mapState.dpr;
  mapState.width = rect.width; mapState.height = rect.height; mapState.dpr = dpr;
  if (changed || !mapState.background) {
    canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
    mapState.background = celestialBackground(canvas.width, canvas.height);
  }
  drawCelestial();
}
function celestialFocusSet() {
  const focus = mapState.selected || mapState.hover;
  if (!focus) return null;
  return new Set([focus, ...mapState.relations.get(focus).map((relation) => relation.node)]);
}
function drawCelestial() {
  const state = mapState, canvas = $("#map-canvas");
  if (!state || !state.width || !state.background) return;
  const ctx = canvas.getContext("2d"), t = state.transform;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1;
  ctx.drawImage(state.background, 0, 0);
  ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
  if (!state.nodes.length) return;
  const focus = state.selected || state.hover, near = celestialFocusSet(), matches = state.matches;
  ctx.save(); ctx.translate(t.x, t.y); ctx.scale(t.k, t.k);
  for (const edge of state.edges) {
    if (edge.kind === "similarity" && !state.threads) continue;
    if (!celestialVisible(edge.source) || !celestialVisible(edge.target)) continue;
    const [color, opacity, dash] = celestialEdgeStyles[edge.kind] || celestialEdgeStyles.similarity;
    const active = focus && (edge.source === focus || edge.target === focus);
    ctx.strokeStyle = color;
    ctx.globalAlpha = active ? 0.95 : focus || matches ? opacity * 0.25 : opacity;
    ctx.lineWidth = (active ? 2 : edge.kind === "similarity" ? 0.8 : 1.3) / t.k;
    ctx.setLineDash(dash.map((value) => value / t.k));
    ctx.beginPath(); ctx.moveTo(edge.source.x, edge.source.y); ctx.lineTo(edge.target.x, edge.target.y); ctx.stroke();
  }
  ctx.setLineDash([]);
  for (const item of state.nodes) {
    if (!celestialVisible(item)) continue;
    const dim = (near && !near.has(item)) || (matches && !matches.has(item));
    const color = celestialColor(item);
    ctx.fillStyle = color;
    if (!dim) {
      ctx.globalAlpha = 0.14;
      ctx.beginPath(); ctx.arc(item.x, item.y, item.radius * 2.2, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = dim ? 0.22 : 1;
    ctx.beginPath(); ctx.arc(item.x, item.y, item.radius, 0, Math.PI * 2); ctx.fill();
    if (!dim) {
      ctx.fillStyle = "#f7fcff"; ctx.globalAlpha = 0.9;
      ctx.beginPath(); ctx.arc(item.x, item.y, Math.max(0.9, item.radius * 0.35), 0, Math.PI * 2); ctx.fill();
    }
    if (item.stale && !dim) {
      ctx.globalAlpha = 1; ctx.strokeStyle = "#f2c17b"; ctx.lineWidth = 1.2 / t.k;
      ctx.setLineDash([2 / t.k, 2 / t.k]);
      ctx.beginPath(); ctx.arc(item.x, item.y, item.radius + 2.5 / t.k, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
    }
    if (item === state.selected || item === state.hover || item === state.dragging) {
      ctx.globalAlpha = 1; ctx.strokeStyle = item === state.selected ? "#ffffff" : "#f2c17b";
      ctx.lineWidth = 2 / t.k;
      ctx.beginPath(); ctx.arc(item.x, item.y, item.radius + 4 / t.k, 0, Math.PI * 2); ctx.stroke();
    }
  }
  ctx.restore(); ctx.globalAlpha = 1;
  drawCelestialLabels(ctx, focus, near);
}
function drawCelestialLabels(ctx, focus, near) {
  const state = mapState, t = state.transform, placed = [];
  const fits = (box) => box.right > 0 && box.left < state.width && box.bottom > 0 && box.top < state.height
    && !placed.some((other) => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top);
  if (state.colorBy === "project" && !focus && state.groups.project.length > 1) {
    const extents = new Map();
    for (const item of state.nodes) {
      if (!celestialVisible(item)) continue;
      const key = celestialKey(item, "project"), extent = extents.get(key) || { x: 0, n: 0, top: Infinity };
      extent.x += item.x; extent.n += 1; extent.top = Math.min(extent.top, item.y - item.radius);
      extents.set(key, extent);
    }
    ctx.font = "600 12px system-ui"; ctx.textBaseline = "alphabetic"; ctx.textAlign = "center";
    for (const [key, extent] of extents) {
      if (extent.n < 2) continue;
      const text = celestialGroupName(key, "project").toUpperCase();
      const width = ctx.measureText(text).width, y = t.applyY(extent.top) - 12;
      const x = Math.max(width / 2 + 6, Math.min(state.width - width / 2 - 6, t.applyX(extent.x / extent.n)));
      const box = { left: x - width / 2 - 4, right: x + width / 2 + 4, top: y - 13, bottom: y + 4 };
      if (!fits(box)) continue;
      placed.push(box);
      ctx.fillStyle = state.colors.project.get(key); ctx.globalAlpha = 0.85;
      ctx.fillText(text, x, y);
    }
    ctx.globalAlpha = 1; ctx.textAlign = "start";
  }
  const seen = new Set(), candidates = [];
  const add = (item) => { if (item && !seen.has(item) && celestialVisible(item)) { seen.add(item); candidates.push(item); } };
  add(state.selected); add(state.hover);
  if (near) [...near].sort((a, b) => b.degree - a.degree).forEach(add);
  if (state.matches) [...state.matches].slice(0, 40).forEach(add);
  if (!focus && !state.matches) {
    const ranked = [...state.nodes].sort((a, b) => b.degree - a.degree);
    ranked.slice(0, state.nodes.length <= 30 ? 30 : Math.round(8 * t.k * t.k)).forEach(add);
  }
  ctx.font = "12px system-ui"; ctx.textBaseline = "middle";
  for (const item of candidates) {
    const x = t.applyX(item.x), y = t.applyY(item.y), offset = item.radius * t.k + 6;
    // Put the label on the side with more room and shorten it to fit inside the canvas.
    const rightRoom = state.width - 6 - (x + offset), leftRoom = x - offset - 6;
    const room = Math.min(320, Math.max(rightRoom, leftRoom)) - 12;
    if (room < 40) continue;
    let text = item.title.length > 48 ? `${item.title.slice(0, 47)}…` : item.title;
    while (text.length > 4 && ctx.measureText(text).width > room) text = `${text.slice(0, -2)}…`;
    const width = ctx.measureText(text).width + 12;
    const box = rightRoom >= width || rightRoom >= leftRoom
      ? { left: x + offset, top: y - 10, right: x + offset + width, bottom: y + 10 }
      : { left: x - offset - width, top: y - 10, right: x - offset, bottom: y + 10 };
    const important = item === state.selected || item === state.hover;
    if (!important && !fits(box)) continue;
    placed.push(box);
    ctx.fillStyle = "rgba(5, 9, 18, 0.82)";
    ctx.beginPath(); ctx.roundRect(box.left, box.top, width, 20, 5); ctx.fill();
    ctx.fillStyle = important ? "#ffffff" : "#c9d6e6";
    ctx.fillText(text, box.left + 6, y);
  }
}
function celestialFind(sx, sy) {
  if (!mapState) return null;
  const t = mapState.transform, x = t.invertX(sx), y = t.invertY(sy);
  let best = null, bestDistance = Infinity;
  for (const item of mapState.nodes) {
    if (!celestialVisible(item)) continue;
    const distance = Math.hypot(item.x - x, item.y - y);
    if (distance < Math.max(item.radius + 3, 12 / t.k) && distance < bestDistance) { best = item; bestDistance = distance; }
  }
  return best;
}
function celestialPointer(event) {
  const rect = $("#map-canvas").getBoundingClientRect();
  return [event.clientX - rect.left, event.clientY - rect.top];
}
function showMapTooltip(event, item) {
  const tooltip = $("#map-tooltip"), shell = $(".map-shell");
  if (!item) { tooltip.hidden = true; return; }
  tooltip.replaceChildren(
    node("strong", item.title),
    node("small", `${projectName(item.project_id)} · ${item.type} · ${item.status}`),
    node("small", `${item.degree} relation${item.degree === 1 ? "" : "s"}${item.stale ? " · review due" : ""}`),
  );
  tooltip.hidden = false;
  const rect = shell.getBoundingClientRect();
  const left = event.clientX - rect.left + 14, top = event.clientY - rect.top + 14;
  tooltip.style.left = `${Math.max(8, Math.min(left, rect.width - tooltip.offsetWidth - 8))}px`;
  tooltip.style.top = `${top + tooltip.offsetHeight > rect.height - 8 ? Math.max(8, top - tooltip.offsetHeight - 24) : top}px`;
}
function celestialTransition() {
  const selection = d3.select("#map-canvas");
  return reducedMotion.matches ? selection : selection.transition().duration(450);
}
function fitCelestial(animate = true) {
  const state = mapState;
  if (!state || !state.width) return;
  const visible = state.nodes.filter(celestialVisible);
  if (!visible.length) return;
  const [minX, maxX] = d3.extent(visible, (item) => item.x), [minY, maxY] = d3.extent(visible, (item) => item.y);
  const pad = Math.min(70, state.width * 0.08);
  const k = Math.max(0.15, Math.min(3, (state.width - pad * 2) / Math.max(1, maxX - minX), (state.height - pad * 2) / Math.max(1, maxY - minY)));
  const target = d3.zoomIdentity.translate(state.width / 2, state.height / 2).scale(k).translate(-(minX + maxX) / 2, -(minY + maxY) / 2);
  (animate ? celestialTransition() : d3.select("#map-canvas")).call(mapZoom.transform, target);
}
function centerCelestial(item) {
  const state = mapState, k = Math.max(state.transform.k, 1.6);
  const target = d3.zoomIdentity.translate(state.width / 2, state.height / 2).scale(k).translate(-item.x, -item.y);
  celestialTransition().call(mapZoom.transform, target);
}
function selectCelestial(item, center = false) {
  if (!mapState) return;
  mapState.selected = item; mapState.hover = null; $("#map-tooltip").hidden = true;
  renderMapSelection(); syncMapIndex();
  if (item && center) centerCelestial(item); else drawCelestial();
}
function setMapState(text, retry = false) {
  const state = $("#map-state"); state.replaceChildren();
  state.hidden = !text;
  if (!text) return;
  const body = node("div"); body.append(node("p", text));
  if (retry) { const button = node("button", "Try again", "secondary"); button.onclick = guard(showMap); body.append(button); }
  state.append(body);
}
function renderMapSummary() {
  const data = mapState.source, explicit = data.edges.filter((edge) => edge.kind !== "similarity").length;
  const hidden = mapState.nodes.length - mapState.nodes.filter(celestialVisible).length;
  $("#map-summary").textContent = data.nodes.length
    ? `${data.nodes.length} stars · ${explicit} linked paths · ${data.edges.length - explicit} semantic threads · ${mapState.groups.project.length} project${mapState.groups.project.length === 1 ? "" : "s"}${data.truncated ? ` · ${data.nodes.length} most recent shown` : ""}${hidden ? ` · ${hidden} hidden` : ""}`
    : "No current memories in this scope.";
}
function renderMapLegend() {
  const legend = $("#map-legend"), by = mapState.colorBy; legend.replaceChildren();
  for (const [key, count] of mapState.groups[by]) {
    const chip = node("button", undefined, "map-chip"), shown = !mapState.hidden[by].has(key);
    chip.type = "button"; chip.style.setProperty("--swatch", mapState.colors[by].get(key));
    chip.setAttribute("aria-pressed", String(shown));
    chip.title = `${shown ? "Hide" : "Show"} ${celestialGroupName(key, by)}`;
    chip.append(node("span", celestialGroupName(key, by)), node("small", String(count)));
    chip.onclick = () => {
      if (mapState.hidden[by].has(key)) mapState.hidden[by].delete(key); else mapState.hidden[by].add(key);
      if (mapState.selected && !celestialVisible(mapState.selected)) mapState.selected = null;
      renderMapLegend(); renderMapIndex(); renderMapSelection(); renderMapSummary(); drawCelestial();
    };
    legend.append(chip);
  }
  if (mapState.hidden.project.size || mapState.hidden.type.size) {
    const reset = node("button", "Show all", "map-chip plain"); reset.type = "button";
    reset.onclick = () => {
      mapState.hidden = { project: new Set(), type: new Set() };
      renderMapLegend(); renderMapIndex(); renderMapSummary(); drawCelestial();
    };
    legend.append(reset);
  }
  const edgeKey = node("div", undefined, "map-edge-key");
  for (const kind of ["relates_to", "derived_from", "contradicts", "similarity"]) {
    const item = node("span", celestialEdgeNames[kind], `edge ${kind}`);
    item.style.setProperty("--swatch", celestialEdgeStyles[kind][0]); edgeKey.append(item);
  }
  legend.append(edgeKey);
}
function renderMapSelection() {
  const panel = $("#map-selection"), item = mapState?.selected; panel.replaceChildren();
  if (!item) {
    panel.append(node("p", "Select a star or a memory in the list to see how it connects.", "muted"));
    return;
  }
  const title = node("h3", item.title); title.style.setProperty("--swatch", celestialColor(item));
  panel.append(title, node("p", `${projectName(item.project_id)} · ${item.type} · ${item.status} · ${item.evidence}${item.stale ? " · review due" : ""}`, "muted"));
  const actions = node("div", undefined, "actions");
  const open = node("button", "Open memory"); open.onclick = guard(() => showDetail(item.id));
  const clear = node("button", "Clear selection", "secondary"); clear.onclick = () => selectCelestial(null);
  actions.append(open, clear); panel.append(actions);
  const relations = [...mapState.relations.get(item)].filter((relation) => celestialVisible(relation.node))
    .sort((a, b) => (a.edge.kind === "similarity") - (b.edge.kind === "similarity") || (b.edge.similarity || 0) - (a.edge.similarity || 0));
  panel.append(node("h4", `Relations · ${relations.length}`));
  if (!relations.length) { panel.append(node("p", "No relations to visible memories.", "muted")); return; }
  const list = node("ul", undefined, "map-relations");
  for (const relation of relations) {
    const row = node("button", undefined, "map-relation"), kind = relation.edge.kind;
    row.type = "button"; row.style.setProperty("--swatch", celestialEdgeStyles[kind][0]);
    row.append(node("small", kind === "similarity" ? `${Math.round((relation.edge.similarity || 0) * 100)}% similar` : celestialEdgeNames[kind]),
      node("span", relation.node.title));
    row.onclick = () => selectCelestial(relation.node, true);
    const entry = node("li"); entry.append(row); list.append(entry);
  }
  panel.append(list);
}
function renderMapIndex() {
  const list = $("#map-index"); list.replaceChildren();
  const query = mapState.query.trim().toLowerCase();
  const visible = mapState.nodes.filter(celestialVisible);
  const rows = query ? visible.filter((item) => `${item.title} ${projectName(item.project_id)} ${item.type}`.toLowerCase().includes(query)) : visible;
  mapState.matches = query ? new Set(rows) : null;
  rows.sort((a, b) => projectName(a.project_id).localeCompare(projectName(b.project_id)) || b.degree - a.degree || a.title.localeCompare(b.title));
  for (const item of rows) {
    const row = node("button", undefined, "map-index-row"), body = node("span", undefined, "grow");
    row.type = "button"; row.dataset.id = item.id; row.style.setProperty("--swatch", celestialColor(item));
    body.append(node("strong", item.title), node("small", `${projectName(item.project_id)} · ${item.type} · ${item.degree} relation${item.degree === 1 ? "" : "s"}`));
    row.append(body); row.onclick = () => selectCelestial(item, true);
    row.onmouseenter = () => { mapState.hover = item; drawCelestial(); };
    row.onmouseleave = () => { mapState.hover = null; drawCelestial(); };
    const entry = node("li"); entry.append(row); list.append(entry);
  }
  $("#map-count").textContent = query ? `${rows.length} of ${visible.length}` : `${visible.length}`;
  if (!rows.length) list.append(node("li", query ? "No memories match this search." : "All groups are hidden.", "muted map-empty"));
  syncMapIndex();
}
function syncMapIndex() {
  for (const row of $("#map-index").querySelectorAll(".map-index-row")) {
    const current = mapState?.selected?.id === row.dataset.id;
    if (current) row.setAttribute("aria-current", "true"); else row.removeAttribute("aria-current");
  }
  // Scroll only the list; scrollIntoView would also scroll the side panel and hide the search field.
  const list = $("#map-index"), current = list.querySelector("[aria-current]");
  if (!current) return;
  const top = current.offsetTop, bottom = top + current.offsetHeight;
  if (top < list.scrollTop) list.scrollTop = top;
  else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
}
async function showMap() {
  const dialog = $("#map-dialog");
  if (!dialog.open) dialog.showModal();
  const previous = mapState;
  if (previous) previous.simulation.stop();
  mapState = null;
  $("#map-summary").textContent = "";
  $("#map-legend").replaceChildren(); $("#map-index").replaceChildren(); $("#map-selection").replaceChildren();
  $("#map-count").textContent = ""; $("#map-tooltip").hidden = true;
  const canvas = $("#map-canvas"); canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  setMapState("Charting relationships…");
  const project = $("#project-filter").value;
  let data;
  try {
    data = await api(`/api/map?limit=400${project ? `&project_id=${project}` : ""}`);
  } catch (error) {
    if (dialog.open) setMapState(`The map could not be loaded: ${error.message}`, true);
    return;
  }
  if (!dialog.open) return;
  mapState = prepareCelestial(data);
  $("#map-search").value = "";
  $("#map-color").textContent = `Color: ${mapState.colorBy}`;
  $("#map-threads").setAttribute("aria-pressed", String(mapState.threads));
  setMapState(data.nodes.length ? "" : "No current memories in this scope yet. Captured memories appear here as stars.");
  renderMapSummary(); renderMapLegend(); renderMapIndex(); renderMapSelection();
  resizeCelestial(); fitCelestial(false);
}
const mapCanvas = $("#map-canvas");
const mapZoom = d3.zoom().scaleExtent([0.1, 8]).on("zoom", (event) => {
  if (!mapState) return;
  mapState.transform = event.transform;
  if (event.sourceEvent) $("#map-tooltip").hidden = true;
  drawCelestial();
});
const mapDrag = d3.drag()
  .subject((event) => {
    const item = celestialFind(event.x, event.y);
    return item ? { item, x: mapState.transform.applyX(item.x), y: mapState.transform.applyY(item.y) } : null;
  })
  .on("start", (event) => {
    const item = event.subject.item;
    mapState.dragging = item; item.fx = item.x; item.fy = item.y;
    $("#map-tooltip").hidden = true; mapCanvas.classList.add("dragging");
    mapState.simulation.alphaTarget(0.2).restart();
  })
  .on("drag", (event) => {
    const item = event.subject.item;
    item.fx = mapState.transform.invertX(event.x); item.fy = mapState.transform.invertY(event.y);
  })
  .on("end", (event) => {
    const item = event.subject.item;
    item.fx = null; item.fy = null;
    if (mapState) { mapState.dragging = null; mapState.simulation.alphaTarget(0); }
    mapCanvas.classList.remove("dragging");
  });
d3.select(mapCanvas).call(mapDrag).call(mapZoom).on("dblclick.zoom", null);
new ResizeObserver(() => resizeCelestial()).observe($(".map-shell"));
mapCanvas.addEventListener("pointermove", (event) => {
  if (!mapState || event.pointerType === "touch" || event.buttons) return;
  const hit = celestialFind(...celestialPointer(event));
  mapCanvas.classList.toggle("pointing", Boolean(hit));
  if (hit !== mapState.hover) { mapState.hover = hit; drawCelestial(); }
  showMapTooltip(event, hit);
});
mapCanvas.addEventListener("pointerleave", () => {
  if (!mapState) return;
  mapState.hover = null; $("#map-tooltip").hidden = true; drawCelestial();
});
mapCanvas.addEventListener("click", (event) => {
  if (!mapState) return;
  selectCelestial(celestialFind(...celestialPointer(event)));
});
$("#map-button").onclick = guard(showMap);
$("#map-fit").onclick = () => fitCelestial();
$("#map-zoom-in").onclick = () => mapState && celestialTransition().call(mapZoom.scaleBy, 1.5);
$("#map-zoom-out").onclick = () => mapState && celestialTransition().call(mapZoom.scaleBy, 1 / 1.5);
$("#map-reset").onclick = () => {
  if (!mapState) return;
  const previous = mapState; previous.simulation.stop();
  mapState = prepareCelestial(previous.source, previous);
  mapState.width = previous.width; mapState.height = previous.height; mapState.dpr = previous.dpr;
  mapState.background = previous.background;
  renderMapIndex(); renderMapSelection(); fitCelestial();
};
$("#map-color").onclick = () => {
  if (!mapState) return;
  mapState.colorBy = mapState.colorBy === "project" ? "type" : "project";
  $("#map-color").textContent = `Color: ${mapState.colorBy}`;
  renderMapLegend(); renderMapIndex(); renderMapSelection(); drawCelestial();
};
$("#map-threads").onclick = () => {
  if (!mapState) return;
  mapState.threads = !mapState.threads;
  $("#map-threads").setAttribute("aria-pressed", String(mapState.threads)); drawCelestial();
};
$("#map-search").addEventListener("input", () => {
  if (!mapState) return;
  mapState.query = $("#map-search").value; renderMapIndex(); drawCelestial();
});
$("#map-search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !mapState?.matches?.size) return;
  event.preventDefault();
  selectCelestial($("#map-index .map-index-row") && mapState.byId.get($("#map-index .map-index-row").dataset.id), true);
});
$("#map-index").addEventListener("keydown", (event) => {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  const rows = [...$("#map-index").querySelectorAll(".map-index-row")], index = rows.indexOf(document.activeElement);
  if (!rows.length) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1
    : Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
  rows[next].focus();
});
$("#map-dialog").addEventListener("close", () => {
  if (mapState) mapState.simulation.stop();
  mapState = null; $("#map-tooltip").hidden = true;
});
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
