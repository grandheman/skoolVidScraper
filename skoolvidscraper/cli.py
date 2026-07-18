import argparse
import sys


def _cmd_serve(args):
    from .server import run_server
    run_server()


def _cmd_tray(args):
    from .tray import run as run_tray
    run_tray()


def _cmd_scrape(args):
    from .main import run
    run(transcribe=args.transcribe, formats=args.formats, model=args.model,
        device=args.device, no_screenshots=args.no_screenshots,
        section=args.section, lessons_spec=args.lessons)


def _cmd_transcribe(args):
    from .transcribe import run
    sys.exit(run(
        args.target, args.formats, args.model, args.device,
        skip_if_exists=not args.no_skip,
        screenshots=not args.no_screenshots,
        scene_threshold=args.scene_threshold,
        max_interval=args.max_interval,
    ))


def build_parser():
    from . import __version__
    p = argparse.ArgumentParser(
        prog="skoolvidscraper",
        description="Turn Skool classrooms into agent-readable intake: "
                    "download, transcribe, and screenshot every lesson.",
    )
    p.add_argument("--version", action="version", version=f"skoolvidscraper {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="Run the local helper server for the Chrome extension.")
    sp.set_defaults(func=_cmd_serve)

    tp = sub.add_parser("tray", help="Run the helper server as a system-tray app.")
    tp.set_defaults(func=_cmd_tray)

    cp = sub.add_parser("scrape", help="Download the classroom in config.json (optionally build intake).")
    cp.add_argument("--transcribe", action="store_true",
                    help="Transcribe + screenshot after downloading.")
    cp.add_argument("--formats", nargs="+", choices=("txt", "srt", "json"),
                    help="Transcript formats (default: from config).")
    cp.add_argument("--model", help="Whisper model size (default: from config).")
    cp.add_argument("--device", choices=("auto", "cuda", "cpu"),
                    help="Transcription device (default: from config).")
    cp.add_argument("--no-screenshots", action="store_true",
                    help="Skip scene-change screenshot capture.")
    cp.add_argument("--section", help="Only lessons whose section title contains this text.")
    cp.add_argument("--lessons", help="Only these 1-based lessons, e.g. '1-5,8'.")
    cp.set_defaults(func=_cmd_scrape)

    xp = sub.add_parser("transcribe", help="Transcribe + screenshot an existing folder or file.")
    xp.add_argument("target", nargs="?", default="./downloads",
                    help="File or folder to process (default: ./downloads).")
    xp.add_argument("--formats", nargs="+", choices=("txt", "srt", "json"),
                    default=["txt", "srt", "json"])
    xp.add_argument("--model", default="small.en")
    xp.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    xp.add_argument("--no-screenshots", action="store_true")
    xp.add_argument("--scene-threshold", type=float, default=0.25,
                    help="Scene-change sensitivity, 0-1 (lower = more frames).")
    xp.add_argument("--max-interval", type=float, default=45.0,
                    help="Guarantee a frame every N seconds (0 = pure scene-change).")
    xp.add_argument("--no-skip", action="store_true",
                    help="Re-process even if output files already exist.")
    xp.set_defaults(func=_cmd_transcribe)

    return p


def main():
    from .ffmpeg_setup import ensure_ffmpeg
    ensure_ffmpeg()
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
