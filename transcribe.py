"""
Intake pipeline: transcribe downloaded videos and capture scene-change
screenshots, producing agent-readable output (what was said + what was on screen).

Examples:
  python transcribe.py                             # process ./downloads with config defaults
  python transcribe.py --formats json              # only the consolidated intake JSON
  python transcribe.py --no-screenshots            # transcript only, skip frames
  python transcribe.py --model medium.en downloads/Introduction.mp4
"""
import argparse
import bisect
import json
import os
import sys

from transcriber import Transcriber, VIDEO_EXTENSIONS
from screenshots import extract_screenshots

VALID_FORMATS = ("txt", "srt", "json")


def load_config(path="config.json") -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def collect_media(target: str) -> list:
    if os.path.isfile(target):
        return [target]
    if os.path.isdir(target):
        # Recurse so per-classroom subfolders are found; skip screenshot dirs.
        found = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d != "frames"]
            found += [
                os.path.join(root, name)
                for name in files
                if name.lower().endswith(VIDEO_EXTENSIONS)
            ]
        return sorted(found)
    return []


def _srt_timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    h, millis = divmod(millis, 3_600_000)
    m, millis = divmod(millis, 60_000)
    s, millis = divmod(millis, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def _attach_screenshots(segments: list, shots: list):
    """Tag each segment with the most recent screenshot at or before its start."""
    times = [s["t"] for s in shots]
    for seg in segments:
        idx = bisect.bisect_right(times, seg["start"]) - 1
        seg["screenshot"] = shots[idx]["file"] if idx >= 0 else None


def _write_txt(path: str, segments: list):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(seg["text"] for seg in segments) + "\n")


def _write_srt(path: str, segments: list):
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{_srt_timestamp(seg['start'])} --> {_srt_timestamp(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")


def _write_json(path: str, source: str, info: dict, model: str, segments: list, shots: list):
    payload = {
        "source": source,
        "language": info["language"],
        "duration": info["duration"],
        "model": model,
        "segments": segments,
        "screenshots": shots,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def process_file(transcriber, path, formats, skip_if_exists, screenshots,
                 scene_threshold, max_interval, model):
    media_dir = os.path.dirname(path) or "."
    base = os.path.splitext(os.path.basename(path))[0]
    targets = {fmt: os.path.join(media_dir, f"{base}.{fmt}") for fmt in formats}

    if skip_if_exists and all(os.path.exists(p) for p in targets.values()):
        return True, "Already done (skipped)"

    segments, info = transcriber.run_asr(path)

    shots = []
    if screenshots:
        frames_dir = os.path.join(media_dir, "frames", base)
        try:
            raw = extract_screenshots(path, frames_dir, scene_threshold, max_interval)
            shots = [{"t": s["t"], "file": f"frames/{base}/{s['file']}"} for s in raw]
        except RuntimeError as e:
            # Never fail a file just because screenshots couldn't run.
            print(f"    (screenshots skipped: {e})")

    _attach_screenshots(segments, shots)

    if "txt" in targets:
        _write_txt(targets["txt"], segments)
    if "srt" in targets:
        _write_srt(targets["srt"], segments)
    if "json" in targets:
        _write_json(targets["json"], os.path.basename(path), info, model, segments, shots)

    note = f" + {len(shots)} shots" if shots else ""
    return True, f"{', '.join(formats)}{note} ({transcriber.device})"


def run(target, formats, model, device, skip_if_exists=True,
        screenshots=True, scene_threshold=0.25, max_interval=45.0) -> int:
    media = collect_media(target)
    if not media:
        print(f"No media files found at: {target}")
        return 1

    print(f"Loading Whisper model '{model}' (device={device})...")
    transcriber = Transcriber(model_size=model, device=device)
    print(f"Model ready on: {transcriber.device}")
    print(f"Processing {len(media)} file(s) -> {', '.join(formats)}"
          f"{' + screenshots' if screenshots else ''}\n")

    failures = 0
    for i, path in enumerate(media, 1):
        print(f"[{i}/{len(media)}] {os.path.basename(path)} ...", flush=True)
        try:
            success, message = process_file(
                transcriber, path, formats, skip_if_exists, screenshots,
                scene_threshold, max_interval, model
            )
        except Exception as e:
            success, message = False, f"Failed: {e}"
        print(f"    {'OK' if success else 'FAILED'}: {message}")
        if not success:
            failures += 1

    print(f"\nDone. {len(media) - failures} succeeded, {failures} failed.")
    return 0 if failures == 0 else 1


def build_arg_parser(defaults: dict) -> argparse.ArgumentParser:
    t = defaults.get("transcription", {})
    parser = argparse.ArgumentParser(description="Transcribe videos and capture scene screenshots.")
    parser.add_argument("target", nargs="?",
                        default=defaults.get("output_directory", "./downloads"),
                        help="File or folder to process (default: output_directory / ./downloads)")
    parser.add_argument("--formats", nargs="+", choices=VALID_FORMATS,
                        default=t.get("formats", ["txt", "srt", "json"]),
                        help="Output formats (default: txt srt json)")
    parser.add_argument("--model", default=t.get("model", "small.en"),
                        help="Whisper model size (default: small.en)")
    parser.add_argument("--device", default=t.get("device", "auto"),
                        choices=["auto", "cuda", "cpu"], help="Compute device (default: auto)")
    parser.add_argument("--no-screenshots", action="store_true",
                        help="Skip scene-change screenshot capture")
    parser.add_argument("--scene-threshold", type=float,
                        default=t.get("scene_threshold", 0.25),
                        help="Scene-change sensitivity, 0-1 (lower = more frames)")
    parser.add_argument("--max-interval", type=float,
                        default=t.get("max_interval", 45.0),
                        help="Guarantee a frame at least every N seconds (0 = pure scene-change)")
    parser.add_argument("--no-skip", action="store_true",
                        help="Re-process even if output files already exist")
    return parser


def main():
    defaults = load_config()
    args = build_arg_parser(defaults).parse_args()
    sys.exit(run(
        args.target, args.formats, args.model, args.device,
        skip_if_exists=not args.no_skip,
        screenshots=not args.no_screenshots,
        scene_threshold=args.scene_threshold,
        max_interval=args.max_interval,
    ))


if __name__ == "__main__":
    main()
