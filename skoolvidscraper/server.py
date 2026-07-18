"""
Local helper server for the Chrome extension.

Start once:  python server.py
The extension POSTs {url, cookies, settings} to /scrape; this runs the existing
download + intake pipeline in a background thread. Poll /status for progress.

Binds to 127.0.0.1 only (localhost) - never exposed to the network.
"""
import json
import os
import tempfile
import threading

from flask import Flask, jsonify, request

from .cookie_loader import cookies_from_list
from .page_fetcher import fetch_lesson_page
from .discoverer import discover_lessons, classroom_dir_name
from .extractor import resolve_video_url
from .downloader import download_video
from .transcribe import run as transcribe_run

PORT = 8765
app = Flask(__name__)

# Single-job model: this is a personal, one-classroom-at-a-time tool.
_lock = threading.Lock()
JOB = {"status": "idle", "phase": "", "done": 0, "total": 0, "log": [], "error": None}


def load_config(path="config.json") -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _log(msg: str):
    JOB["log"].append(msg)
    print(msg, flush=True)


def _reset(status="running"):
    JOB.update(status=status, phase="", done=0, total=0, log=[], error=None)


def _worker(url: str, cookies: list, settings: dict):
    config = load_config()
    base_out = config.get("output_directory", "./downloads")
    fname = config.get("filename_template", "%(title)s.%(ext)s")
    # Each classroom gets its own subfolder so multiple classrooms never collide.
    out_dir = os.path.join(base_out, classroom_dir_name(url))

    try:
        JOB["phase"] = "Loading cookies"
        cookie_txt = os.path.join(tempfile.gettempdir(), "skool_live_cookies.txt")
        cookiejar, _ = cookies_from_list(cookies, cookie_txt)
        _log("Cookies loaded from browser session.")

        JOB["phase"] = "Discovering lessons"
        _log(f"Fetching classroom: {url}")
        html = fetch_lesson_page(url, cookiejar, wait_seconds=0)
        lessons = discover_lessons(url, html)
        JOB["total"] = len(lessons)
        _log(f"Discovered {len(lessons)} lesson(s) with videos.")

        JOB["phase"] = "Downloading"
        for i, lesson in enumerate(lessons, 1):
            _log(f"[{i}/{len(lessons)}] {lesson['lesson_title']}")

            video_url = lesson["video_url"]
            if not video_url:  # Mux lesson - resolve from its page
                info = resolve_video_url(lesson["lesson_url"], cookiejar)
                video_url = info["url"]
                if not video_url:
                    _log(f"    FAILED: {info['error']}")
                    JOB["done"] = i
                    continue

            success, message = download_video(
                video_url=video_url,
                output_dir=out_dir,
                filename_template=fname,
                skip_if_exists=config.get("skip_already_downloaded", True),
                max_height=int(settings.get("max_video_height", config.get("max_video_height", 720))),
                title=lesson["lesson_title"],
            )
            _log(f"    {'OK' if success else 'FAILED'}: {message}")
            JOB["done"] = i

        if settings.get("run_mode", "full") == "full":
            JOB["phase"] = "Transcribing + screenshots"
            _log("=== Building intake (transcripts + screenshots) ===")
            t = config.get("transcription", {})
            transcribe_run(
                target=out_dir,
                formats=settings.get("formats") or t.get("formats", ["txt", "srt", "json"]),
                model=settings.get("model") or t.get("model", "small.en"),
                device=t.get("device", "auto"),
                skip_if_exists=config.get("skip_already_downloaded", True),
                screenshots=bool(settings.get("screenshots", t.get("screenshots", True))),
                scene_threshold=t.get("scene_threshold", 0.25),
                max_interval=t.get("max_interval", 45),
            )

        JOB["phase"] = "Done"
        JOB["status"] = "done"
        _log("All done.")
    except Exception as e:
        JOB["status"] = "error"
        JOB["error"] = str(e)
        _log(f"ERROR: {e}")


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/status", methods=["GET"])
def status():
    return jsonify(JOB)


@app.route("/scrape", methods=["POST", "OPTIONS"])
def scrape():
    if request.method == "OPTIONS":
        return ("", 204)

    if JOB["status"] == "running":
        return jsonify({"ok": False, "error": "A job is already running."}), 409

    body = request.get_json(force=True, silent=True) or {}
    url = body.get("url", "")
    cookies = body.get("cookies", [])
    settings = body.get("settings", {})

    if "skool.com/" not in url or "/classroom" not in url:
        return jsonify({"ok": False, "error": "Open a Skool classroom tab first."}), 400
    if not cookies:
        return jsonify({"ok": False, "error": "No cookies received."}), 400

    with _lock:
        if JOB["status"] == "running":
            return jsonify({"ok": False, "error": "A job is already running."}), 409
        _reset("running")
        threading.Thread(target=_worker, args=(url, cookies, settings), daemon=True).start()

    return jsonify({"ok": True, "message": "Scrape started."})


def run_server():
    print(f"skoolVidScraper server on http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    run_server()
