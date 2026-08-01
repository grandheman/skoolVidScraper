# skoolVidScraper

## What this does
Intake engine for Skool classrooms (NotebookLM-style, for AI agents).
Discovers and downloads every classroom video (low-res, for processing only),
then transcribes each and captures a screenshot at every on-screen change, so a
downstream AI agent gets both what was said and what was on screen at each moment.
Authenticates via live browser cookies (no browser automation, no passwords).

## Stack
- browser-cookie3: fallback for reading Chrome cookies directly from disk
- requests: fetches Skool classroom and lesson pages
- discoverer.py: parses __NEXT_DATA__ JSON to build the full lesson list from one classroom fetch
- extractor.py: per-lesson video URL resolution (direct videoLink or Mux signed HLS)
- yt-dlp: downloads videos (supports YouTube, Vimeo, Loom, Wistia, Mux, etc.)
- Node.js: required by yt-dlp to resolve HD YouTube format URLs
- transcriber.py: local Whisper ASR via faster-whisper (GPU/CPU auto-detect)
- screenshots.py: ffmpeg scene-change frame capture (one frame per slide/visual change)
- transcribe.py: intake orchestrator + CLI. Merges transcript + screenshots into
  agent-readable output (segments carry the screenshot on screen at that moment)
- ffmpeg: required for screenshots (install: winget install Gyan.FFmpeg)
- server.py: Flask helper (localhost:8765) the Chrome extension talks to
- cli.py: the `skoolvidscraper` command (subcommands: serve, tray, scrape, transcribe)
- tray.py: system-tray launcher for the server (pystray; `skoolvidscraper tray`)
- console.py: ensure_utf8_output(), called by every entry point (see Text encoding)
- extension/: Manifest V3 Chrome extension. Reads the active classroom URL + live
  Skool cookies (chrome.cookies API) and POSTs them to server.py. Settings (run mode,
  quality, model, formats, screenshots) live in the popup UI and override config.json.

All Python lives in the `skoolvidscraper/` package; `pyproject.toml` installs it
and exposes the `skoolvidscraper` console command. `extension/` and `config.json`
stay at the repo root.

## Key config
config.json (gitignored; copy from config.example.json). Key field: `classroom_url`.
Downloads land in `output_directory/<Classroom Title>/` (one subfolder per classroom,
named by the classroom title from __NEXT_DATA__; falls back to <community>-<classroomId>).
Each folder gets an INGEST.md telling a downstream AI agent how to read the files.

## Video hosting styles
- Direct `videoLink` in the lesson tree (Wistia/YouTube/Loom): used as-is.
- Mux signed HLS: the tree only carries a `videoId`; extractor.py resolves the
  per-lesson `playbackId` + signed `playbackToken` from `pageProps.video` and builds
  `stream.mux.com/<id>.m3u8?token=<jwt>`. yt-dlp needs `--referer https://www.skool.com/`
  (the token enforces it) and ffmpeg to merge the separate HLS video/audio streams.

## Chrome extension (one-click launcher)
Removes the manual cookies.txt export and the config.json edit. Flow:
1. `pip install .` then start the helper: `skoolvidscraper serve`
   (or `skoolvidscraper tray` for a system-tray app; binds 127.0.0.1:8765)
2. Load `extension/` unpacked: chrome://extensions -> Developer mode -> Load unpacked
3. Open a Skool classroom tab, click the extension, adjust settings, hit Scrape.
The extension reads the active tab URL + live Skool cookies (chrome.cookies API,
includes HttpOnly auth cookies) and POSTs {url, cookies, settings} to server.py.
Popup settings override config.json; config.json remains the server-side fallback.
The popup shows a lesson checklist (grouped by section) so you scrape only what you
pick; the server exposes POST /discover (lessons, no download) and /scrape accepts an
optional `lesson_ids` list. CLI equivalents: `scrape --lessons 1-5,8` / `--section NAME`.
server.py runs one job at a time and exposes GET /status for progress polling.
Only one server can hold port 8765; when restarting, stop the old one first.

## Cookie loading priority
1. cookies.txt (Netscape format): auto-detected in project root
2. cookies.json (Chrome extension JSON export): auto-detected, converted to Netscape for yt-dlp
3. browser-cookie3 direct Chrome read: fallback, may fail on Chrome 127+ (App-Bound Encryption)

## To run
pip install .                       # installs the `skoolvidscraper` command
skoolvidscraper scrape --transcribe # CLI: download classroom (config.json) + build intake
skoolvidscraper serve               # or start the server for the Chrome extension
skoolvidscraper tray                # server as a system-tray app (needs the [tray] extra)

## Intake (transcription + screenshots)
Local Whisper (faster-whisper) + ffmpeg scene-change screenshots. No API key, offline.
Auto-uses NVIDIA GPU if present (cuBLAS/cuDNN come from the pip nvidia-*-cu12 packages;
transcriber.py registers their DLL dirs on Windows), else falls back to CPU.
- Standalone: `skoolvidscraper transcribe` (recurses output_directory, skipping frames dirs)
- With download run: `skoolvidscraper scrape --transcribe`
- Flags: `--formats txt srt json`, `--model small.en`, `--device auto|cuda|cpu`,
  `--no-screenshots`, `--scene-threshold 0.25` (lower = more frames),
  `--max-interval 45` (guarantee a frame every N seconds; 0 = pure scene-change)
- Defaults live in config.json under `transcription`. Set `after_download: true` to
  run intake automatically on every `python main.py` run.
- Output next to each video: <video>.txt, <video>.srt, <video>.json, and
  frames/<video>/HH-MM-SS.jpg. The .json is the agent-facing artifact: each transcript
  segment carries the screenshot filename that was on screen at that timestamp, plus a
  top-level screenshots list. Already-processed files are skipped.

## Text encoding (Windows)
Skool section and lesson titles are full of emoji, and Python on Windows defaults
to the cp1252 locale codec, which has no mapping for bytes 0x81/0x8D/0x8F/0x90/0x9D.
Both directions have bitten this project, so both are now handled:
- Reading a subprocess: always pass `encoding="utf-8", errors="replace"` to
  subprocess.run/Popen. Bare `text=True` uses the locale codec and crashes on the
  UTF-8 path ffmpeg and yt-dlp echo back. A folder named "🏁 ..." (0x8F) killed
  every lesson under it, while "🌱 ..." (0x8C, defined in cp1252) survived, so the
  symptom looks like random per-classroom flakiness.
- Printing: console.ensure_utf8_output() reconfigures stdout/stderr to UTF-8 at
  each entry point (cli, main, server, transcribe). A real console is UTF-8, but
  redirecting to a file or pipe drops to cp1252 and printing a title raises.

## Error handling rules
- Never crash the full run due to a single lesson failure
- Log every failure with a clear reason and continue
- Guard per-lesson work with `except Exception`, not a specific type. A narrower
  `except RuntimeError` let a UnicodeDecodeError through and discarded ASR that
  had already finished.
- If cookies fail to load or classroom discovery fails, exit early with a helpful message
