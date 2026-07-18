import os
import re
import subprocess

PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _timestamp_name(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}-{m:02d}-{s:02d}"


def extract_screenshots(video_path: str, out_dir: str, scene_threshold: float = 0.25,
                        max_interval: float = 45.0, jpg_quality: int = 3) -> list:
    """
    Capture a frame at every visual change (slide/screen-share change) AND at
    least once every `max_interval` seconds, so low-motion / talking-head videos
    still get periodic coverage. Frames are named by timestamp (HH-MM-SS.jpg).

    Set max_interval to 0 to disable the periodic floor (pure scene-change).

    Returns a list of {"t": seconds, "file": <basename>} sorted by time.
    Requires ffmpeg on PATH. Raises RuntimeError if ffmpeg is missing.
    """
    os.makedirs(out_dir, exist_ok=True)
    tmp_pattern = os.path.join(out_dir, "_tmp_%05d.jpg")

    # eq(n,0) forces the opening frame; gt(scene,threshold) catches every change;
    # gte(t-prev_selected_t,max_interval) guarantees no gap longer than the floor.
    # showinfo prints each emitted frame's pts_time to stderr, which we parse for
    # timestamps (a file path in the filter breaks on Windows backslashes/colons).
    select = f"eq(n\\,0)+gt(scene\\,{scene_threshold})"
    if max_interval and max_interval > 0:
        select += f"+gte(t-prev_selected_t\\,{max_interval})"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
        "-i", video_path,
        "-vf", f"select='{select}',showinfo",
        "-vsync", "vfr", "-q:v", str(jpg_quality),
        tmp_pattern,
    ]

    try:
        result = subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found on PATH (needed for screenshots).")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {(e.stderr or '').strip()[:300]}")

    # showinfo logs one line per emitted frame; parse pts_time in emission order.
    times = [float(m) for m in PTS_RE.findall(result.stderr or "")]

    tmp_files = sorted(
        f for f in os.listdir(out_dir) if f.startswith("_tmp_") and f.endswith(".jpg")
    )

    results = []
    used = set()
    for i, tmp in enumerate(tmp_files):
        t = times[i] if i < len(times) else float(i)
        name = _timestamp_name(t)
        final = f"{name}.jpg"
        # Disambiguate multiple changes within the same second.
        suffix = 1
        while final in used:
            final = f"{name}_{suffix}.jpg"
            suffix += 1
        used.add(final)
        os.replace(os.path.join(out_dir, tmp), os.path.join(out_dir, final))
        results.append({"t": round(t, 2), "file": final})

    return results
