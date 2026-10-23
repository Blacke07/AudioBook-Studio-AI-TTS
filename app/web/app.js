"use strict";

/* ---------- small helpers ---------- */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const view = $("#view");
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const NARRATOR = "Narrator", UNASSIGNED = "Unassigned", PAUSE = "Scene break";
const HEADING = /^[—–]\s+(?:[A-Z][a-z]+\s+)?[IVXLC]+\s+[—–]$/;

const ICONS = {
  sound: '<path d="M4 9v6M8 6v12M12 3v18M16 7v10M20 10v4"/>',
  video: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3z"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  wand: '<path d="M15 4V2M15 10V8M11 6h2M17 6h2M4 20 14 10M18 14l1 1"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  scissors: '<circle cx="6" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><path d="M8 8.5 20 18M8 15.5 20 6"/>',
  redo: '<path d="M20 11a8 8 0 1 1-2.3-5.6M20 4v5h-5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  dice: '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="15" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/><circle cx="9" cy="15" r="1" fill="currentColor"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  flag: '<path d="M5 21V4h11l-1.5 4L16 12H5"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  book: '<path d="M4 19V5a2 2 0 0 1 2-2h5v18H6a2 2 0 0 1-2-2zM11 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  back: '<path d="m14 6-6 6 6 6"/>',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24">${ICONS[name]}</svg>`;

async function api(path, options = {}) {
  const init = { headers: { "Content-Type": "application/json" }, ...options };
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `Error ${response.status}`);
  return data;
}

function toast(message, kind = "") {
  const element = document.createElement("div");
  element.className = `toast ${kind}`;
  element.textContent = message;
  $("#toasts").append(element);
  setTimeout(() => element.remove(), kind === "bad" ? 9000 : 4200);
}

async function guard(action, busyButton) {
  const label = busyButton?.innerHTML;
  if (busyButton) { busyButton.disabled = true; busyButton.innerHTML = `<span class="spinner"></span> Working…`; }
  try { return await action(); }
  catch (error) { toast(error.message, "bad"); }
  finally { if (busyButton) { busyButton.disabled = false; busyButton.innerHTML = label; } }
}

function modal(title, body, actions = [{ label: "Close", value: null }]) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><h2>${esc(title)}</h2><div class="stack">${body}</div>
      <div class="row end">${actions.map((a, i) => `<button class="btn ${a.primary ? "primary" : ""}" data-i="${i}">${a.label}</button>`).join("")}</div></div>`;
    const previousFocus = document.activeElement;
    const close = (value) => { overlay.remove(); previousFocus?.focus({preventScroll:true}); resolve(value); };
    overlay.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.stopPropagation(); close(null); }
    });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
      const button = event.target.closest("[data-i]");
      if (button) {
        const action = actions[+button.dataset.i];
        close(action.value === "form" ? Object.fromEntries($$("[name]", overlay).map((f) => [f.name, f.type === "checkbox" ? f.checked : f.value])) : action.value);
      }
    });
    document.body.append(overlay);
    overlay.querySelector("input, textarea, select, button")?.focus();
  });
}

function duration(seconds) {
  if (!seconds && seconds !== 0) return "—";
  seconds = Math.round(seconds);
  if (seconds < 60) return `${seconds} s`;
  const hours = Math.floor(seconds / 3600), minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours} h ${String(minutes).padStart(2, "0")} min` : `${minutes} min`;
}

const PALETTE = [14, 200, 330, 150, 42, 265, 95, 185, 300, 60, 230, 0];
function colorFor(name) {
  if (name === NARRATOR) return "var(--muted)";
  if (name === UNASSIGNED) return "var(--warn)";
  let hash = 0;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  return `hsl(${PALETTE[hash % PALETTE.length]} 58% 50%)`;
}

const STATE_CLASS = { new: "", modified: "warn", needs_review: "warn", analyzed: "info", partial: "info",
  outdated: "warn", generated: "ok", exported: "ok", error: "bad" };
const STATE_COLOR = { new: "var(--line)", modified: "var(--warn)", needs_review: "var(--warn)", analyzed: "var(--info)",
  partial: "var(--info)", outdated: "var(--warn)", generated: "var(--ok)", exported: "var(--ok)", error: "var(--bad)" };
const STATE_LABEL = { new: "Not analyzed", modified: "Text changed", needs_review: "Needs review", analyzed: "Ready to generate",
  partial: "Partly generated", outdated: "Outdated", generated: "Generated", exported: "Exported", error: "Error" };
const chip = (state, label) => `<span class="chip ${STATE_CLASS[state] || ""}">${esc(label || STATE_LABEL[state])}</span>`;

/* ---------- worker panel ---------- */
let workerState = { running: false, log: [] };
let lastWorkerSignature = "";
async function pollWorker() {
  try {
    workerState = await api("/api/status");
    renderWorker();
    const signature = `${workerState.running}|${workerState.done}|${workerState.phase}|${workerState.log.length}`;
    if (signature !== lastWorkerSignature) {
      const finished = lastWorkerSignature && signature.split("|")[0] !== lastWorkerSignature.split("|")[0];
      lastWorkerSignature = signature;
      if (finished || workerState.running) refreshOnProgress?.();
    }
  } catch { /* server restarting */ }
  setTimeout(pollWorker, workerState.running ? 1500 : 4000);
}
let refreshOnProgress = null;
let refreshTimer = null;
function scheduleRefresh(callback) {
  refreshOnProgress = () => { clearTimeout(refreshTimer); refreshTimer = setTimeout(callback, 1200); };
}

function renderWorker() {
  const s = workerState;
  const box = $("#worker");
  if (s.running) {
    const fraction = Math.round((s.fraction || 0) * 100);
    box.innerHTML = `<b><span class="pulse-dot"></span>${esc(s.phase || "Working")}</b>
      <div class="now">${esc(s.chapter || "")}</div>
      <div class="bar"><i style="width:${fraction}%"></i></div>
      <div class="now small">${s.total ? `${Math.min((s.done || 0) + 1, s.total)} of ${s.total} · ` : ""}${fraction}%${s.eta_seconds ? ` · ~${duration(s.eta_seconds)} remaining` : ""}</div>
      <div class="row"><button class="btn" id="stop">${icon("stop")} Stop</button><button class="btn ghost" id="log">${icon("list")} Log</button></div>`;
    $("#stop").onclick = () => guard(() => api("/api/stop", { method: "POST" }).then(() => toast("Stopping. Audio finishes its current passage; video cancels. Completed work is kept.")));
  } else {
    const last = s.log.length ? s.log[s.log.length - 1].slice(10) : "Start a job from the Volumes page.";
    box.innerHTML = `<b>No active job</b><div class="now small" title="${esc(last)}">${esc(last)}</div>
      <div class="row"><button class="btn ghost" id="log">${icon("list")} Log</button></div>`;
  }
  $("#log").onclick = () => modal("Activity log", `<div class="log">${esc(s.log.join("\n") || "Nothing yet.")}</div>`);
}

/* ---------- router ---------- */
const routes = [
  [/^#\/?$/, viewVolumes, "volume"],
  [/^#\/volume\/(.+)$/, (m) => viewVolume(decodeURIComponent(m[1])), "volume"],
  [/^#\/chapter\/([^/]+)\/(.+)$/, (m) => viewChapter(decodeURIComponent(m[1]), decodeURIComponent(m[2])), "volume"],
  [/^#\/characters$/, viewCharacters, "characters"],
  [/^#\/narrator$/, viewNarrator, "narrator"],
  [/^#\/settings$/, viewSettings, "settings"],
  [/^#\/project$/, viewProject, "project"],
];
async function route() {
  if (CharacterRegistry.dirty() && location.hash !== '#/characters' && !await CharacterRegistry.leave()) {
    location.hash = '#/characters'; return;
  }
  refreshOnProgress = null;
  closeMenu();
  const hash = location.hash || "#/";
  for (const [pattern, render, section] of routes) {
    const match = hash.match(pattern);
    if (match) {
      $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === section));
      view.innerHTML = `<div class="empty"><span class="spinner"></span></div>`;
      try { await render(match); } catch (error) { view.innerHTML = `<div class="banner">${esc(error.message)}</div>`; }
      window.scrollTo(0, 0);
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);

/* ---------- volumes ---------- */
async function viewVolumes() {
  const data = await api("/api/overview");
  const cards = data.volumes.map((volume) => {
    const counts = volume.counts;
    const done = counts.generated + counts.exported;
    const bar = Object.entries(counts).filter(([, n]) => n).map(([state, n]) =>
      `<i style="width:${(n / Math.max(volume.chapters, 1)) * 100}%;background:${STATE_COLOR[state]}" title="${STATE_LABEL[state]}: ${n}"></i>`).join("");
    return `<div class="card volume-card" data-volume="${esc(volume.name)}">
      <div class="row between"><h2>${esc(volume.name)}</h2><div class="row"><button class="btn small" data-edit-volume="${esc(volume.name)}">Edit</button><button class="btn small" data-remove-volume="${esc(volume.name)}">Remove</button></div></div><div class="muted small">${esc(volume.source)}</div>
      ${volume.error ? `<div class="banner">${esc(volume.error)}</div>` : ""}
      <div class="stats">
        <div class="stat"><b>${volume.chapters}</b><span>chapters</span></div>
        <div class="stat"><b>${duration(volume.estimated_seconds)}</b><span>estimated audio</span></div>
        <div class="stat"><b>${done}</b><span>generated</span></div>
        <div class="stat"><b>${counts.needs_review}</b><span>needs review</span></div>
      </div><div class="stackbar">${bar}</div></div>`;
  }).join("");
  view.innerHTML = `
    <div class="page-head"><div><h1>Your volumes</h1>
      <p>Each volume is a folder of TXT or DOCX chapters. The app reads them in order, generates audio and exports each chapter.</p></div></div>
    <div class="card"><h3>Getting started</h3><p class="muted small" style="margin:4px 0 14px">Set up your voices once, then process your chapters.</p>
      <div class="steps">
        <div><b><a href="#/narrator">Choose the narrator</a></b><span>Compare takes of the same passage and keep your favorite.</span></div>
        <div><b><a href="#/characters">Review the cast</a></b><span>Set each character's identity and reference voice for the whole book.</span></div>
        <div><b>Run automatically</b><span>Open a volume and start the job. You can stop and resume later.</span></div>
        <div><b>Review flagged lines</b><span>Review uncertain speakers before the selected batch proceeds to audio.</span></div>
      </div></div>
    <div class="grid cards" style="margin-top:18px">${cards}
      <div class="card add-card" id="add-volume"><div>${icon("plus")}<h3 style="margin-top:8px">Add a volume</h3><div class="small">Choose the chapter folder</div></div></div>
    </div>
    ${data.ffmpeg ? "" : `<div class="banner" style="margin-top:16px">${icon("info")} FFmpeg was not found. Only WAV export is available.</div>`}`;
  $$(".volume-card").forEach((card) => card.onclick = () => location.hash = `#/volume/${encodeURIComponent(card.dataset.volume)}`);
  $$('[data-edit-volume]').forEach(button => button.onclick = e => { e.stopPropagation(); guard(() => editVolumeDialog(data.volumes.find(v => v.name === button.dataset.editVolume)),button); });
  $$('[data-remove-volume]').forEach(button => button.onclick = e => { e.stopPropagation(); guard(() => removeVolumeDialog(data.volumes.find(v => v.name === button.dataset.removeVolume)),button); });
  $("#add-volume").onclick = addVolumeDialog;
  scheduleRefresh(viewVolumes);
}

async function addVolumeDialog() {
  const body = `<p class="muted">Choose the folder containing your chapters, such as Volume 1. Source files are never modified.</p>
    <label class="field"><span>Chapter folder</span><div class="row" style="flex-wrap:nowrap"><input type="text" name="source" id="vol-source" placeholder="C:\\...\\Volume 1">
    <button class="btn" type="button" id="pick">${icon("folder")} Browse…</button></div></label>
    <label class="field"><span>Volume name</span><input type="text" name="name" id="vol-name" placeholder="defaults to the folder name"></label>`;
  const pending = modal("Add a volume", body, [{ label: "Cancel", value: null }, { label: "Add volume", value: "form", primary: true }]);
  $("#pick").onclick = () => guard(async () => {
    const result = await api("/api/pick-folder", { method: "POST" });
    if (result.path) {
      $("#vol-source").value = result.path;
      if (!$("#vol-name").value) $("#vol-name").value = result.path.split(/[\\/]/).pop();
    }
  });
  const form = await pending;
  if (!form) return;
  await guard(async () => {
    const result = await api("/api/volumes", { method: "POST", body: form });
    toast(`Volume added: ${result.name}`);
    location.hash = `#/volume/${encodeURIComponent(result.name)}`;
  });
}

let volumeFilter = "all";
let selected = new Set();
const videoChip = (c) => `<span class="chip ${c.video.state === "ready" ? "ok" : c.video.state === "outdated" ? "warn" : ""}">${esc(c.video.label)}</span>`;

/* The discreet back control follows the logical parent, not history.back():
   a chapter returns to its volume, a volume returns to the volumes list, other pages have none. */
function parentRoute(hash = location.hash || "#/") {
  const chapter = /^#\/chapter\/([^/]+)\/.+$/.exec(hash);
  if (chapter) {
    let volume = chapter[1];
    try { volume = decodeURIComponent(volume); } catch { /* keep the raw name */ }
    return { href: `#/volume/${encodeURIComponent(volume)}`, label: `Back to ${volume}` };
  }
  if (/^#\/volume\/.+$/.test(hash)) return { href: "#/", label: "Back to volumes" };
  return null;
}
const backButton = (parent) => parent
  ? `<a class="back" id="back" href="${esc(parent.href)}" aria-label="${esc(parent.label)}" title="${esc(parent.label)}">${icon("back")}</a>`
  : "";
async function viewVolume(name) {
  const data = await api(`/api/volumes/${encodeURIComponent(name)}`);
  const chapters = data.chapters;
  const counts = {};
  chapters.forEach((c) => counts[c.state] = (counts[c.state] || 0) + 1);
  const estimated = chapters.reduce((sum, c) => sum + (c.estimated_seconds || 0), 0);
  const generated = chapters.filter((c) => ["generated", "exported"].includes(c.state)).reduce((sum, c) => sum + (c.seconds || 0), 0);
  const remaining = chapters.filter((c) => !["generated", "exported"].includes(c.state)).reduce((sum, c) => sum + (c.remaining_seconds ?? c.estimated_seconds ?? 0), 0) * data.render_factor;
  selected = new Set([...selected].filter((stem) => chapters.some((c) => c.stem === stem)));
  const visible = chapters.filter((c) => volumeFilter === "all" || c.state === volumeFilter);
  const visibleSelected = visible.filter((c) => selected.has(c.stem)).length;
  const bar = Object.entries(counts).map(([state, n]) => `<i style="width:${n / chapters.length * 100}%;background:${STATE_COLOR[state]}"></i>`).join("");
  const target = selected.size ? `for ${selected.size} selected chapter${selected.size === 1 ? "" : "s"}` : "for the whole volume";
  view.innerHTML = `${backButton(parentRoute())}
    <div class="crumbs"><a href="#/">Volumes</a> ›</div>
    <div class="page-head"><div><h1>${esc(name)}</h1><p class="small">${esc(data.volume.source)}</p></div>
      <div class="row"><button class="btn" id="edit-volume">Edit volume</button><button class="btn" id="remove-volume">Remove volume</button><button class="btn" id="open-source">${icon("folder")} Chapters</button><button class="btn" id="open-export">${icon("download")} Exported files</button><button class="btn" id="run-volume" ${chapters.length && !chapters.some((c) => !c.can_export) ? "" : `disabled title="Generate current audio for every chapter in this volume."`}>${icon("book")} Export the whole volume</button></div></div>
    <div class="card">
      <div class="stats" style="margin-top:0">
        <div class="stat"><b>${chapters.length}</b><span>chapters</span></div>
        <div class="stat"><b>${duration(estimated)}</b><span>estimated audio</span></div>
        <div class="stat"><b>${duration(generated)}</b><span>already generated</span></div>
        <div class="stat"><b>~${duration(remaining)}</b><span>estimated time remaining</span></div>
      </div>
      <div class="stackbar">${bar}</div>
      <hr class="soft">
      <div class="row between">
        <div><h3>Run automatically <span class="muted small" style="font-family:var(--sans);font-weight:400">${target}</span></h3>
          <div class="muted small" style="max-width:600px">Analyze dialogue, generate audio and export each chapter. The entire batch waits if any chapter needs speaker review or an analysis repair. You can stop at any time.</div></div>
        <button class="btn primary big" id="run-all">${icon("play")} Run automatically</button>
      </div>
      ${ChapterWorkflow.html(chapters, name)}
      <p class="muted small">The entire selected batch must finish text review before audio starts. Without a selection, the batch is the whole volume. Automatic processing pauses here if any chapter needs review. ${data.video_enabled ? "It also creates video after current audio is exported." : "Automatic video is off."}</p>
    </div>
    <div class="card" id="volume-cast"></div>
    ${counts.needs_review ? `<div class="banner" style="margin-top:16px">${icon("flag")}<div><b>${counts.needs_review} ${counts.needs_review === 1 ? "chapter needs" : "chapters need"} your review.</b> Some lines have uncertain speakers. Open those chapters and choose the speaker for each highlighted line.</div></div>` : ""}
    ${counts.error ? `<div class="banner" style="margin-top:16px;background:var(--bad-soft);color:var(--bad)">${icon("info")}<div><b>${counts.error} ${counts.error === 1 ? "chapter has an error" : "chapters have errors"}.</b> Choose Diagnose / repair in Text, or beside the affected chapter.</div></div>` : ""}
    <div class="card" style="margin-top:16px">
      <div class="filters">${[["all", `All (${chapters.length})`], ...Object.keys(STATE_LABEL).filter((s) => counts[s]).map((s) => [s, `${STATE_LABEL[s]} (${counts[s]})`])]
        .map(([key, label]) => `<span class="chip ${key === "all" ? "" : STATE_CLASS[key]} ${volumeFilter === key ? "on" : ""}" data-filter="${key}">${label}</span>`).join("")}</div>
      <table class="chapters"><thead><tr><th class="check"><label class="chapter-select"><input type="checkbox" id="all" aria-label="Select all visible chapters" ${visible.length ? "" : "disabled"}></label></th><th>No.</th><th>Title</th><th>Duration</th><th>Status</th><th></th></tr></thead>
      <tbody>${visible.map((c) => `<tr class="clickable" data-stem="${esc(c.stem)}">
        <td class="check"><label class="chapter-select"><input type="checkbox" data-select="${esc(c.stem)}" aria-label="Select ${esc(c.title)}" ${selected.has(c.stem) ? "checked" : ""}></label></td>
        <td class="num">${c.number ?? ""}</td>
        <td>${esc(c.title)}${c.error ? `<div class="small" style="color:var(--bad)">${esc(c.analysis_problem ? "Speaker analysis needs repair." : c.error)}</div><button class="btn" data-diagnose="${esc(c.stem)}">Diagnose / repair</button>` : ""}</td>
        <td class="dur">${c.seconds ? duration(c.seconds) : `~${duration(c.estimated_seconds)}`}</td>
        <td>${chip(c.state, c.label)}${c.state === "partial" ? `<span class="bar mini-bar"><i style="width:${c.progress * 100}%"></i></span>` : ""}
          ${c.unclear ? `<span class="chip warn" title="unassigned dialogue">${c.unclear} unassigned</span>` : ""}
          ${c.flagged ? `<span class="chip" title="passages with unusual pacing">${icon("flag")} ${c.flagged}</span>` : ""}
          <div style="margin-top:4px">${videoChip(c)}</div>${c.video.error ? `<div class="small" style="color:var(--bad)">Video: ${esc(c.video.error)}</div>` : ""}</td>
        <td>${c.audio ? `<button class="btn ghost icon-only" data-play="${esc(c.audio)}" title="Listen">${icon("play")}</button>` : ""}</td>
      </tr>`).join("")}</tbody></table>
      ${visible.length ? "" : `<div class="empty">No chapters in this category.</div>`}
    </div>
    <audio id="volume-player" controls class="hidden" style="width:100%;margin-top:14px"></audio>`;

  const run = (steps, button) => guard(async () => {
    const stems = steps.includes("volume") ? chapters.map(c => c.stem) : [...selected];
    const force = steps.length === 1 && steps[0] === "analyze";
    const targets = stems.length ? chapters.filter(c => stems.includes(c.stem)) : chapters;
    if (force && targets.some(c => c.state !== "new") && !await modal("Analyze Text again?",
      `<p>Analyze ${targets.length} chapter${targets.length === 1 ? "" : "s"} in this batch again?</p><p>Successful analysis replaces existing speaker assignments and take selections, including manual corrections. Spoken-text edits that no longer match will need review. Audio and video may need regeneration.</p><p class="muted small">Your manuscript files and saved voices are unchanged.</p>`,
      [{label:"Cancel", value:false}, {label:"Analyze again", value:true, primary:true}])) return;
    await api("/api/run", { method: "POST", body: { volume: name, stems, steps, force,
      automatic: steps.join(",") === "analyze,render,export" } });
    toast("Job queued. Follow progress in the lower-left panel.");
    pollNow();
  }, button);
  ChapterWorkflow.bind();
  $("#review-text").onclick = () => { volumeFilter = "needs_review"; viewVolume(name); };
  $("#diagnose-text").onclick = (e) => guard(() => ChapterWorkflow.diagnoseBatch(name,
    chapters.filter(c => c.error && (!selected.size || selected.has(c.stem)))), e.currentTarget);
  $("#run-all").disabled = !chapters.length;
  $("#run-volume").disabled = !chapters.length || chapters.some(c => !c.can_export);
  $("#run-all").onclick = (e) => run(["analyze", "render", "export"], e.currentTarget);
  $("#run-analyze").onclick = (e) => run(["analyze"], e.currentTarget);
  $("#run-render").onclick = (e) => run(["render"], e.currentTarget);
  $("#run-export").onclick = (e) => run(["export"], e.currentTarget);
  $("#run-video").onclick = (e) => run(["video"], e.currentTarget);
  $("#youtube").onclick = (e) => guard(async () => {
    const result = await api("/api/video/youtube", { method: "POST", body: { volume: name, stems: [...selected] } });
    await modal("YouTube chapter list", `<p>Saved beside your chapter videos, in their volume order. These timestamps assume the videos are joined without gaps.</p><p class="muted small">YouTube has its own chapter requirements. Very short chapters may not appear as chapters on YouTube.</p><a class="btn primary" href="${esc(result.url)}" download="YouTube chapters.txt">${icon("download")} Download chapter list</a>`);
  }, e.currentTarget);
  $("#run-volume").onclick = async (e) => {
    const ok = await modal("Export the whole volume", `<p>All generated chapters will be combined into one file with chapter markers (choose the format in <a href="#/settings">Settings</a>; M4B by default, an audiobook format with chapter support).</p><p class="muted small">Exporting a complete volume may take a few minutes.</p>`,
      [{ label: "Cancel", value: false }, { label: "Export volume", value: true, primary: true }]);
    if (ok) run(["volume"], e.currentTarget);
  };
  $("#edit-volume").onclick = e => guard(() => editVolumeDialog(data.volume),e.currentTarget);
  $("#remove-volume").onclick = e => guard(() => removeVolumeDialog(data.volume),e.currentTarget);
  VoiceRules.mount(name).catch(error => toast(error.message));
  $("#open-source").onclick = () => guard(() => api("/api/open", { method: "POST", body: { what: "source", volume: name } }));
  $("#open-export").onclick = () => guard(() => api("/api/open", { method: "POST", body: { what: "export", volume: name } }));
  $$("[data-filter]").forEach((element) => element.onclick = () => { volumeFilter = element.dataset.filter; viewVolume(name); });
  $("#all").checked = visible.length > 0 && visibleSelected === visible.length;
  $("#all").indeterminate = visibleSelected > 0 && visibleSelected < visible.length;
  $("#all").onchange = (event) => { visible.forEach((c) => event.target.checked ? selected.add(c.stem) : selected.delete(c.stem)); viewVolume(name); };
  $$("[data-select]").forEach((box) => box.onchange = () => {
    box.checked ? selected.add(box.dataset.select) : selected.delete(box.dataset.select); viewVolume(name);
  });
  $$("tr.clickable").forEach((row) => row.onclick = (event) => {
    const diagnostic = event.target.closest("[data-diagnose]");
    if (diagnostic) { guard(() => ChapterWorkflow.diagnose(name, row.dataset.stem), diagnostic); return; }
    const cell = event.target.closest("td.check");
    if (cell) {
      if (!event.target.closest("input, label")) $("[data-select]", cell).click();
      return;
    }
    const play = event.target.closest("[data-play]");
    if (play) { const player = $("#volume-player"); player.classList.remove("hidden"); player.src = play.dataset.play; player.play(); return; }
    location.hash = `#/chapter/${encodeURIComponent(name)}/${encodeURIComponent(row.dataset.stem)}`;
  });
  scheduleRefresh(() => { if ((!$("#volume-player") || $("#volume-player").paused) && !ChapterWorkflow.isOpen()) viewVolume(name); });
}

/* ---------- chapter editor ---------- */
let lineFilter = "all";
async function viewChapter(volume, stem) {
  const data = await api(`/api/chapter?volume=${encodeURIComponent(volume)}&stem=${encodeURIComponent(stem)}`);
  const c = data.chapter, lines = data.lines;
  const unclear = lines.filter((l) => l.speaker === UNASSIGNED).length;
  const contextual = lines.filter((l) => l.basis === "context").length;
  const reviewCount = unclear + lines.filter((l) => l.flagged).length + contextual;
  const sceneNumbers = [...new Set(lines.map((l) => l.scene ?? 0))].sort((a, b) => a - b);
  const sceneLabel = (scene) => {
    const names = (lines.find((l) => l.scene === scene)?.context_ids || [])
      .map((id) => (data.contexts || []).find((c) => c.id === id)?.name).filter(Boolean);
    return names.length ? names.join(", ") : "No context";
  };
  const speakers = [...new Set(lines.map((l) => l.speaker).filter((s) => ![NARRATOR, UNASSIGNED, PAUSE].includes(s)))];
  const shown = lines.map((line, index) => ({ line, index })).filter(({ line }) =>
    lineFilter === "all" || (lineFilter === "dialogue" && ![NARRATOR, PAUSE].includes(line.speaker)) || (lineFilter === "review" && (line.speaker === UNASSIGNED || line.flagged || line.basis === "context")));
  const kind = (line) => line.speaker === PAUSE ? "pause" : HEADING.test(line.text) ? "heading" : line.speaker === NARRATOR ? "narration" : "speech";
  view.innerHTML = `${backButton(parentRoute())}
    <div class="crumbs"><a href="#/">Volumes</a> › <a href="#/volume/${encodeURIComponent(volume)}">${esc(volume)}</a> ›</div>
    <div class="page-head"><div><h1>${c.number != null ? `${c.number} · ` : ""}${esc(c.title)}</h1>
      <p>${chip(c.state, c.label)} ${c.seconds ? `<span class="chip">${duration(c.seconds)}</span>` : `<span class="chip">~${duration(c.estimated_seconds)}</span>`}
      ${videoChip(c)} ${c.reason ? `<span class="small" style="margin-left:6px">${esc(c.reason)}</span>` : ""}</p></div>
      <div class="row"><button class="btn" id="reanalyze">${icon("wand")} ${!data.manual_draft ? "Analyze again" : "Analyze Text"}</button>
        <button class="btn primary" id="render" ${c.can_generate ? "" : 'disabled title="Finish text analysis and resolve speakers first."'}>${icon("play")} Generate chapter</button>
        <button class="btn" id="create-video" ${["generated", "exported"].includes(c.state) ? "" : 'disabled title="Generate current audio first"'}>${icon("play")} Create video</button>
        <button class="btn ghost icon-only" id="open" title="Open working folder">${icon("folder")}</button></div></div>
    ${c.error ? `<div class="banner" style="background:var(--bad-soft);color:var(--bad)">${esc(c.error)}<button class="btn" id="diagnose-chapter">Diagnose / repair</button></div>` : ""}
    ${data.manual_draft || c.analysis_problem ? `<div class="banner">${icon("book")}<div><b>Manual speaker editor</b><p>The text is available even if AI analysis fails. Choose a speaker beside each line or split a line; changes save without using Gemma. Your original chapter file is never edited.</p><button class="btn" id="save-manual">${data.manual_draft ? "Use manual assignments" : "Keep these assignments"}</button></div></div>` : ""}
    ${c.audio ? `<div class="player"><audio id="player" controls preload="metadata" src="${esc(c.audio)}"></audio></div>` : ""}
    ${c.video.url ? `<div class="row" style="margin:10px 0 16px"><a class="btn" href="${esc(c.video.url)}" target="_blank" rel="noopener">${icon("play")} Open video</a><button class="btn" id="show-video">${icon("folder")} Show in folder</button></div>` : ""}
    ${c.video.error ? `<div class="banner">Video: ${esc(c.video.error)}</div>` : ""}
    ${data.spoken_error ? `<div class="banner"><div><b>Spoken-text edits need review</b><p>${esc(data.spoken_error)}</p><details><summary>Stale edits</summary>${data.spoken_conflicts.map(entry=>`<div class="log">${esc(entry.text || "")}</div>`).join("")}</details><button class="btn" data-clear-spoken>Discard stale spoken-text edits</button></div></div>` : ""}
    ${data.voice_error ? `<div class="banner"><div><b>Voice rules need review</b><p>${esc(data.voice_error)}</p><button class="btn" data-clear-voice-conflicts>Review and clear stale line overrides</button></div></div>` : ""}
    ${unclear ? `<div class="banner">${icon("flag")}<div><b>${unclear} ${unclear === 1 ? "line needs" : "lines need"} a speaker.</b> Click the highlighted Unassigned label and choose a character.</div></div>` : ""}
    ${(data.blockers || []).length ? `<div class="banner">${icon("flag")}<div><b>${data.blockers.length} ${data.blockers.length === 1 ? "character needs" : "characters need"} approval in this chapter.</b><p>${data.blockers.map((b) => esc(b.label)).join(", ")}</p><div class="row">${data.blockers.map((b) => `<button class="btn" data-review-character="${esc(b.name)}">Review ${esc(b.label)}</button>`).join("")}</div></div></div>` : ""}
    ${data.report ? `<details class="card" style="padding:14px 18px"><summary><b>Analysis report</b></summary><div class="log" style="margin-top:10px">${esc(data.report)}</div></details>` : ""}
    <div class="card" style="margin-top:16px">
      ${lines.length ? `<div class="context-strip" aria-label="Narrative contexts by scene">${sceneNumbers.map((scene) => `<button type="button" class="btn small" data-scene-context="${scene}" title="Change the narrative context of this scene">Scene ${scene + 1} · ${esc(sceneLabel(scene))}</button>`).join("")}</div>` : ""}
      ${lines.length ? `<div class="row between"><div class="filters" style="margin:0">
          ${[["all", "All text"], ["dialogue", "Dialogue only"], ["review", `Lines to review (${reviewCount})`]].map(([key, label]) =>
            `<span class="chip ${lineFilter === key ? "on" : ""}" data-lines="${key}">${label}</span>`).join("")}</div>
          <div class="legend">${speakers.map((s) => `<button type="button" class="chip" data-legend-voice="${esc(s)}" title="Edit reading voice for ${esc(s)}"><i class="dot" style="background:${colorFor(s)}"></i>${esc(VoiceRules.label(s, lines))}</button>`).join("")}</div></div>
        <div class="script" id="script">${shown.map(({ line, index }, position) => `
          <div class="line ${kind(line)} ${line.joined ? "joined" : position ? "gap" : ""} ${line.speaker === UNASSIGNED ? "unclear" : ""} ${line.omitted ? "omitted" : ""}" data-index="${index}" style="--c:${colorFor(line.speaker)}" ${line.omitted ? 'title="Omitted: the fixed voice identifies the speaker. You can change this in Settings."' : ""}>
            <div>${line.speaker === PAUSE ? "" : `<button class="who ${line.speaker === NARRATOR ? "narrator" : ""}" data-who="${index}"><i class="dot" style="background:${colorFor(line.speaker)}"></i>${esc(line.speaker === UNASSIGNED ? "Who is speaking?" : line.speaker)}</button>`}</div>
            <div class="text">${line.joined ? '<span class="muted">↳ </span>' : ""}${esc(line.text)}${line.spoken_text && line.spoken_text !== line.text ? `<div class="spoken-edit"><b>Spoken:</b> ${esc(line.spoken_text)}</div>` : ""}${line.basis === "context" ? ` <span class="chip" title="Speaker inferred from narrative context; review this line.">context</span>` : ""}${line.flagged ? ` <span class="flag" title="Unusual pacing: listen to this line">${icon("flag")}</span>` : ""}${line.variant ? ` <span class="chip">take ${line.variant + 1}</span>` : ""}</div>
            <div class="tools">
              ${line.start != null && c.audio ? `<button class="btn ghost icon-only" data-play="${index}" title="Play from here">${icon("play")}</button>` : ""}
              ${![PAUSE,UNASSIGNED].includes(line.speaker) ? `<button type="button" class="btn small reading-voice" data-voice-rule="${index}" title="Edit the reading voice for this line">Voice: ${esc(line.read_as || line.speaker)}</button>` : ""}
              ${line.speaker !== PAUSE ? `<button class="btn small" data-edit-spoken="${index}" ${data.manual_draft ? "disabled" : ""} title="Edit the spoken version without changing the manuscript">Edit spoken text</button>` : ""}
              ${line.speaker !== PAUSE ? `<button class="btn ghost icon-only" data-split="${index}" title="Split the line, for example at a speech tag">${icon("scissors")}</button>` : ""}
              ${line.start != null ? `<button class="btn ghost icon-only" data-variant="${index}" title="Generate another take of this line">${icon("redo")}</button>` : ""}
            </div></div>`).join("")}</div>`
        : `<div class="empty"><p>This chapter has not been analyzed yet.</p><button class="btn primary" id="first-analyze">${icon("wand")} Analyze dialogue</button></div>`}
    </div>`;

  const runChapter = (steps, button) => guard(async () => {
    await api("/api/run", { method: "POST", body: { volume, stems: [stem], steps } });
    toast("Queued. Progress appears in the lower-left panel.");
    pollNow();
  }, button);
  $("#render").onclick = (e) => runChapter(["render", "export"], e.currentTarget);
  $("#diagnose-chapter")?.addEventListener("click", (e) => guard(() => ChapterWorkflow.diagnose(volume, stem), e.currentTarget));
  $("#create-video").onclick = (e) => runChapter(["video"], e.currentTarget);
  $("#show-video")?.addEventListener("click", (e) => guard(() => api("/api/video/show", { method: "POST", body: { volume, stem } }), e.currentTarget));
  const analyze = async (button) => {
    if (!data.manual_draft && lines.length && !await modal("Analyze again?", "<p>Your speaker assignments for this chapter will be replaced by a new analysis.</p>",
      [{ label: "Cancel", value: false }, { label: "Analyze again", value: true, primary: true }])) return;
    guard(async () => { await api("/api/chapter/analyze", { method: "POST", body: { volume, stem } }); toast("Analysis started."); pollNow(); }, button);
  };
  $("#reanalyze").onclick = (e) => analyze(e.currentTarget);
  $("#first-analyze")?.addEventListener("click", (e) => analyze(e.currentTarget));
  $("#open").onclick = () => guard(() => api("/api/open", { method: "POST", body: { what: "chapter", volume, stem } }));
  $$("[data-lines]").forEach((element) => element.onclick = () => { lineFilter = element.dataset.lines; viewChapter(volume, stem); });
  $$("[data-review-character]").forEach((button) => button.onclick = (event) =>
    guard(() => reviewCharacter(button.dataset.reviewCharacter, volume, stem, data, lines), event.currentTarget));
  $$("[data-scene-context]").forEach((button) => button.onclick = (event) =>
    guard(() => editSceneContext(+button.dataset.sceneContext, volume, stem, data), event.currentTarget));

  const save = async (rows, message) => {
    const result = await api("/api/chapter/rows", { method: "PUT", body: { volume, stem, rows, source_hash:data.source_hash } });
    if (result.added?.length) toast(`Added to the glossary: ${result.added.join(", ")}. Review their gender in Characters.`);
    else if (message) toast(message);
    viewChapter(volume, stem);
  };
  VoiceRules.bindChapter(volume, stem, data);
  SpokenText.bind(volume, stem, data);
  const rows = () => lines.map((l) => [l.speaker, l.text, l.joined, l.variant]);
  $("#save-manual")?.addEventListener("click", e => guard(() => save(rows(), "Manual assignments saved. Resolve remaining unassigned speakers before generating audio."), e.currentTarget));
  $$("[data-who]").forEach((button) => button.onclick = (event) => {
    event.stopPropagation();
    const index = +button.dataset.who;
    openMenu(button, data.speakers, lines[index].speaker, (speaker) => guard(() => {
      const next = rows();
      next[index][0] = speaker;
      return save(next, `${speaker} · saved`);
    }));
  });
  $$("[data-split]").forEach((button) => button.onclick = async () => {
    const index = +button.dataset.split;
    const form = await modal("Split line", `<p class="muted">${esc(lines[index].text)}</p>
      <label class="field"><span>Words where the new segment begins</span><input type="text" name="phrase" placeholder="he said"></label>
      <label class="field"><span>Speaker for the new segment</span><select name="speaker">${data.speakers.map((s) => `<option>${esc(s)}</option>`).join("")}</select></label>`,
      [{ label: "Cancel", value: null }, { label: "Split", value: "form", primary: true }]);
    if (form) guard(async () => { await api("/api/chapter/split", { method: "POST", body: { volume, stem, index, source_hash:data.source_hash, ...form } }); viewChapter(volume, stem); });
  });
  $$("[data-variant]").forEach((button) => button.onclick = () => guard(() => {
    const next = rows();
    next[+button.dataset.variant][3] = (next[+button.dataset.variant][3] || 0) + 1;
    return save(next, "New take selected. Only this line will be regenerated in the next run.");
  }));
  const player = $("#player");
  if (player) {
    $$("[data-play]").forEach((button) => button.onclick = () => { player.currentTime = lines[+button.dataset.play].start; player.play(); });
    player.ontimeupdate = () => {
      const t = player.currentTime;
      $$(".line.playing").forEach((element) => element.classList.remove("playing"));
      const index = lines.findIndex((l) => l.start != null && t >= l.start && t < l.start + l.seconds + 0.3);
      if (index >= 0) $(`.line[data-index="${index}"]`)?.classList.add("playing");
    };
  }
  scheduleRefresh(() => { if (!player || player.paused) viewChapter(volume, stem); });
}

/* narrative contexts: reviewed scene bindings, never inferred from the text */
async function editSceneContext(scene, volume, stem, data) {
  const state = await api("/api/character-registry");
  const volumeId = (state.volumes || []).find((v) => v.name === volume)?.id;
  if (!volumeId) { toast("This volume is no longer registered."); return; }
  const contexts = (state.document.organization.contexts || []).filter((c) => c.volume === volumeId);
  const current = (data.lines.find((l) => l.scene === scene)?.context_ids || [])[0] || "";
  const choice = await modal(`Scene ${scene + 1} context`,
    `<p>Bind this scene to a narrative context. Contexts scope aliases and guide speaker detection; they never rewrite the chapter.</p>
     <label class="field"><span>Narrative context</span><select name="context"><option value="">No context</option>${contexts.map((c) => `<option value="${esc(c.id)}" ${c.id === current ? "selected" : ""}>${esc(c.name)}</option>`).join("")}<option value="new">New context…</option></select></label>`,
    [{ label: "Cancel", value: null }, { label: "Save context", value: "form", primary: true }]);
  if (!choice) return;
  let context = choice.context;
  if (context === "new") {
    const form = await modal("New narrative context",
      `<label class="field"><span>Name</span><input name="name" maxlength="160" placeholder="Experience — Leonatus"></label>
       <label class="field"><span>Description</span><textarea name="description" maxlength="2000" placeholder="What this scene is and who can appear in it."></textarea></label>`,
      [{ label: "Cancel", value: null }, { label: "Create and bind", value: "form", primary: true }]);
    if (!form || !form.name.trim()) return;
    const created = await api("/api/character-registry/contexts", { method: "POST",
      body: { action: "create", name: form.name.trim(), description: form.description || "", volume: volumeId, revision: state.revision } });
    context = (created.document.organization.contexts || []).find((c) => c.name === form.name.trim())?.id;
    if (!context) { toast("The context was created but could not be bound. Reload the chapter."); return; }
  }
  await api("/api/character-registry/scene-context", { method: "PUT",
    body: { volume, stem, scene, context: context || null, source_hash: data.source_hash } });
  toast(context ? "Scene context saved." : "Scene context cleared.");
  viewChapter(volume, stem);
}

/* chapter-level identity review: approval is global, replacement stays in this chapter */
const STATUS_NAMES = { approved: "Approved", provisional: "Provisional", needs_review: "Needs review" };
async function reviewCharacter(name, volume, stem, data, lines) {
  const state = await api("/api/character-registry");
  const doc = state.document, meta = doc.organization.characters[name];
  if (!meta) { toast("This character is no longer in the registry."); return; }
  const action = await modal(`Review ${meta.label}`,
    `<p><b>${esc(meta.label)}</b> <span class="chip warn">${esc(STATUS_NAMES[meta.status] || meta.status)}</span></p>
     ${meta.reason ? `<p class="small">${esc(meta.reason)}</p>` : ""}
     <p class="small muted">Approving the identity changes who may be generated, not how anything sounds. Replacing a speaker changes this chapter only.</p>`,
    [{ label: "Cancel", value: null }, { label: "Open full details", value: "details" },
     { label: "Replace in chapter…", value: "replace" }, { label: "Approve identity", value: "approve", primary: true }]);
  if (action === "details") {
    sessionStorage.setItem("registryFocus", name);
    sessionStorage.setItem("registryReturn", location.hash);
    location.hash = "#/characters";
    return;
  }
  if (action === "replace") {
    const targets = doc.characters.filter((c) => c.name !== name).map((c) => c.name);
    if (!targets.length) { toast("There is no other character to use."); return; }
    const form = await modal("Replace in this chapter",
      `<p>Every line spoken by <b>${esc(meta.label)}</b> in this chapter becomes the chosen character. Other chapters keep their assignments.</p>
       <label class="field"><span>Existing character</span><select name="target">${targets.map((t) => `<option>${esc(t)}</option>`).join("")}</select></label>`,
      [{ label: "Cancel", value: null }, { label: "Replace in this chapter", value: "form", primary: true }]);
    if (!form) return;
    const rows = lines.map((line) => [line.speaker === name ? form.target : line.speaker, line.text, line.joined, line.variant]);
    await api("/api/chapter/rows", { method: "PUT", body: { volume, stem, rows, source_hash: data.source_hash } });
    toast(`This chapter now uses ${form.target} for those lines.`);
    viewChapter(volume, stem);
    return;
  }
  if (action === "approve") {
    const categories = doc.organization.categories.map((c) => [c.id, c.name]);
    const form = await modal("Approve identity",
      `<label class="field"><span>Category</span><select name="category">${categories.map(([id, label]) => `<option value="${esc(id)}" ${id === meta.category ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></label>
       <label class="row"><input type="checkbox" name="addVolume" checked> Add ${esc(volume)} to this character's volumes</label>
       <p class="small muted">The preview lists every chapter whose audio or video changes. Approval alone does not change the sound.</p>`,
      [{ label: "Cancel", value: null }, { label: "Preview approval", value: "form", primary: true }]);
    if (!form) return;
    const updated = structuredClone(state.document);
    const record = updated.organization.characters[name];
    record.status = "approved";
    if (form.category) record.category = form.category;
    if (form.addVolume) {
      const volumeId = (state.volumes || []).find((v) => v.name === volume)?.id;
      if (volumeId) record.volumes = [...new Set([...(record.volumes || []), volumeId])];
    }
    const report = await api("/api/character-registry/preview", { method: "POST", body: { revision: state.revision, document: updated } });
    const audio = report.effects.filter((e) => e.audio).length;
    const video = report.effects.filter((e) => e.video).length;
    const ready = report.effects.filter((e) => e.resolved).length;
    const confirm = await modal("Apply identity approval?",
      `<p>${audio} ${audio === 1 ? "chapter needs" : "chapters need"} new audio, ${video} ${video === 1 ? "needs" : "need"} a new video, and ${ready} ${ready === 1 ? "becomes" : "become"} ready to generate.</p><p class="small muted">Nothing is generated automatically. The manuscript and saved voices are unchanged.</p>`,
      [{ label: "Cancel", value: false }, { label: "Apply approval", value: true, primary: true }]);
    if (!confirm) return;
    await api("/api/character-registry", { method: "PUT", body: { request: report.request, plan_id: report.plan_id } });
    toast(`${meta.label} is approved.`);
    viewChapter(volume, stem);
  }
}

/* speaker picker */
let openMenuElement = null;
function closeMenu() { openMenuElement?.remove(); openMenuElement = null; }
document.addEventListener("click", (event) => { if (openMenuElement && !openMenuElement.contains(event.target)) closeMenu(); });
function openMenu(anchor, options, current, choose) {
  closeMenu();
  const menu = document.createElement("div");
  menu.className = "menu";
  menu.innerHTML = `<input type="text" placeholder="Search or enter a new name"><div class="options"></div>`;
  const list = $(".options", menu), input = $("input", menu);
  const draw = () => {
    const query = input.value.trim().toLowerCase();
    const matches = options.filter((o) => o.toLowerCase().includes(query));
    list.innerHTML = matches.map((o) => `<button data-o="${esc(o)}"><i class="dot" style="background:${colorFor(o)}"></i>${esc(o)}${o === current ? " ✓" : ""}</button>`).join("")
      + (query && !options.some((o) => o.toLowerCase() === query) ? `<button data-new="1">${icon("plus")} New character: <b>${esc(input.value.trim())}</b></button>` : "");
  };
  draw();
  input.oninput = draw;
  input.onkeydown = (event) => { if (event.key === "Enter") { const first = $("button", list); first?.click(); } if (event.key === "Escape") closeMenu(); };
  list.onclick = (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    const value = button.dataset.new ? input.value.trim() : button.dataset.o;
    closeMenu();
    choose(value);
  };
  document.body.append(menu);
  const rect = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.left, innerWidth - 260)}px`;
  menu.style.top = `${Math.min(rect.bottom + 6, innerHeight - 370)}px`;
  openMenuElement = menu;
  input.focus();
}

/* ---------- voice presets ---------- */
let presetList = null;
async function loadPresets() { return presetList ||= (await api("/api/presets")).presets; }
function presetRows(items, current, actionLabel) {
  return items.map((p) => `<div class="preset ${p.id === current ? "in-use" : ""}">
    <div><b>${esc(p.name)}</b><span class="small">${esc(p.summary)}</span></div>
    ${p.id === current ? `<span class="chip ok">${icon("check")} In use</span>`
      : `<button class="btn primary small" data-preset="${esc(p.id)}">${icon("lock")} ${esc(actionLabel)}</button>`}
    <audio controls preload="none" src="${esc(p.url)}"></audio></div>`).join("");
}
function pickPreset(title, intro, items, current) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `<div class="modal wide"><h2>${esc(title)}</h2><div class="stack"><p class="muted small">${intro}</p>
      <div class="presets">${presetRows(items, current, "Use this voice")}</div></div>
      <div class="row end"><button class="btn" data-close>Cancel</button></div></div>`;
    const previousFocus = document.activeElement;
    const close = (value) => { overlay.remove(); previousFocus?.focus({preventScroll:true}); resolve(value); };
    overlay.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.stopPropagation(); close(null); }
    });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay || event.target.closest("[data-close]")) close(null);
      const pick = event.target.closest("[data-preset]");
      if (pick) close(pick.dataset.preset);
    });
    document.body.append(overlay);
  });
}

/* ---------- characters ---------- */
async function showVoiceGuide(example = false) {
  const filename = example ? "Voice Sheet Example.md" : "Voice Personality Guide.md";
  const url = "/guides/" + encodeURIComponent(filename);
  const response = await fetch(url);
  if (!response.ok) throw new Error("Could not open the guide: " + response.status);
  const content = await response.text();
  const prompt = example ? content : content.match(/```text\r?\n([\s\S]*?)\r?\n```/)?.[1];
  if (!prompt) throw new Error("The complete prompt is missing from the guide.");
  const action = await modal(example ? "Example voice sheets" : "Character voice personality",
    `<p class="small muted">Reference material only. Reading this guide does not import characters or change your voices and settings.</p>
      <label class="field"><span>${example ? "Fictional example" : "Guide and complete prompt"}</span><textarea readonly rows="14">${esc(content)}</textarea></label>
      <a class="btn small" href="${esc(url)}" download="${esc(filename)}">${icon("download")} Download file</a>`,
    [{ label: "Close", value: null }, { label: example ? "Copy example" : "Copy prompt", value: "copy", primary: true }]);
  if (action === "copy") {
    await navigator.clipboard.writeText(prompt);
    toast(example ? "Example copied." : "Complete prompt copied.");
  }
}

let characterData = null, characterSaveTimer = null, characterSample = "", characterQuery = "";
async function viewCharacters() {
  if (CharacterRegistry.tab === 'quick') return CharacterRegistry.show();
  const [characters, similarity] = await Promise.all([api("/api/characters"), api("/api/voices/similarity")]);
  characterData = { ...characters, similarity };
  characterSample ||= characters.default_sample;
  drawCharacters();
}
let fieldHelpId = 0;
function fieldHelp(label, text, shortLabel = "") {
  const id='field-help-'+(++fieldHelpId);
  return `<span class="field-help"><button type="button" class="help-trigger" aria-label="Help: ${esc(label)}" aria-describedby="${id}">${shortLabel ? esc(shortLabel) : icon('info')}</button><span class="help-content" role="tooltip" id="${id}">${esc(text)}</span></span>`;
}
function bindFieldHelp(root) {
  root.querySelectorAll('.field-help').forEach(tip=>{
    const button=tip.querySelector('button');
    button.onkeydown=e=>{if(e.key==='Escape'){tip.classList.add('dismissed');e.stopPropagation();}};
    button.onfocus=()=>tip.classList.remove('dismissed');
    tip.onmouseenter=()=>tip.classList.remove('dismissed');
  });
}

function drawCharacters() {
  const d = characterData;
  const profileNames = (gender) => [...(d.profiles[gender] || []), ...(gender === "unknown" ? [] : d.profiles.unknown || []), ...d.profiles.narrator];
  const visible = d.characters.map((c, i) => ({ c, i })).filter(({ c }) => !characterQuery || (c.name + " " + c.aliases + " " + c.note).toLowerCase().includes(characterQuery));
  const genderKey = { male: "male", female: "female", unknown: "unknown" };
  const pairs = d.similarity?.pairs || [];
  const confusable = pairs.filter((p) => p.score >= (d.similarity.confusable || 0.5));
  const closestTo = (name) => pairs.filter((p) => p.a === name || p.b === name).map((p) => ({ name: p.a === name ? p.b : p.a, score: p.score }))[0];
  view.innerHTML = `
    <div class="page-head"><div><h1>Your characters</h1>
      <p>Each character has an own reference voice. Reading rules can choose the narrator or another character without changing who speaks. Gender, aliases and context help identify speakers.</p></div>
      <button class="btn primary" id="new-character">${icon("plus")} New character</button></div>
    <details class="card character-guide"><summary>About fixed voices and auditions</summary><div class="stack">
      <div><b>Important: a preview should express the character's personality.</b>
        <p class="small">Build the voice sheet from the story, relationships and speaking style, then write the description and sample in English. A fixed reference also carries the sample's delivery.</p>
        <p class="small">Editing a description does not replace a fixed voice. Listen to a new take and fix it explicitly when you choose to change a voice. The guide does not change anything automatically.</p></div>
      <div class="row"><button class="btn small" id="voice-guide">Voice personality guide</button>
        <button class="btn small" id="voice-guide-example">View complete example</button></div>
    </div></details>
    ${d.duplicates.length ? `<div class="banner">${icon("flag")}<div><b>Identical voices:</b> ${d.duplicates.map((g) => esc(g.join(" and "))).join("; ")}. They may be hard to distinguish in the same scene.</div></div>` : ""}
    ${confusable.length ? `<div class="banner">${icon("flag")}<div><b>Similar fixed voices</b> (voice fingerprint, 1 = identical): ${confusable.map((p) => `${esc(p.a)} ↔ ${esc(p.b)} <b>${p.score.toFixed(2)}</b>`).join(" · ")}.
      For one of them, choose <b>“Find a more distinct voice”</b> to compare up to 3 new takes from the same description, ranked by their difference from the other voices.</div></div>` : ""}
    <div class="card"><div class="grid two">
      <label class="field"><span>Search</span><input type="text" id="query" value="${esc(characterQuery)}" placeholder="name, alias or context"></label>
      <label class="field"><span>Default preview for characters without their own sample</span><input type="text" id="sample" value="${esc(characterSample)}"></label>
    </div></div>
    ${visible.length ? "" : `<div class="empty">${d.characters.length ? "No characters match your search." : "No characters yet. Add your cast here, or analyze a chapter to discover speakers."}</div>`}
    <div class="grid cards" style="margin-top:16px">${visible.map(({ c, i }) => {
      const design = d.profile_texts[c.design] ? c.design : "__custom";
      const text = d.profile_texts[c.design] || c.design;
      return `<div class="card char-card" data-i="${i}">
        <div class="char-head"><i class="dot" style="background:${colorFor(c.name)};width:14px;height:14px"></i><h3 style="flex:1">${esc(c.name)}</h3>
          <div class="seg" aria-label="Gender">${[["male", "♂"], ["female", "♀"], ["unknown", "?"]].map(([g, sign]) => `<button class="${c.gender === g ? "on" : ""}" data-gender="${g}" title="${g}" aria-label="${g}" aria-pressed="${c.gender === g}">${sign}</button>`).join("")}</div></div>
        <button class="btn small" data-reading-voice>Read as: ${esc(c.read_as || c.name)}</button>
        <div class="row between"><span class="${c.fixed ? 'fixed-status' : 'review-status'}">${c.fixed ? icon('lock')+' Fixed voice' : 'Voice to review'}</span>${fieldHelp('Fixed voice','An approved recording keeps the voice identity. Unfix returns to the recipe and can make generated chapters outdated.')}
        <button class="btn" data-listen>${icon("play")} Listen</button></div>
        <audio data-audio controls class="hidden" style="width:100%"></audio>
        ${c.fixed ? `<div class="fixed-box"><div class="row between"><span class="small muted">Own reference</span><button class="btn ghost small" data-unfix>Unfix voice</button></div>
          ${(() => { const near=closestTo(c.name);return near ? `<div class="small">Most similar to <b>${esc(near.name)}</b>: ${near.score.toFixed(2)}${near.score >= 0.5 ? ' — may be confused' : ''}${fieldHelp('Voice similarity','A voice fingerprint comparison, not an emotion score. Higher values mean more similar voices; compare a more distinct take if listeners may confuse them.')}</div>` : ''; })()}
          <audio controls src="${esc(c.fixed.url)}" style="width:100%"></audio></div>` : `<button class="btn primary hidden" data-fix>${icon("lock")} Fix this voice</button>`}
        <div class="small muted">Shared performance variation ${fieldHelp('Shared performance variation','The Narrator page sets one temperature for all voices, including characters. Each character has a separate seed. This does not change the fixed reference.')}<a href="#/narrator">Narrator settings</a></div>
        <details class="character-section"><summary>Speaker detection</summary>
          <label class="field"><span>Aliases ${fieldHelp('Aliases','Other names used for this character in the text. They help identify the speaker; they are not spoken.')}</span><input type="text" data-f="aliases" value="${esc(c.aliases)}" placeholder="e.g. Ally, Doctor"></label>
          <label class="field"><span>Context for speaker detection ${fieldHelp('Speaker detection context','Notes sent to the dialogue model when this character or an alias appears in the chapter. They help identify who speaks; they are not spoken and do not change the voice.')}</span><textarea data-f="note" rows="2">${esc(c.note)}</textarea></label>
        </details>
        <details class="character-section"><summary>Voice creation</summary>
          <label class="field"><span>Voice recipe model ${fieldHelp('Voice recipe model','Creates audition takes from a description (VoiceDesign), a built-in speaker (CustomVoice), or the narrator’s recipe model. A fixed reference takes priority until you unfix it.')}</span><select data-f="model">${["same as narrator", "VoiceDesign", "CustomVoice"].map(m=>`<option ${c.model === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
          <label class="field"><span>Character sample — personality (English) ${fieldHelp('Character sample','The text used for auditions. A fixed voice clones the approved recording without delivery instructions. The reference’s rhythm and emotion can influence later lines; punctuation still matters and does not guarantee a specific emotion.')}</span><textarea data-f="sample" rows="3" placeholder="${esc(characterSample)}">${esc(c.sample || '')}</textarea></label>
          <label class="field"><span>Voice description (VoiceDesign) ${fieldHelp('Voice description','Describes timbre, age and accent when creating a new VoiceDesign take. Editing it does not alter an already fixed voice.')}</span><select data-profile>${["__custom",...profileNames(genderKey[c.gender])].map(p=>`<option value="${esc(p)}" ${p===design ? 'selected' : ''}>${p==='__custom' ? 'Custom description' : esc(p)}</option>`).join('')}</select></label>
          <textarea data-description aria-label="Voice description text" rows="3">${esc(text)}</textarea>
          <label class="field"><span>Built-in speaker (CustomVoice) ${fieldHelp('Built-in speaker','Selects a built-in speaker for CustomVoice auditions. Ryan and Aiden are the English speakers in this catalog. Fixed voices use their approved recording instead.')}</span><select data-f="custom"><option value=""></option>${Object.entries(d.custom_speakers).map(([name,about])=>`<option value="${name}" ${c.custom===name ? 'selected' : ''}>${name} — ${esc(about)}</option>`).join('')}</select></label>
          <div class="foot"><label class="field"><span>Variation number (seed) ${fieldHelp('Seed','A number used to repeat an audition take. The dice choose another number for a different take of the same recipe; they do not replace the fixed reference.')}</span><input type="number" data-f="seed" value="${c.seed}" title="Variation number (seed)"></label><button class="btn ghost icon-only" data-dice title="Another take">${icon('dice')}</button></div>
          <div class="row"><button class="btn" data-preset-pick>${icon('book')} Use a preset voice</button><button class="btn" data-candidates>${icon('dice')} Find a more distinct voice</button></div>
          <div class="takes" data-candidate-list></div>
        </details>
        <div class="row end"><button class="btn ghost icon-only danger" data-delete title="Remove from glossary">${icon('trash')}</button></div>
      </div>`;
    }).join("")}</div>`;
  CharacterRegistry.studioHeader();
  bindFieldHelp(view);
  $("#voice-guide").onclick = (e) => guard(() => showVoiceGuide(), e.currentTarget);
  $("#voice-guide-example").onclick = (e) => guard(() => showVoiceGuide(true), e.currentTarget);
  $("#query").oninput = (e) => { characterQuery = e.target.value.toLowerCase(); clearTimeout(drawCharacters.t); drawCharacters.t = setTimeout(() => { drawCharacters(); $("#query").focus(); $("#query").setSelectionRange(99, 99); }, 300); };
  $("#sample").oninput = (e) => characterSample = e.target.value;
  $("#new-character").onclick = async () => {
    const form = await modal("New character", `<label class="field"><span>Name (as it appears in the text)</span><input type="text" name="name"></label>
      <label class="field"><span>Gender</span><select name="gender"><option>male</option><option>female</option><option>unknown</option></select></label>
      <p class="muted small">Starts with a distinct voice recipe. You can edit it afterwards.</p>`, [{ label: "Cancel", value: null }, { label: "Add", value: "form", primary: true }]);
    if (form) guard(async () => { characterData = { ...characterData, ...await api("/api/characters/new", { method: "POST", body: form }) }; drawCharacters(); });
  };
  $$(".char-card").forEach((card) => {
    const c = d.characters[+card.dataset.i];
    $("[data-reading-voice]", card).onclick = e => guard(() => VoiceRules.editor(c.name,{text:c.sample || characterSample}),e.currentTarget);
    const changed = () => queueCharacterSave();
    $$("[data-f]", card).forEach((field) => field.oninput = () => { c[field.dataset.f] = field.type === "number" ? +field.value : field.value; changed(); });
    $$("[data-gender]", card).forEach((button) => button.onclick = () => { c.gender = button.dataset.gender; changed(); drawCharacters(); });
    $("[data-profile]", card).onchange = (e) => {
      if (e.target.value !== "__custom") { c.design = e.target.value; $("[data-description]", card).value = d.profile_texts[c.design]; }
      else c.design = $("[data-description]", card).value;
      changed();
    };
    $("[data-description]", card).oninput = (e) => { c.design = e.target.value; $("[data-profile]", card).value = "__custom"; changed(); };
    $("[data-dice]", card).onclick = () => { c.seed = Math.floor(Math.random() * 9000) + 1000; $("[data-f=seed]", card).value = c.seed; changed(); };
    let lastTake = null;
    $("[data-listen]", card).onclick = (e) => guard(async () => {
      const result = await api("/api/characters/preview", { method: "POST", body: { character: c, text: c.sample || characterSample } });
      const audio = $("[data-audio]", card); audio.classList.remove("hidden"); audio.src = result.url; audio.play();
      lastTake = result;
      $("[data-fix]", card)?.classList.remove("hidden");
    }, e.currentTarget);
    $("[data-fix]", card)?.addEventListener("click", (e) => guard(async () => {
      await api("/api/voices/fix", { method: "POST", body: { role: c.name, path: lastTake.path, text: lastTake.text, origin: { seed: c.seed, design: c.design } } });
      toast(`The voice for ${c.name} is fixed and will be reused throughout the book.`);
      await viewCharacters();
    }, e.currentTarget));
    $("[data-preset-pick]", card).onclick = (e) => guard(async () => {
      const all = await loadPresets();
      const rank = (p) => (p.kind === "character" ? 0 : 1) + (c.gender === "unknown" || p.gender === c.gender ? 0 : 2);
      const intro = "Each preset is a fixed reference voice with the description and seed that produced it. Listen, then choose one."
        + (c.fixed ? ` <b>This replaces the current fixed voice of ${esc(c.name)}</b>; only this character's generated passages become Outdated.` : "");
      const id = await pickPreset(`Voice presets for ${c.name}`, intro, [...all].sort((a, b) => rank(a) - rank(b)), c.fixed?.origin?.preset);
      if (!id) return;
      clearTimeout(characterSaveTimer);
      await api("/api/characters", { method: "PUT", body: { characters: characterData.characters } });
      await api("/api/presets/apply", { method: "POST", body: { id, role: c.name } });
      toast(`${c.name} now uses the preset voice “${all.find((p) => p.id === id).name}”.`);
      await viewCharacters();
    }, e.currentTarget);
    $("[data-candidates]", card).onclick = (e) => guard(async () => {
      const result = await api("/api/characters/candidates", { method: "POST", body: { character: c, text: c.sample || characterSample, count: 6 } });
      const list = $("[data-candidate-list]", card);
      list.innerHTML = (result.current ? `<div class="small muted">Current reference is most similar to <b>${esc(result.current[1])}</b>: ${result.current[0].toFixed(2)}. Lower means more distinct.</div>` : "")
        + result.takes.map((t) => `<div class="take"><b>Take ${t.seed}</b><audio controls src="${t.url}"></audio>
          <button class="btn primary small" data-pick="${esc(t.path)}" data-seed="${t.seed}">${icon("lock")} Fix voice</button>
          <div class="small muted" style="grid-column:1/-1">${t.closest ? `closest voice: ${esc(t.closest)} ${t.score.toFixed(2)}` : ""}</div></div>`).join("");
      $$("[data-pick]", list).forEach((b) => b.onclick = () => guard(async () => {
        c.seed = +b.dataset.seed;
        await api("/api/characters", { method: "PUT", body: { characters: characterData.characters } });
        await api("/api/voices/fix", { method: "POST", body: { role: c.name, path: b.dataset.pick, text: result.text, origin: { seed: c.seed, design: c.design } } });
        toast(`${c.name} has a new fixed voice. Only this character's generated passages become outdated.`);
        await viewCharacters();
      }, b));
    }, e.currentTarget);
    $("[data-unfix]", card)?.addEventListener("click", async () => {
      if (!await modal(`Unfix the voice for ${c.name}?`, "<p>This character will use the description again, which may vary between passages. Generated chapters will become Outdated.</p>",
        [{ label: "Cancel", value: false }, { label: "Unfix voice", value: true, primary: true }])) return;
      guard(async () => { await api("/api/voices/unfix", { method: "POST", body: { role: c.name } }); await viewCharacters(); });
    });
    $("[data-delete]", card).onclick = async () => {
      if (!await modal(`Remove ${c.name}?`, "<p>The character will be removed from the glossary. Previously analyzed dialogue will need a voice before generation.</p>",
        [{ label: "Cancel", value: false }, { label: "Remove", value: true, primary: true }])) return;
      d.characters.splice(+card.dataset.i, 1); queueCharacterSave(0); drawCharacters();
    };
  });
}
function queueCharacterSave(delay = 700) {
  clearTimeout(characterSaveTimer);
  characterSaveTimer = setTimeout(() => guard(async () => {
    await api("/api/characters", { method: "PUT", body: { characters: characterData.characters } });
    const fresh = await api("/api/characters");
    characterData.duplicates = fresh.duplicates;
    toast("Characters saved");
  }), delay);
}

/* ---------- narrator ---------- */
async function viewNarrator() {
  const [data, allPresets] = await Promise.all([api("/api/settings"), loadPresets()]);
  const narratorPresets = allPresets.filter((p) => p.kind === "narrator");
  const n = data.settings.narrator;
  let sample = data.preview_text;
  const draw = () => {
    const isDesign = n.mode === "VoiceDesign";
    const profile = data.profiles[n.profile] && data.profiles[n.profile] === n.description ? n.profile : "__custom";
    view.innerHTML = `
      <div class="page-head"><div><h1>Narrator voice</h1>
        <p>The narrator reads prose and speech tags. Compare takes of the same passage, then <b>fix</b> your favorite. The same reference voice will then be used throughout the book.</p></div>
        <button class="btn primary" id="save">${icon("check")} Save narrator</button></div>
      ${data.fixed ? `<div class="card fixed-box" style="margin-bottom:16px">
          <div class="row between"><b>${icon("lock")} Narrator voice is fixed</b>
            <div class="row"><button class="btn" id="listen-fixed">${icon("play")} Hear it on the preview text</button><button class="btn ghost" id="unfix">Unfix voice</button></div></div>
          <div class="small muted">This approved reference voice is used throughout the book (${esc(data.fixed.date.slice(0, 10))}, ${data.fixed.seconds} s). The description and directions below are only used to audition a new voice.</div>
          <audio controls src="${esc(data.fixed.url)}" style="width:100%"></audio>
          <div class="takes" id="fixed-takes"></div></div>`
        : `<div class="banner" style="margin-bottom:16px">${icon("info")}<div><b>No reference voice yet:</b> passages may sound like different narrators. Compare takes and choose <b>“Fix voice”</b> on your favorite. A clear 15–20 second sample is a useful starting point.</div></div>`}
      <div class="card stack" id="narrator-presets" style="margin-bottom:16px">
        <div><h3>Ready-made narrator voices</h3><p class="small muted">Listen, then choose one to fix it for the whole book. Or describe your own voice below.</p></div>
        <div class="presets">${presetRows(narratorPresets, data.fixed?.origin?.preset, "Use as narrator")}</div></div>
      <div class="grid two">
        <div class="card stack">
          <div class="seg"><button class="${isDesign ? "on" : ""}" data-mode="VoiceDesign">Describe a voice (VoiceDesign)</button><button class="${isDesign ? "" : "on"}" data-mode="CustomVoice">Built-in speaker (CustomVoice)</button></div>
          ${isDesign ? `
            <label class="field"><span>Starting profile</span><select id="profile"><option value="__custom">Custom description</option>${Object.keys(data.profiles).map((p) => `<option ${p === profile ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
            <label class="field"><span>Voice description (English)</span><textarea id="description" rows="5">${esc(n.description)}</textarea><small>Age, gender, timbre, accent and character. Example: “warm, grounded middle-low register”.</small></label>`
          : `<label class="field"><span>Voice</span><select id="speaker">${Object.entries(data.custom_speakers).map(([s, about]) => `<option value="${s}" ${n.speaker === s ? "selected" : ""}>${s} — ${esc(about)}</option>`).join("")}</select><small>Built-in speaker identity. Ryan and Aiden are native English speakers.</small></label>`}
          <label class="field"><span>Delivery directions (English)</span><textarea id="instructions" rows="4">${esc(n.instructions)}</textarea><small>Pacing, emotion and emphasis. Example: “measured but flowing, understated”.</small></label>
          <div class="two-cols">
            <label class="field"><span>Variation number (seed)</span><input type="number" id="seed" value="${n.seed}"><small>A different number gives a different take. It is not a quality score.</small></label>
            <label class="field"><span>Performance variation: <b id="temp-value">${n.temperature}</b></span><input type="range" id="temperature" min="0.3" max="1.2" step="0.05" value="${n.temperature}"><small>Lower values usually give more predictable delivery. Fix a reference voice to preserve identity.</small></label>
          </div>
        </div>
        <div class="card stack">
          <h3>Audition the same passage</h3>
          <label class="field"><span>Preview text</span><textarea id="sample" rows="5">${esc(sample)}</textarea><small>Paste a passage containing prose and dialogue.</small></label>
          <div class="row"><button class="btn primary" id="listen">${icon("play")} Listen</button><button class="btn" id="compare">${icon("dice")} Compare 3 takes</button></div>
          <div class="takes" id="takes"></div>
          <div class="banner info small">${icon("info")}<div>Changing a reference voice makes the affected chapters Outdated. Only the narrator's changed passages need regeneration.</div></div>
        </div>
      </div>`;
    $$("#narrator-presets [data-preset]").forEach((b) => b.onclick = () => guard(async () => {
      if (data.fixed && !await modal("Replace the narrator voice?", "<p>The new voice is used for all narration. Generated chapters become Outdated and only the narrator's passages are regenerated.</p>",
        [{ label: "Cancel", value: false }, { label: "Use this voice", value: true, primary: true }])) return;
      await api("/api/presets/apply", { method: "POST", body: { id: b.dataset.preset, role: NARRATOR } });
      toast("The narrator voice is fixed and will be used throughout the book.");
      viewNarrator();
    }, b));
    $$("[data-mode]").forEach((b) => b.onclick = () => { read(); n.mode = b.dataset.mode; draw(); });
    $("#profile")?.addEventListener("change", (e) => { if (e.target.value !== "__custom") { n.profile = e.target.value; $("#description").value = data.profiles[n.profile]; } });
    $("#temperature").oninput = (e) => $("#temp-value").textContent = e.target.value;
    $("#save").onclick = (e) => guard(async () => { read(); const result = await api("/api/settings", { method: "PUT", body: { settings: data.settings } }); data.settings = result.settings; toast("Narrator saved"); }, e.currentTarget);
    const takes = (seeds, button) => guard(async () => {
      read();
      const result = await api("/api/narrator/preview", { method: "POST", body: { narrator: n, text: sample, seeds } });
      $("#takes").innerHTML = result.takes.map((t) => `<div class="take"><b>Take ${t.seed}</b><audio controls src="${t.url}"></audio>
        <button class="btn primary" data-fix="${esc(t.path)}" data-seed="${t.seed}">${icon("lock")} Fix voice</button></div>`).join("");
      $$("[data-fix]").forEach((b) => b.onclick = () => guard(async () => {
        n.seed = +b.dataset.seed;
        await api("/api/voices/fix", { method: "POST", body: { role: "Narrator", path: b.dataset.fix, text: result.text, origin: { seed: n.seed, description: n.description, temperature: n.temperature } } });
        await api("/api/settings", { method: "PUT", body: { settings: data.settings } });
        toast(`Take ${n.seed} is now the narrator's fixed voice.`);
        viewNarrator();
      }, b));
      $("#takes audio")?.play();
    }, button);
    $("#listen-fixed")?.addEventListener("click", (e) => guard(async () => {
      read();
      const result = await api("/api/narrator/preview", { method: "POST", body: { narrator: n, text: sample, fixed: true } });
      $("#fixed-takes").innerHTML = `<div class="take"><b>Fixed voice</b><audio controls autoplay src="${result.takes[0].url}"></audio><span></span></div>`;
    }, e.currentTarget));
    $("#unfix")?.addEventListener("click", async () => {
      if (!await modal("Unfix the narrator voice?", "<p>The narrator will use the description again and may vary between passages. Generated chapters will become Outdated.</p>",
        [{ label: "Cancel", value: false }, { label: "Unfix voice", value: true, primary: true }])) return;
      guard(async () => { await api("/api/voices/unfix", { method: "POST", body: { role: "Narrator" } }); viewNarrator(); });
    });
    $("#listen").onclick = (e) => takes([+$("#seed").value], e.currentTarget);
    $("#compare").onclick = (e) => { const s = +$("#seed").value; takes([s, s + 1, s + 2], e.currentTarget); };
  };
  const read = () => {
    if ($("#description")) n.description = $("#description").value;
    if ($("#speaker")) n.speaker = $("#speaker").value;
    if ($("#instructions")) n.instructions = $("#instructions").value;
    if ($("#seed")) n.seed = +$("#seed").value;
    if ($("#temperature")) n.temperature = +$("#temperature").value;
    if ($("#sample")) sample = $("#sample").value;
  };
  draw();
}

/* ---------- settings ---------- */
async function viewSettings() {
  const data = await api("/api/settings");
  const s = data.settings;
  const v = s.video;
  const formatHelp = { mp3: "Widely supported. Recommended.", m4a: "Good quality in a compact file; Apple and Android.", ogg: "Open format suited to speech.",
    opus: "Compact files with efficient speech compression.", flac: "Lossless audio; larger files.", wav: "Uncompressed audio for editing." };
  view.innerHTML = `
    <div class="page-head"><div><h1>Settings and export</h1><p>Applies to every chapter. Defaults balance clear speech, compact files and export speed.</p></div>
      <button class="btn primary" id="save">${icon("check")} Save settings</button></div>
    ${data.ffmpeg ? "" : `<div class="banner">${icon("info")} FFmpeg was not found on this computer. Only WAV is available.</div>`}
    <p class="small muted" id="model-profile">Model set: <b>${esc(data.model_profile.label)}</b> · dialogue model ${esc(data.model_profile.gemma)}. Chosen during installation.</p>
    <div class="grid two">
      <details class="card stack settings-section" open><summary><h3>${icon("sound")} Audio</h3></summary>
        <div class="grid" style="grid-template-columns:1fr 1fr">${Object.entries(data.formats.chapter).map(([key, label]) => `
          <label class="choice ${s.export_format === key ? "on" : ""}"><input type="radio" name="format" value="${key}" ${s.export_format === key ? "checked" : ""}><div><b>${esc(label)}</b><span>${formatHelp[key]}</span></div></label>`).join("")}</div>
        <div><span class="small muted">Quality</span><br><div class="seg" id="quality"><button data-q="standard" class="${s.export_quality === "standard" ? "on" : ""}">Standard · 64 kbps</button><button data-q="high" class="${s.export_quality === "high" ? "on" : ""}">High · 96 kbps</button></div></div>
        <label class="field"><span>Whole-volume format</span><select id="volume-format">${Object.entries(data.formats.volume).map(([key, label]) => `<option value="${key}" ${s.volume_format === key ? "selected" : ""}>${esc(label)}</option>`).join("")}</select><small>M4B preserves chapter markers for compatible audiobook players.</small></label>
        <label class="field"><span>Author (file metadata)</span><input type="text" id="author" value="${esc(s.author)}"></label>
      </details>
      <details class="card stack settings-section" id="video-settings" open><summary><h3>${icon("video")} Video</h3></summary>
        <label class="switch"><input type="checkbox" id="video-enabled" ${v.enabled ? "checked" : ""}><div><b>Also create an MP4 video</b><div class="small muted">Run automatically creates videos after audio export. Off by default; manual video creation is always available.</div></div></label>
        <div class="two-cols">
          <label class="field"><span>Resolution</span><select id="video-resolution"><option value="1920" ${v.width === 1920 ? "selected" : ""}>1080p · 1920 × 1080</option><option value="1280" ${v.width === 1280 ? "selected" : ""}>720p · 1280 × 720</option></select></label>
          <label class="field"><span>Video codec</span><select id="video-codec" disabled aria-describedby="video-codec-help">${Object.entries({h264: "H.264", h265: "H.265 (HEVC)", av1: "AV1"}).map(([key, label]) => `<option value="${key}" ${(v.codec || "h264") === key ? "selected" : ""}>${label} · Checking…</option>`).join("")}</select><small id="video-codec-help" aria-live="polite">Checking encoders… Encoded with NVIDIA NVENC when available. H.264 can also use the CPU; H.265 and AV1 require NVENC.</small></label>
          <label class="field"><span>Previous passages</span><select id="video-before">${[0,1,2,3,4].map(n => `<option ${n === v.before ? "selected" : ""}>${n}</option>`).join("")}</select></label>
          <label class="field"><span>Following passages</span><select id="video-after">${[0,1,2,3,4].map(n => `<option ${n === v.after ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        </div>
        <label class="field"><span>Optional footer</span><input id="video-footer" type="text" maxlength="200" value="${esc(v.footer)}" placeholder="Leave empty for no footer"></label>
        <label class="switch"><input type="checkbox" id="video-omitted" ${v.show_omitted ? "checked" : ""}><div>Show omitted speech tags</div></label>
        <label class="switch"><input type="checkbox" id="video-progress" ${v.progress_bar ? "checked" : ""}><div>Show progress bar in video</div></label>
        <p class="small muted">Uses current, generated audio. Changing appearance options makes existing videos outdated; turning automatic video on or off keeps them valid. Audio and voices are unchanged. ${data.video_factor ? `Measured render time: about ${Math.round(data.video_factor*60)} seconds per minute of audio.` : "A time estimate appears after the first completed video."}</p>
      </details>
    </div>
    <details class="card stack settings-section" open style="margin-top:18px"><summary><h3>${icon("book")} Reading</h3></summary>
      <label class="switch"><input type="checkbox" id="multi" ${s.multi_voice ? "checked" : ""}><div><b>Separate character voices</b><div class="small muted">Off: the narrator reads everything, including dialogue.</div></div></label>
      <label class="switch"><input type="checkbox" id="announce" ${s.announce_titles ? "checked" : ""}><div><b>Announce chapter titles</b><div class="small muted">For example: Chapter 1. Arrival. followed by a pause.</div></div></label>
      <label class="switch"><input type="checkbox" id="tags" ${s.speech_tags !== "all" ? "checked" : ""}><div><b>Omit simple speech tags for fixed voices</b><div class="small muted">A simple tag such as Alex said is omitted when Alex has a fixed voice. Informative tags such as she whispered and tags for voices without references are kept.</div></div></label>
      <label class="field"><span>Pause between speakers: <b id="pause-value">${s.dialogue_pause}</b> s</span><input type="range" id="pause" min="0.2" max="1.5" step="0.05" value="${s.dialogue_pause}">
        <small>Actual silence between speakers. Tag-to-dialogue: 0.25 s; paragraphs: 0.6 s; scene changes: 1.2 s.</small></label>
      <div><b>Uncertain speakers during automatic processing</b>
        <div class="stack" style="margin-top:8px">
          <label class="choice ${s.unclear_policy === "wait" ? "on" : ""}"><input type="radio" name="policy" value="wait" ${s.unclear_policy === "wait" ? "checked" : ""}><div><b>Wait for my review</b><span>The selected batch waits until you choose every unresolved speaker. Recommended for accuracy.</span></div></label>
          <label class="choice ${s.unclear_policy === "narrator" ? "on" : ""}"><input type="radio" name="policy" value="narrator" ${s.unclear_policy === "narrator" ? "checked" : ""}><div><b>Use the narrator</b><span>Processing continues. Those lines use the narrator's voice.</span></div></label>
        </div></div>
    </details>`;
  $$(".choice input").forEach((input) => input.onchange = () => $$(`.choice input[name=${input.name}]`).forEach((other) => other.closest(".choice").classList.toggle("on", other.checked)));
  $$("#quality button").forEach((b) => b.onclick = () => { $$("#quality button").forEach((x) => x.classList.toggle("on", x === b)); });
  $("#pause").oninput = (e) => $("#pause-value").textContent = e.target.value;
  $("#save").onclick = (e) => guard(async () => {
    s.video = { ...v, codec: $("#video-codec").value, enabled: $("#video-enabled").checked,
      width: +$("#video-resolution").value, height: +$("#video-resolution").value === 1920 ? 1080 : 720,
      before: +$("#video-before").value, after: +$("#video-after").value,
      show_omitted: $("#video-omitted").checked, progress_bar: $("#video-progress").checked,
      footer: $("#video-footer").value };
    s.export_format = $("input[name=format]:checked").value;
    s.export_quality = $("#quality .on").dataset.q;
    s.volume_format = $("#volume-format").value;
    s.author = $("#author").value;
    s.multi_voice = $("#multi").checked;
    s.announce_titles = $("#announce").checked;
    s.speech_tags = $("#tags").checked ? "omit_fixed" : "all";
    s.dialogue_pause = +$("#pause").value;
    s.unclear_policy = $("input[name=policy]:checked").value;
    await api("/api/settings", { method: "PUT", body: { settings: s } });
    toast("Settings saved");
  }, e.currentTarget);
  // Do not wait for GPU checks before displaying the page or wiring its controls.
  const codecSelect = $("#video-codec"), codecHelp = $("#video-codec-help");
  api("/api/video/codecs").then(({codecs}) => {
    if ($("#video-codec") !== codecSelect) return; // The user may have navigated away.
    const current = v.codec || "h264";
    codecSelect.innerHTML = Object.entries({h264: "H.264", h265: "H.265 (HEVC)", av1: "AV1"}).map(([key, label]) => {
      const info = codecs[key];
      const status = info.available ? (info.encoder === "libx264" ? "CPU" : "NVENC") : info.reason;
      return `<option value="${key}" ${current === key ? "selected" : ""} ${info.available ? "" : "disabled"}>${label} · ${esc(status)}</option>`;
    }).join("");
    codecSelect.disabled = !Object.values(codecs).some(info => info.available);
    codecHelp.textContent = "Encoded with NVIDIA NVENC when available. H.264 can also use the CPU; H.265 and AV1 require NVENC. " +
      (codecs[current].available ? "" : `Saved codec unavailable: ${codecs[current].reason} Choose another codec before rendering.`);
  }).catch(() => {
    if ($("#video-codec") === codecSelect) codecHelp.textContent = "Encoder checks failed. Your saved codec is unchanged. Reopen Settings to retry.";
  });
}

/* ---------- project transfer ---------- */
const PROJECT_PARTS = { settings: "Settings", cast: "Cast and fixed voices", volumes: "Volumes and speaker assignments" };
let importPreview = null;
async function viewProject() {
  const history = await api("/api/project");
  view.innerHTML = `<div class="page-head"><div><h1>Project</h1><p>Back up or move your settings, cast and speaker assignments. Everything stays on this computer.</p></div></div>
    <div class="grid two">
      <div class="card stack"><h2>Export project</h2><p class="muted small">Choose the parts to save in one .abstudio file. Generated chapter audio, models, caches and source manuscripts are never included.</p>
        ${Object.entries(PROJECT_PARTS).map(([key,label]) => `<label class="switch"><input type="checkbox" data-export-part="${key}" ${key === "volumes" ? "" : "checked"}><div>${label}</div></label>`).join("")}
        <div class="banner small" id="book-warning">This file will contain your book text if you include speaker assignments. Do not share it publicly.</div>
        <p class="small muted">A cast-only export contains voice descriptions, reference WAVs and their transcripts. Real-book example lines are excluded; review references and notes before sharing a voice pack.</p>
        <button class="btn primary" id="export-project">${icon("download")} Preview export…</button>
      </div>
      <div class="card stack"><h2>Import project</h2><p class="muted small">Open an .abstudio file. Preview additions and conflicts before anything changes. Existing characters, voices and speaker corrections are kept by default.</p>
        <button class="btn primary" id="import-project">${icon("folder")} Open project…</button>
        <p class="small muted">Stop the queue and wait for it to finish before transferring a project. Import creates a local backup automatically. Missing chapter folders can be located in the preview.</p>
        <button class="btn" id="undo-project" ${history.last_import ? "" : "disabled"}>${icon("redo")} Undo last import</button>
      </div>
    </div><div id="import-preview"></div>
    <div class="card" style="margin-top:18px"><h3>Automatic backups</h3><p class="muted small">Installed apps store automatic import backups in Backups/Projects. These backups can include book text and personal voices; keep them private.</p>
      ${history.backups.length ? `<div class="log">${esc(history.backups.join("\n"))}</div>` : '<p class="muted small">No imports yet.</p>'}</div>`;
  $("#export-project").onclick = (e) => guard(async () => {
    const parts = $$("[data-export-part]:checked").map(input => input.dataset.exportPart);
    const result = await api("/api/project/export/preview", { method:"POST", body:{parts} });
    if (result.cancelled) return;
    const ok = await modal("Confirm project export", `<p>${esc(result.path)}</p><p>${result.characters} characters · ${result.voices} fixed voices · ${result.volumes} volumes · ${result.scripts} scripts · about ${(result.bytes/1024/1024).toFixed(1)} MB expanded.</p>
      ${result.parts.includes("cast") ? '<p>Voice references, transcripts and notes may contain private material. Review them before sharing a voice pack.</p>' : ""}
      ${result.contains_book_text ? '<div class="banner">This file will contain your book text. Do not share it publicly.</div>' : ""}
      ${result.exists ? '<p><b>The existing project file will be replaced.</b></p>' : ""}`,
      [{label:"Cancel",value:false},{label:result.exists ? "Replace file" : "Export project",value:true,primary:true}]);
    if (!ok) return;
    await api("/api/project/export/apply", {method:"POST",body:{token:result.token,confirm:true,overwrite:result.exists}});
    toast("Project exported");
  }, e.currentTarget);
  $("#import-project").onclick = (e) => guard(async () => {
    const result = await api("/api/project/import/preview", {method:"POST",body:{}});
    if (result.cancelled) return;
    importPreview = {...result, choices:{parts:result.summary.parts.filter(part => part !== "settings"),characters:[],voices:[],scripts:[],locations:{}}};
    drawImportPreview();
  }, e.currentTarget);
  $("#undo-project").onclick = (e) => guard(async () => {
    const preview = await api("/api/project/undo/preview",{method:"POST",body:{}});
    const ok = await modal("Restore the state before the last import?", `<p>Restore ${esc(preview.backup)}.</p><p><b>Current settings, cast, volumes and saved assignments will be replaced by that backup, including later edits.</b> Chapter audio and original manuscripts are not changed. A safety backup of the current state is saved first.</p>`,
      [{label:"Cancel",value:false},{label:"Restore backup",value:true,primary:true}]);
    if (!ok) return;
    await api("/api/project/undo/apply",{method:"POST",body:{token:preview.token,confirm:true}});
    importPreview = null;
    toast("Previous project state restored");
    await viewProject();
  }, e.currentTarget);
  if (importPreview) drawImportPreview();
}

function drawImportPreview() {
  const p = importPreview;
  const choices = p.choices;
  const names = {character:"characters", voice:"voices", script:"scripts"};
  $("#import-preview").innerHTML = `<div class="card stack" style="margin-top:18px"><h2>Preview import</h2>
    <p class="small muted">${esc(p.path)} · ${p.changes} files would change. Nothing has been written.</p>
    <div class="row">${p.summary.parts.map(key => `<label class="switch"><input type="checkbox" data-import-part="${key}" ${choices.parts.includes(key) ? "checked" : ""}><div>${PROJECT_PARTS[key]}</div></label>`).join("")}</div>
    ${p.contains_book_text ? '<div class="banner small">This project contains book text in its speaker assignments and may include edited spoken versions. Review override notices below and keep it private.</div>' : ""}
    <div style="overflow:auto"><table class="chapters"><thead><tr><th>Part</th><th>Name</th><th>Action</th><th>Details / choice</th></tr></thead><tbody>
      ${p.items.map(item => `<tr><td>${esc(item.kind)}</td><td>${esc(item.name)}</td><td>${esc(item.action)}</td><td>
        ${esc(item.reason || "")}
        ${item.source !== undefined ? `<div class="small muted">${esc(choices.locations[item.name] || item.source)}</div><button class="btn small" data-locate="${esc(item.name)}">Locate folder…</button>` : ""}
        ${item.conflict && names[item.kind] ? `<label class="switch"><input type="checkbox" data-conflict-kind="${names[item.kind]}" data-conflict-name="${esc(item.name)}" ${(choices[names[item.kind]] || []).includes(item.name) ? "checked" : ""}><div>Use imported (otherwise keep mine)</div></label>` : ""}
        ${item.changes && Object.keys(item.changes).length ? `<details><summary>Settings differences</summary><pre class="log">${esc(JSON.stringify(item.changes,null,2))}</pre></details>` : ""}
      </td></tr>`).join("")}</tbody></table></div>
    ${p.ignored.length ? `<p class="small muted">Ignored entries: ${esc(p.ignored.join(", "))}</p>` : ""}
    <div class="row"><button class="btn" id="refresh-import">Update preview</button><button class="btn primary" id="apply-import" ${p.changes ? "" : "disabled"}>Apply this preview</button></div>
    <p class="muted small" id="preview-note">A backup will be saved before applying. Review additions, skipped items and conflicts first.</p></div>`;
  const refresh = async () => {
    const result = await api("/api/project/import/preview",{method:"POST",body:{token:p.token,choices}});
    importPreview = {...result,choices};
    drawImportPreview();
  };
  const changed = () => {
    choices.parts = $$("[data-import-part]:checked").map(input => input.dataset.importPart);
    for (const key of Object.values(names)) choices[key] = $$(`[data-conflict-kind="${key}"]:checked`).map(input => input.dataset.conflictName);
    $("#apply-import").disabled = true;
    $("#preview-note").textContent = "Choices changed. Update the preview before applying.";
  };
  $$("[data-import-part], [data-conflict-kind]").forEach(input => input.onchange = changed);
  $$("[data-locate]").forEach(button => button.onclick = () => guard(async () => {
    const result = await api("/api/pick-folder",{method:"POST",body:{}});
    if (result.path) { choices.locations[button.dataset.locate] = result.path; await refresh(); }
  },button));
  $("#refresh-import").onclick = (e) => guard(refresh,e.currentTarget);
  $("#apply-import").onclick = (e) => guard(async () => {
    const ok = await modal("Apply project import?", `<p>Apply the ${p.changes} file changes shown in this preview? A private backup will be created first.</p>`,
      [{label:"Cancel",value:false},{label:"Apply import",value:true,primary:true}]);
    if (!ok) return;
    const result = await api("/api/project/import/apply",{method:"POST",body:{token:p.token,confirm:true}});
    importPreview = null;
    await viewProject();
    await modal("Import completed",`<p>${esc(result.message)}</p><p class="small muted">Backup: ${esc(result.backup || "No changes")}</p><div class="log">${esc(result.items.map(item => `${item.action}: ${item.kind} ${item.name}${item.reason ? " — "+item.reason : ""}`).join("\n"))}</div>`);
  },e.currentTarget);
}

/* ---------- start ---------- */
let pollTimer = null;
function pollNow() { clearTimeout(pollTimer); api("/api/status").then((s) => { workerState = s; renderWorker(); }).catch(() => {}); }

/* ---------- step-by-step guide (shown once, reopened from Guide in the sidebar) ---------- */
const GUIDE_KEY = "audiobook-studio-guide-v1";
const GUIDE = [
  { route: "#/", title: "Welcome to AudioBook Studio",
    text: "This short guide walks you from a folder of chapters to a finished audiobook in five steps. Skip it now if you like: you can reopen it anytime from <b>Guide</b> in the sidebar." },
  { route: "#/narrator", target: "#narrator-presets", title: "1. Choose the narrator",
    text: "A warm American narrator is already fixed, so every chapter sounds like the same person. Listen to the ready-made voices here, or describe your own, compare takes and choose <b>Fix voice</b>." },
  { route: "#/characters", target: "#new-character", title: "2. Add your characters",
    text: "Add the characters who speak. Each one keeps a single voice for the whole book: choose <b>Use a preset voice</b> for a ready-made voice, or describe one, listen and fix it. The <b>voice personality guide</b> helps you write good descriptions." },
  { route: "#/", target: "#add-volume", title: "3. Add a volume",
    text: "Choose a folder with numbered TXT or DOCX chapters, such as “1 - The beginning.txt”. Your files are only read, never changed." },
  { route: "#/", title: "4. Analyze and review",
    text: "Open the volume and start the job. The app finds the dialogue and who speaks. Lines it is unsure about wait for you under <b>Needs review</b>: open the chapter and click the yellow label to choose the speaker." },
  { route: "#/settings", target: "#view .card", title: "5. Generate and export",
    text: "Choose the export format here: MP3 for chapters, M4B for a whole volume with chapter markers. Optional MP4 video is off by default; enable it in the Video section or use Create video on a generated chapter. Jobs run in the background; finished chapters are kept when you stop." },
  { route: "#/", target: "#guide-button", title: "You're ready",
    text: "Start with one chapter and listen before generating a long volume. Use <b>Project</b> to back up or move your cast, fixed voices, settings and speaker assignments. Reopen this guide anytime from <b>Guide</b>." },
];
function guideSeen() { try { return localStorage.getItem(GUIDE_KEY) === "done"; } catch { return true; } }
function guideDone() { try { localStorage.setItem(GUIDE_KEY, "done"); } catch { /* storage unavailable: show again next time */ } }
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function showGuide(step) {
  $(".guide")?.remove();
  $$(".guide-target").forEach((element) => element.classList.remove("guide-target"));
  if (step < 0 || step >= GUIDE.length) return;
  const s = GUIDE[step];
  if ((location.hash || "#/") !== s.route) { location.hash = s.route; await pause(60); }
  for (let i = 0; i < 40 && s.target && !$(s.target); i++) await pause(100);  // wait for the page to render
  const target = s.target && $(s.target);
  if (target) { target.classList.add("guide-target"); target.scrollIntoView({ block: "center", behavior: "smooth" }); }
  const last = step === GUIDE.length - 1;
  const box = document.createElement("div");
  box.className = "guide";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "Guide");
  box.innerHTML = `<div class="row between"><span class="small muted">Step ${step + 1} of ${GUIDE.length}</span>
      <div class="dots">${GUIDE.map((_, i) => `<i class="${i === step ? "on" : ""}"></i>`).join("")}</div></div>
    <h3>${esc(s.title)}</h3><p>${s.text}</p>
    <div class="row between guide-actions"><button class="btn ghost small" data-g="skip">${last ? "Close" : "Skip guide"}</button>
      <div class="row">${step ? `<button class="btn small" data-g="back">Back</button>` : ""}
        <button class="btn primary small" data-g="next">${last ? "Finish" : "Next"}</button></div></div>`;
  box.addEventListener("click", (event) => {
    const action = event.target.closest("[data-g]")?.dataset.g;
    if (action === "back") showGuide(step - 1);
    else if (action === "next" && !last) showGuide(step + 1);
    else if (action) { guideDone(); showGuide(-1); }
  });
  document.body.append(box);
  $("[data-g=next]", box).focus();
}
$("#guide-button").onclick = () => showGuide(0);

route();
if (!guideSeen()) setTimeout(() => showGuide(0), 700);
pollWorker();
