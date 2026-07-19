const SERVER = "http://127.0.0.1:8765";

const el = (id) => document.getElementById(id);
let pollTimer = null;
let lessonResources = {}; // lesson id -> [{file_id, file_name, ...}] file resources
let isCommunity = false;  // true when the active tab is a community classroom index

const escapeHtml = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- settings persistence -------------------------------------------------
const DEFAULTS = {
  run_mode: "full",
  max_video_height: "720",
  model: "small.en",
  screenshots: true,
  formats: ["txt", "srt", "json"],
};

function readSettings() {
  return {
    run_mode: document.querySelector("#mode .active").dataset.val,
    max_video_height: el("quality").value,
    model: el("model").value,
    screenshots: el("screenshots").checked,
    formats: [...document.querySelectorAll("#fmtset input:checked")].map((c) => c.value),
  };
}

function applySettings(s) {
  document.querySelectorAll("#mode button").forEach((b) =>
    b.classList.toggle("active", b.dataset.val === s.run_mode));
  el("quality").value = s.max_video_height;
  el("model").value = s.model;
  el("screenshots").checked = s.screenshots;
  document.querySelectorAll("#fmtset input").forEach((c) =>
    (c.checked = s.formats.includes(c.value)));
  syncModeUI();
}

function saveSettings() {
  chrome.storage.local.set({ settings: readSettings() });
}

// Disable format/screenshot controls when in download-only mode.
function syncModeUI() {
  const full = document.querySelector("#mode .active").dataset.val === "full";
  el("fmtset").style.opacity = full ? "1" : ".4";
  el("fmtset").style.pointerEvents = full ? "auto" : "none";
  el("screenshots").disabled = !full;
}

// ---- server + scrape ------------------------------------------------------
async function pingServer() {
  try {
    const s = await (await fetch(`${SERVER}/status`)).json();
    el("srvdot").className = "dot ok";
    el("srvtxt").textContent = "server connected";
    el("scrape").disabled = false;
    renderStatus(s);
    if (s.busy) startPolling();
    // Always populate the picker for the current tab so more can be queued,
    // even while another job runs.
    loadLessons();
    return true;
  } catch {
    el("srvdot").className = "dot err";
    el("srvtxt").textContent = "server offline (run: skoolvidscraper serve)";
    el("scrape").disabled = true;
    return false;
  }
}

async function getActiveTabUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ? tab.url : "";
}

async function getSkoolCookies() {
  return chrome.cookies.getAll({ domain: "skool.com" });
}

// ---- lesson picker --------------------------------------------------------
function showPicker(show) {
  el("lessonset").style.display = show ? "" : "none";
}

function setAllLessons(checked) {
  document.querySelectorAll("#lessons .lesson").forEach((c) => (c.checked = checked));
  updateLessonCount();
}

function updateLessonCount() {
  const all = [...document.querySelectorAll("#lessons .lesson")];
  el("lcount").textContent = `${all.filter((c) => c.checked).length} of ${all.length} selected`;
  document.querySelectorAll("#lessons .lsec").forEach((sec) => {
    const items = [...sec.querySelectorAll(".lesson")];
    const on = items.filter((c) => c.checked).length;
    const head = sec.querySelector(".sec");
    head.checked = on === items.length;
    head.indeterminate = on > 0 && on < items.length;
  });
}

function getSelectedLessonIds() {
  return [...document.querySelectorAll("#lessons .lesson:checked")].map((c) => c.dataset.id);
}

function renderLessons(lessons) {
  const box = el("lessons");
  box.innerHTML = "";
  let group = null, section = Symbol();
  for (const L of lessons) {
    if ((L.section || "General") !== section) {
      section = L.section || "General";
      group = document.createElement("div");
      group.className = "lsec";
      const head = document.createElement("label");
      head.className = "sechead";
      const sc = document.createElement("input");
      sc.type = "checkbox"; sc.className = "sec"; sc.checked = true;
      const sp = document.createElement("span");
      sp.textContent = section;
      head.append(sc, sp);
      sc.addEventListener("change", () => {
        group.querySelectorAll(".lesson").forEach((c) => (c.checked = sc.checked));
        updateLessonCount();
      });
      group.appendChild(head);
      box.appendChild(group);
    }
    const row = document.createElement("label");
    row.className = "lrow";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.className = "lesson"; cb.checked = true; cb.dataset.id = L.id;
    cb.addEventListener("change", updateLessonCount);
    const sp = document.createElement("span");
    sp.textContent = L.title; sp.title = L.title;
    row.append(cb, sp);
    group.appendChild(row);
  }
  updateLessonCount();
}

function renderClassrooms(classrooms) {
  const box = el("lessons");
  box.innerHTML = "";
  for (const c of classrooms) {
    const row = document.createElement("div");
    row.className = "lrow";
    const sp = document.createElement("span");
    sp.textContent = c.title;
    sp.title = c.title;
    row.appendChild(sp);
    box.appendChild(row);
  }
}

async function loadLessons() {
  const url = await getActiveTabUrl();
  if (!url.includes("skool.com/") || !url.includes("/classroom")) { showPicker(false); return; }
  showPicker(true);
  el("lcount").textContent = "loading…";
  el("lessons").innerHTML = "";
  isCommunity = false;
  lessonResources = {};
  try {
    const cookies = await getSkoolCookies();
    const j = await (await fetch(`${SERVER}/discover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookies }),
    })).json();
    if (!j.ok) { el("lcount").textContent = j.error || "could not load"; return; }
    if (j.classrooms) {
      // Community index: this scrape will recurse every classroom.
      isCommunity = true;
      el("lall").style.display = el("lnone").style.display = "none";
      el("lcount").textContent = `${j.classrooms.length} classrooms in this community`;
      renderClassrooms(j.classrooms);
      el("scrape").textContent = `Scrape all ${j.classrooms.length} classrooms`;
    } else {
      el("lall").style.display = el("lnone").style.display = "";
      renderLessons(j.lessons || []);
      for (const L of j.lessons || [])
        lessonResources[L.id] = (L.resources || []).filter((r) => r.type === "file");
      el("scrape").textContent = "Scrape this classroom";
    }
  } catch {
    el("lcount").textContent = "could not load lessons";
  }
}

function renderStatus(s) {
  const bar = el("bar");
  const view = s.active || s.last;
  if (view) {
    el("status").textContent =
      view.status === "error" ? `${view.title}: ${view.error}` :
      view.phase ? `${view.title}: ${view.phase}${view.total ? `  (${view.done}/${view.total})` : ""}`
                 : `${view.title}: ${view.status}`;
    if (view.status === "running" && view.total) {
      // blend the current download % into the overall lesson progress so the bar
      // advances smoothly even on a single long video.
      const frac = (view.done + (view.pct || 0) / 100) / view.total;
      bar.style.display = "block";
      bar.querySelector("i").style.width = `${Math.round(frac * 100)}%`;
    } else if (view.status === "done") {
      bar.style.display = "block";
      bar.querySelector("i").style.width = "100%";
    } else {
      bar.style.display = "none";
    }
    el("log").textContent = (view.log || []).slice(-40).join("\n");
    el("log").scrollTop = el("log").scrollHeight;
  } else {
    el("status").textContent = "";
    bar.style.display = "none";
    el("log").textContent = "";
  }
  renderQueue(s);
}

function renderQueue(s) {
  const q = el("queue");
  const rows = [];
  if (s.active) rows.push(["run", "run", s.active.title]);
  for (const j of s.queue || []) rows.push(["queued", "", j.title]);
  for (const j of (s.recent || []).slice(-3)) {
    const badge = j.status === "error" ? "failed" : j.status === "skipped" ? "no access" : "done";
    rows.push([badge, j.status === "error" ? "err" : "", j.title]);
  }
  if (!rows.length) { q.style.display = "none"; return; }
  q.style.display = "block";
  q.innerHTML = `<div class="qh">Queue</div>` + rows.map(([badge, cls, name]) =>
    `<div class="qrow"><span class="qbadge ${cls}">${badge}</span><span class="qname">${escapeHtml(name)}</span></div>`
  ).join("");
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const s = await (await fetch(`${SERVER}/status`)).json();
      renderStatus(s);
      if (!s.busy) clearInterval(pollTimer);
    } catch {
      clearInterval(pollTimer);
      pingServer();
    }
  }, 1200);
}

// Resolve signed download URLs for Skool-hosted files. Runs in the browser so it
// passes Skool's api2 WAF (which blocks the server); the returned files.skool.com
// URLs are pre-signed and the server downloads them without auth.
async function resolveResourceUrls(fileIds) {
  const map = {};
  for (const fid of fileIds) {
    try {
      const r = await fetch(`https://api2.skool.com/files/${fid}/download-url?expire=28800`,
        { method: "POST", credentials: "include" });
      if (!r.ok) continue;
      const text = (await r.text()).trim();
      let url = text;
      try {
        const j = JSON.parse(text);
        url = typeof j === "string" ? j : (j.url || j.download_url || j.downloadUrl || url);
      } catch { /* plain-text URL */ }
      if (typeof url === "string" && url.startsWith("http")) map[fid] = url;
    } catch { /* skip this file */ }
  }
  return map;
}

async function scrape() {
  const url = await getActiveTabUrl();
  if (!url.includes("skool.com/") || !url.includes("/classroom")) {
    el("status").textContent = "Open a Skool classroom tab first.";
    return;
  }
  // If the lesson picker is populated, send only the checked lessons.
  let lesson_ids = null;
  if (el("lessonset").style.display !== "none" && document.querySelectorAll("#lessons .lesson").length) {
    lesson_ids = getSelectedLessonIds();
    if (!lesson_ids.length) { el("status").textContent = "Select at least one lesson."; return; }
  }
  el("scrape").disabled = true;

  // Resolve attached-file download URLs for the selected lessons (browser-side).
  const selIds = lesson_ids || Object.keys(lessonResources);
  const fileIds = [...new Set(
    selIds.flatMap((id) => (lessonResources[id] || []).map((r) => r.file_id).filter(Boolean))
  )];
  let resource_urls = {};
  if (fileIds.length) {
    el("status").textContent = `Resolving ${fileIds.length} attachment(s)…`;
    resource_urls = await resolveResourceUrls(fileIds);
  }

  el("status").textContent = "Reading cookies…";
  const cookies = await getSkoolCookies();
  try {
    const r = await fetch(`${SERVER}/scrape`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookies, settings: readSettings(), lesson_ids, resource_urls }),
    });
    const j = await r.json();
    if (!j.ok) { el("status").textContent = j.error || "Failed to start."; el("scrape").disabled = false; return; }
    el("status").textContent = j.message || "Queued.";
    el("scrape").disabled = false;  // queueing allowed: line up more classrooms
    startPolling();
  } catch {
    el("status").textContent = "Could not reach server.";
    el("scrape").disabled = false;
  }
}

// ---- wire up --------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  const stored = await chrome.storage.local.get("settings");
  applySettings({ ...DEFAULTS, ...(stored.settings || {}) });

  document.querySelectorAll("#mode button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#mode button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      syncModeUI();
      saveSettings();
    }));
  ["quality", "model", "screenshots"].forEach((id) =>
    el(id).addEventListener("change", saveSettings));
  document.querySelectorAll("#fmtset input").forEach((c) =>
    c.addEventListener("change", saveSettings));

  el("lall").addEventListener("click", () => setAllLessons(true));
  el("lnone").addEventListener("click", () => setAllLessons(false));

  el("scrape").addEventListener("click", scrape);
  pingServer();

  // In the side panel (which stays open across navigation), keep the picker in
  // sync with whatever classroom tab is active. No-op in the popup, which closes.
  if (chrome.tabs?.onActivated) {
    chrome.tabs.onActivated.addListener(() => loadLessons());
    chrome.tabs.onUpdated.addListener((_id, info, tab) => {
      if (info.status === "complete" && tab.active) loadLessons();
    });
  }
});
