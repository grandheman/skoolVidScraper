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
- extension/: Manifest V3 Chrome extension. Reads the active classroom URL + live
  Skool cookies (chrome.cookies API) and POSTs them to server.py. Settings (run mode,
  quality, model, formats, screenshots) live in the popup UI and override config.json.

## Key config
config.json (gitignored; copy from config.example.json). Key field: `classroom_url`.
Downloads land in `output_directory/<community>-<classroomId>/` (one subfolder per classroom).

## Video hosting styles
- Direct `videoLink` in the lesson tree (Wistia/YouTube/Loom): used as-is.
- Mux signed HLS: the tree only carries a `videoId`; extractor.py resolves the
  per-lesson `playbackId` + signed `playbackToken` from `pageProps.video` and builds
  `stream.mux.com/<id>.m3u8?token=<jwt>`. yt-dlp needs `--referer https://www.skool.com/`
  (the token enforces it) and ffmpeg to merge the separate HLS video/audio streams.

## Chrome extension (one-click launcher)
Removes the manual cookies.txt export and the config.json edit. Flow:
1. `pip install flask` and start the helper: `python server.py` (binds 127.0.0.1:8765)
2. Load `extension/` unpacked: chrome://extensions -> Developer mode -> Load unpacked
3. Open a Skool classroom tab, click the extension, adjust settings, hit Scrape.
The extension reads the active tab URL + live Skool cookies (chrome.cookies API,
includes HttpOnly auth cookies) and POSTs {url, cookies, settings} to server.py.
Popup settings override config.json; config.json remains the server-side fallback.
server.py runs one job at a time and exposes GET /status for progress polling.
Only one server can hold port 8765; when restarting, stop the old one first.

## Cookie loading priority
1. cookies.txt (Netscape format): auto-detected in project root
2. cookies.json (Chrome extension JSON export): auto-detected, converted to Netscape for yt-dlp
3. browser-cookie3 direct Chrome read: fallback, may fail on Chrome 127+ (App-Bound Encryption)

## To run
pip install -r requirements.txt
python main.py

## Intake (transcription + screenshots)
Local Whisper (faster-whisper) + ffmpeg scene-change screenshots. No API key, offline.
Auto-uses NVIDIA GPU if present (cuBLAS/cuDNN come from the pip nvidia-*-cu12 packages;
transcriber.py registers their DLL dirs on Windows), else falls back to CPU.
- Standalone: `python transcribe.py` (recurses output_directory, skipping frames dirs)
- With download run: `python main.py --transcribe`
- Flags: `--formats txt srt json`, `--model small.en`, `--device auto|cuda|cpu`,
  `--no-screenshots`, `--scene-threshold 0.25` (lower = more frames),
  `--max-interval 45` (guarantee a frame every N seconds; 0 = pure scene-change)
- Defaults live in config.json under `transcription`. Set `after_download: true` to
  run intake automatically on every `python main.py` run.
- Output next to each video: <video>.txt, <video>.srt, <video>.json, and
  frames/<video>/HH-MM-SS.jpg. The .json is the agent-facing artifact: each transcript
  segment carries the screenshot filename that was on screen at that timestamp, plus a
  top-level screenshots list. Already-processed files are skipped.

## Error handling rules
- Never crash the full run due to a single lesson failure
- Log every failure with a clear reason and continue
- If cookies fail to load or classroom discovery fails, exit early with a helpful message
