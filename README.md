# skoolVidScraper

Turn any [Skool](https://www.skool.com) classroom you have access to into
**agent-readable intake**: every lesson video is downloaded (low-res, for
processing), transcribed locally, and screenshotted at each on-screen change.
The result is one JSON per lesson where each transcript segment carries the
screenshot that was on screen at that moment, so a downstream AI agent gets both
**what was said** and **what was on screen**.

Think of it as a NotebookLM-style ingestion step for Skool courses.

Everything runs locally: local Whisper transcription (no API key), local ffmpeg
screenshots, and authentication via your own live browser session (no passwords,
no browser automation).

## Features

- **One classroom fetch discovers every lesson** (parses Skool's `__NEXT_DATA__`).
- **Handles both video hosting styles**: direct links (Wistia/YouTube/Loom) and
  Mux signed HLS.
- **Local transcription** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (auto-detects an NVIDIA GPU, falls back to CPU).
- **Scene-change + interval screenshots** via ffmpeg: one frame per slide change,
  plus a guaranteed frame every N seconds so nothing is missed.
- **Consolidated JSON** aligning transcript segments to the on-screen frame.
- **One-click Chrome extension**: open a classroom tab, click the button, done.
  Reads your live Skool cookies, so there is no manual cookie export.
- **Per-classroom output folders** so multiple courses never collide.

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on your PATH (`winget install Gyan.FFmpeg` on Windows)
- (Optional) Node.js, only if you need HD YouTube-hosted lessons
- (Optional) An NVIDIA GPU for fast transcription; CPU works too

```bash
pip install -r requirements.txt
```

## Usage

### Option A: Chrome extension (recommended)

1. Start the local helper (leave it running):
   ```bash
   python server.py
   ```
2. Load the extension: open `chrome://extensions`, enable **Developer mode**,
   click **Load unpacked**, and select the `extension/` folder.
3. Open a Skool classroom tab, click the extension icon, choose your settings
   (run mode, quality, Whisper model, formats, screenshots), and hit
   **Scrape this classroom**. Progress shows in the popup.

The extension reads the active tab URL and your live Skool cookies (including the
HttpOnly auth cookies), so you never export a `cookies.txt`.

> Only one server can hold port 8765 at a time. If you restart it, stop the old
> one first, or the extension will keep talking to the old process.

### Option B: Command line

1. Copy `config.example.json` to `config.json` and set `classroom_url`.
2. Provide cookies (see below).
3. Run:
   ```bash
   python main.py                 # download only
   python main.py --transcribe    # download + transcribe + screenshots
   ```

Transcribe an already-downloaded folder at any time:
```bash
python transcribe.py                       # all classrooms under ./downloads
python transcribe.py --model medium.en
python transcribe.py --formats json --no-screenshots
```

## Cookies (command-line mode)

The Chrome extension supplies cookies automatically. For the CLI, provide them one of:

1. `cookies.txt` (Netscape format) in the project root
2. `cookies.json` (a Chrome cookie-export extension's JSON)
3. Direct Chrome read via browser-cookie3 (may fail on Chrome 127+)

## Output

For each lesson, next to the downloaded video:

```
downloads/<community>-<classroomId>/
  <Lesson>.mp4
  <Lesson>.txt          # plain transcript
  <Lesson>.srt          # subtitles
  <Lesson>.json         # agent-facing: segments + screenshot per segment
  frames/<Lesson>/HH-MM-SS.jpg
```

The `.json` is the artifact meant for an AI agent:

```json
{
  "source": "Introduction.mp4",
  "language": "en",
  "duration": 547.18,
  "segments": [
    { "start": 0.0, "end": 6.3, "text": "...", "screenshot": "frames/Introduction/00-00-00.jpg" }
  ],
  "screenshots": [ { "t": 0.0, "file": "frames/Introduction/00-00-00.jpg" } ]
}
```

## Configuration

All defaults live in `config.json` (see `config.example.json`). The extension's
popup settings override these per run. Key fields:

| Field | Purpose |
|-------|---------|
| `classroom_url` | The Skool classroom to scrape (CLI mode) |
| `output_directory` | Where downloads and intake land |
| `max_video_height` | Resolution cap (720 keeps slide text readable) |
| `transcription.model` | Whisper model (`base.en`, `small.en`, `medium.en`, ...) |
| `transcription.formats` | Any of `txt`, `srt`, `json` |
| `transcription.scene_threshold` | Screenshot sensitivity (lower = more frames) |
| `transcription.max_interval` | Guarantee a frame every N seconds (0 = pure scene-change) |

## Notes

- Videos are downloaded at low resolution on purpose (they are for processing,
  not viewing). 720p keeps on-screen text legible for the screenshots.
- Only scrape classrooms you are legitimately a member of and have the right to
  access. This tool authenticates as you.
