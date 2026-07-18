"""
Local helper server for the Chrome extension.

Start once:  skoolvidscraper serve
The extension POSTs {url, cookies, settings, ...} to /scrape. Jobs run ONE AT A
TIME in a background worker, but they queue: line up several classrooms, or point
at a community index to enqueue every classroom in it, then walk away. Poll
/status for the active job + the pending queue.

Binds to 127.0.0.1 only (localhost) - never exposed to the network.
"""
import itertools
import json
import os
import queue as queuelib
import tempfile
import threading

import requests
from flask import Flask, jsonify, request

from .cookie_loader import cookies_from_list
from .page_fetcher import fetch_lesson_page
from .discoverer import (discover_lessons, discover_classrooms, is_classroom_url,
                         classroom_dir_name, community_dir_name, safe_base)
from .extractor import resolve_video_url
from .downloader import download_video
from .transcribe import run as transcribe_run, write_resources_manifest

PORT = 8765
app = Flask(__name__)

# Jobs run one at a time (a personal tool; one classroom's downloads should not
# fight another's for GPU/network). A FIFO queue lets you line up many classrooms
# or a whole community and walk away.
_state_lock = threading.Lock()
_jobs = {}                    # id -> job dict
_order = []                   # job ids, submission order
_work_q = queuelib.Queue()
_ids = itertools.count(1)
_worker_started = False


def load_config(path="config.json") -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _log(job: dict, msg: str):
    job["log"].append(msg)
    print(f"[job {job['id']}] {msg}", flush=True)


def _new_job(url, cookies, settings, lesson_ids, resource_urls, title=None) -> dict:
    """Register a job and put it on the work queue (a single worker drains it)."""
    jid = next(_ids)
    job = {
        "id": jid, "url": url, "cookies": cookies, "settings": settings or {},
        "lesson_ids": lesson_ids, "resource_urls": resource_urls or {},
        "title": title or url, "status": "queued",
        "phase": "", "done": 0, "total": 0, "pct": 0, "log": [], "error": None,
    }
    with _state_lock:
        _jobs[jid] = job
        _order.append(jid)
    _work_q.put(jid)
    return job


def _public(job: dict) -> dict:
    """Job fields safe to expose (never cookies or token-bearing URLs)."""
    return {k: job[k] for k in
            ("id", "title", "status", "phase", "done", "total", "pct", "error")}


def _with_log(job: dict) -> dict:
    d = _public(job)
    d["log"] = job["log"][-40:]
    return d


def _download_lesson_resources(out_dir: str, lesson: dict, resource_urls: dict, job: dict) -> int:
    """
    Download a lesson's Skool-hosted file resources using the signed URLs the
    extension resolved (the server can't pass the api2.skool.com WAF itself, but
    the returned files.skool.com URLs are pre-signed and need no auth). Records a
    local `path` on each downloaded resource. Returns the number saved.
    """
    base = safe_base(lesson["lesson_title"])
    saved = 0
    for res in lesson.get("resources", []):
        if res.get("type") != "file":
            continue
        signed = (resource_urls or {}).get(res.get("file_id"))
        if not signed:
            continue
        dest_dir = os.path.join(out_dir, "resources", base)
        fname = res.get("file_name") or f"{res.get('file_id')}.bin"
        try:
            os.makedirs(dest_dir, exist_ok=True)
            rr = requests.get(signed, timeout=120)
            rr.raise_for_status()
            with open(os.path.join(dest_dir, fname), "wb") as f:
                f.write(rr.content)
            res["path"] = f"resources/{base}/{fname}"
            saved += 1
        except Exception as e:
            _log(job, f"    resource FAILED ({fname}): {e}")
    return saved


def _run_job(job: dict):
    """Download one classroom (videos + attached files) and optionally build intake."""
    config = load_config()
    base_out = config.get("output_directory", "./downloads")
    fname = config.get("filename_template", "%(title)s.%(ext)s")
    url = job["url"]

    job["phase"] = "Loading cookies"
    # Per-job cookie file so queued jobs never clobber each other's cookies.
    cookie_txt = os.path.join(tempfile.gettempdir(), f"skool_cookies_{job['id']}.txt")
    cookiejar, _ = cookies_from_list(job["cookies"], cookie_txt)
    _log(job, "Cookies loaded from browser session.")

    job["phase"] = "Discovering lessons"
    _log(job, f"Fetching classroom: {url}")
    html = fetch_lesson_page(url, cookiejar, wait_seconds=0)
    all_lessons = discover_lessons(url, html)
    if job["lesson_ids"]:
        wanted = set(job["lesson_ids"])
        lessons = [L for L in all_lessons if L["lesson_id"] in wanted]
    else:
        lessons = all_lessons
    job["total"] = len(lessons)
    job["title"] = classroom_dir_name(url, html)
    _log(job, f"Discovered {len(all_lessons)} lesson(s); scraping {len(lessons)}.")

    # Output nests as <community>/<classroom>/ (falls back to URL slug/id).
    out_dir = os.path.join(base_out, community_dir_name(url, html),
                           classroom_dir_name(url, html))

    # Capture every lesson's non-video content (description + resources) up front.
    write_resources_manifest(out_dir, lessons)

    job["phase"] = "Downloading"
    for i, lesson in enumerate(lessons, 1):
        _log(job, f"[{i}/{len(lessons)}] {lesson['lesson_title']}")

        # Download attached files (both video and doc-only lessons can have them).
        nres = _download_lesson_resources(out_dir, lesson, job["resource_urls"], job)
        if nres:
            _log(job, f"    {nres} resource file(s) saved")

        # Doc-only lesson (no video): nothing more to download.
        if not lesson.get("has_video"):
            _log(job, "    (doc-only lesson)")
            job["done"] = i
            continue

        video_url = lesson["video_url"]
        if not video_url:  # Mux lesson - resolve from its page
            info = resolve_video_url(lesson["lesson_url"], cookiejar)
            video_url = info["url"]
            if not video_url:
                _log(job, f"    FAILED: {info['error']}")
                job["done"] = i
                continue

        n = len(lessons)
        job["pct"] = 0

        def _prog(pct, _i=i, _n=n):
            job["pct"] = pct
            job["phase"] = f"Downloading {_i}/{_n} ({pct:.0f}%)"

        success, message = download_video(
            video_url=video_url,
            output_dir=out_dir,
            filename_template=fname,
            skip_if_exists=config.get("skip_already_downloaded", True),
            max_height=int(job["settings"].get("max_video_height",
                                               config.get("max_video_height", 720))),
            title=lesson["lesson_title"],
            progress_cb=_prog,
        )
        job["pct"] = 0
        _log(job, f"    {'OK' if success else 'FAILED'}: {message}")
        job["done"] = i

    # Rewrite the manifest so downloaded files now carry their local path
    # (and the transcribe step's per-lesson JSON picks it up).
    write_resources_manifest(out_dir, lessons)

    if job["settings"].get("run_mode", "full") == "full":
        job["phase"] = "Transcribing + screenshots"
        _log(job, "=== Building intake (transcripts + screenshots) ===")
        t = config.get("transcription", {})
        transcribe_run(
            target=out_dir,
            formats=job["settings"].get("formats") or t.get("formats", ["txt", "srt", "json"]),
            model=job["settings"].get("model") or t.get("model", "small.en"),
            device=t.get("device", "auto"),
            skip_if_exists=config.get("skip_already_downloaded", True),
            screenshots=bool(job["settings"].get("screenshots", t.get("screenshots", True))),
            scene_threshold=t.get("scene_threshold", 0.25),
            max_interval=t.get("max_interval", 45),
        )

    job["phase"] = "Done"


def _worker_loop():
    """Single worker: drain the queue one job at a time (no concurrent jobs)."""
    while True:
        jid = _work_q.get()
        job = _jobs.get(jid)
        if job is None:
            _work_q.task_done()
            continue
        job["status"] = "running"
        try:
            _run_job(job)
            job["status"] = "done"
            _log(job, "All done.")
        except Exception as e:
            # One classroom failing must never abort the rest of the queue.
            job["status"] = "error"
            job["error"] = str(e)
            _log(job, f"ERROR: {e}")
        finally:
            _work_q.task_done()


def _ensure_worker():
    global _worker_started
    with _state_lock:
        if not _worker_started:
            threading.Thread(target=_worker_loop, daemon=True).start()
            _worker_started = True


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/status", methods=["GET"])
def status():
    with _state_lock:
        jobs = [_jobs[i] for i in _order]
    active = next((j for j in jobs if j["status"] == "running"), None)
    finished = [j for j in jobs if j["status"] in ("done", "error")]
    return jsonify({
        "active": _with_log(active) if active else None,
        "last": _with_log(finished[-1]) if finished else None,
        "queue": [_public(j) for j in jobs if j["status"] == "queued"],
        "recent": [_public(j) for j in finished[-10:]],
        "busy": active is not None or any(j["status"] == "queued" for j in jobs),
    })


@app.route("/discover", methods=["POST", "OPTIONS"])
def discover():
    """Return the classroom's lesson list (no download) so the popup can offer a picker."""
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(force=True, silent=True) or {}
    url = body.get("url", "")
    cookies = body.get("cookies", [])
    if "skool.com/" not in url or "/classroom" not in url:
        return jsonify({"ok": False, "error": "Open a Skool classroom tab first."}), 400
    if not cookies:
        return jsonify({"ok": False, "error": "No cookies received."}), 400

    try:
        cookie_txt = os.path.join(tempfile.gettempdir(), "skool_live_cookies.txt")
        cookiejar, _ = cookies_from_list(cookies, cookie_txt)
        html = fetch_lesson_page(url, cookiejar, wait_seconds=0)
        # Community index: describe the classrooms that a scrape would enqueue.
        if not is_classroom_url(url):
            classrooms = discover_classrooms(url, html)
            return jsonify({
                "ok": True,
                "community": community_dir_name(url, html),
                "classrooms": [{"id": c["id"], "title": c["title"]} for c in classrooms],
            })
        lessons = discover_lessons(url, html)
        return jsonify({
            "ok": True,
            "title": classroom_dir_name(url, html),
            "lessons": [
                {"id": L["lesson_id"], "title": L["lesson_title"], "section": L["section_title"],
                 "resources": L.get("resources", [])}
                for L in lessons
            ],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/scrape", methods=["POST", "OPTIONS"])
def scrape():
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(force=True, silent=True) or {}
    url = body.get("url", "")
    cookies = body.get("cookies", [])
    settings = body.get("settings", {})
    lesson_ids = body.get("lesson_ids")            # optional; None = whole classroom
    resource_urls = body.get("resource_urls") or {}  # {file_id: signed_url} from the extension

    if "skool.com/" not in url or "/classroom" not in url:
        return jsonify({"ok": False, "error": "Open a Skool classroom tab first."}), 400
    if not cookies:
        return jsonify({"ok": False, "error": "No cookies received."}), 400

    _ensure_worker()

    # Community index URL: enqueue one job per classroom in the community. There is
    # no per-classroom attachment resolution in this mode (that needs the extension
    # on each classroom page); videos + resource metadata are still captured.
    if not is_classroom_url(url):
        try:
            cookie_txt = os.path.join(tempfile.gettempdir(), "skool_live_cookies.txt")
            cookiejar, _ = cookies_from_list(cookies, cookie_txt)
            html = fetch_lesson_page(url, cookiejar, wait_seconds=0)
            classrooms = discover_classrooms(url, html)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Could not read community: {e}"}), 500
        if not classrooms:
            return jsonify({"ok": False, "error": "No classrooms found in this community."}), 404
        ids = [_new_job(c["classroom_url"], cookies, settings, None, {}, title=c["title"])["id"]
               for c in classrooms]
        return jsonify({"ok": True, "message": f"Queued {len(ids)} classroom(s).", "job_ids": ids})

    job = _new_job(url, cookies, settings, lesson_ids, resource_urls)
    return jsonify({"ok": True, "message": "Queued.", "job_id": job["id"]})


def run_server():
    from .ffmpeg_setup import ensure_ffmpeg
    ensure_ffmpeg()
    _ensure_worker()
    print(f"skoolVidScraper server on http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    run_server()
