const SERVER = "http://127.0.0.1:8765";

const el = (id) => document.getElementById(id);
let pollTimer = null;

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
    const r = await fetch(`${SERVER}/status`);
    const j = await r.json();
    el("srvdot").className = "dot ok";
    el("srvtxt").textContent = "server connected";
    el("scrape").disabled = false;
    if (j.status === "running") startPolling();
    // Job finished while the popup was closed: show its final summary + log.
    else if (j.status === "done" || j.status === "error") renderStatus(j);
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

function renderStatus(j) {
  const bar = el("bar");
  el("status").textContent =
    j.status === "error" ? `Error: ${j.error}` :
    j.phase ? `${j.phase}${j.total ? `  (${j.done}/${j.total})` : ""}` : j.status;
  if (j.status === "running" && j.total) {
    bar.style.display = "block";
    bar.querySelector("i").style.width = `${Math.round((j.done / j.total) * 100)}%`;
  }
  if (j.status === "done") { bar.style.display = "block"; bar.querySelector("i").style.width = "100%"; }
  el("log").textContent = (j.log || []).slice(-40).join("\n");
  el("log").scrollTop = el("log").scrollHeight;
}

function startPolling() {
  el("scrape").disabled = true;
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const j = await (await fetch(`${SERVER}/status`)).json();
      renderStatus(j);
      if (j.status === "done" || j.status === "error") {
        clearInterval(pollTimer);
        el("scrape").disabled = false;
      }
    } catch {
      clearInterval(pollTimer);
      pingServer();
    }
  }, 1200);
}

async function scrape() {
  const url = await getActiveTabUrl();
  if (!url.includes("skool.com/") || !url.includes("/classroom")) {
    el("status").textContent = "Open a Skool classroom tab first.";
    return;
  }
  el("scrape").disabled = true;
  el("status").textContent = "Reading cookies…";
  const cookies = await getSkoolCookies();
  try {
    const r = await fetch(`${SERVER}/scrape`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookies, settings: readSettings() }),
    });
    const j = await r.json();
    if (!j.ok) { el("status").textContent = j.error || "Failed to start."; el("scrape").disabled = false; return; }
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

  el("scrape").addEventListener("click", scrape);
  pingServer();
});
