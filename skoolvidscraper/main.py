import json
import os
import sys

from .cookie_loader import load_skool_cookies
from .page_fetcher import fetch_lesson_page
from .discoverer import discover_lessons, classroom_dir_name
from .downloader import download_video
from .extractor import resolve_video_url
from .logger import DownloadLogger


def load_config(path="config.json"):
    if not os.path.exists(path):
        print(f"ERROR: config.json not found at {path}")
        sys.exit(1)
    with open(path, "r") as f:
        return json.load(f)


def run(transcribe=False, formats=None, model=None, device=None, no_screenshots=False):
    """Download every lesson in the configured classroom, then optionally build intake."""
    config = load_config()
    t = config.get("transcription", {})
    logger = DownloadLogger(config["log_file"])
    logger.log("=== skoolVidScraper starting ===")

    # Step 1: Load cookies
    try:
        cookiejar, _ = load_skool_cookies(
            config.get("chrome_profile_path", ""),
            cookies_file=config.get("cookies_file")
        )
        logger.log("Cookies loaded successfully.")
    except RuntimeError as e:
        logger.log(f"FATAL: {e}")
        sys.exit(1)

    # Step 2: Fetch the classroom root page and discover all lessons
    classroom_url = config["classroom_url"]
    logger.log(f"Fetching classroom: {classroom_url}")
    try:
        classroom_html = fetch_lesson_page(classroom_url, cookiejar, wait_seconds=0)
        lessons = discover_lessons(classroom_url, classroom_html)
    except Exception as e:
        logger.log(f"FATAL: Could not discover lessons: {e}")
        sys.exit(1)

    logger.log(f"Discovered {len(lessons)} lesson(s) with videos.")

    # Each classroom gets its own subfolder, named by the classroom title.
    out_dir = os.path.join(config["output_directory"],
                           classroom_dir_name(classroom_url, classroom_html))

    # Step 3: Download each lesson's video
    for i, lesson in enumerate(lessons, 1):
        lesson_url = lesson["lesson_url"]
        title = lesson["lesson_title"]
        section = lesson["section_title"]
        video_url = lesson["video_url"]

        # Mux lessons have no direct URL in the tree - resolve from the lesson page.
        if not video_url:
            info = resolve_video_url(lesson_url, cookiejar)
            video_url = info["url"]
            if not video_url:
                logger.record(lesson_url, title, "FAILED", info["error"])
                continue

        logger.log(f"--- [{i}/{len(lessons)}] [{section}] {title}")
        logger.log(f"    Video: {video_url}")

        success, message = download_video(
            video_url=video_url,
            output_dir=out_dir,
            filename_template=config["filename_template"],
            skip_if_exists=config.get("skip_already_downloaded", True),
            max_height=config.get("max_video_height", 720),
            title=title
        )

        if success:
            logger.record(lesson_url, title, "SUCCESS", message)
        else:
            logger.record(lesson_url, title, "FAILED", message)

    logger.summary()

    # Step 4: Optionally transcribe + screenshot everything that was downloaded.
    if transcribe:
        logger.log("=== Building intake (transcripts + screenshots) ===")
        from .transcribe import run as transcribe_run
        transcribe_run(
            target=out_dir,
            formats=formats or t.get("formats", ["txt", "srt", "json"]),
            model=model or t.get("model", "small.en"),
            device=device or t.get("device", "auto"),
            skip_if_exists=config.get("skip_already_downloaded", True),
            screenshots=not no_screenshots,
            scene_threshold=t.get("scene_threshold", 0.25),
            max_interval=t.get("max_interval", 45),
        )


def main():
    import argparse
    p = argparse.ArgumentParser(description="Download a Skool classroom (uses config.json).")
    p.add_argument("--transcribe", action="store_true",
                   help="Transcribe + screenshot downloaded videos after the run.")
    p.add_argument("--formats", nargs="+", choices=("txt", "srt", "json"),
                   help="Transcript output formats (default: from config).")
    p.add_argument("--model", help="Whisper model size (default: from config).")
    p.add_argument("--device", choices=("auto", "cuda", "cpu"),
                   help="Transcription device (default: from config).")
    p.add_argument("--no-screenshots", action="store_true",
                   help="Skip scene-change screenshot capture.")
    a = p.parse_args()
    run(transcribe=a.transcribe, formats=a.formats, model=a.model,
        device=a.device, no_screenshots=a.no_screenshots)


if __name__ == "__main__":
    main()
