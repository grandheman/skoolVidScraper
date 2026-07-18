import subprocess
import os
import re


def _sanitize_filename(name: str) -> str:
    """Make a lesson title safe as a filename (and safe in a yt-dlp -o template)."""
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', " ", name).strip().rstrip(". ")
    name = re.sub(r"\s+", " ", name)
    return (name or "lesson").replace("%", "%%")  # %% so yt-dlp keeps a literal %


def download_video(video_url: str, output_dir: str, filename_template: str,
                   skip_if_exists: bool = True, max_height: int = 720,
                   referer: str = "https://www.skool.com/", title: str = None) -> tuple:
    """
    Download a video using yt-dlp.
    Returns (success: bool, message: str)

    Videos are for transcription + screenshots, not viewing, so we cap the
    resolution (max_height). 720p keeps on-screen slide text readable while
    staying small. The referer is required for Mux-hosted Skool videos (their
    signed tokens enforce an allowed referer domain); it is harmless for other
    hosts. HLS (Mux) delivers separate video/audio streams, so we let yt-dlp
    merge with ffmpeg and fall back to a progressive file where one exists.
    """
    os.makedirs(output_dir, exist_ok=True)
    # Name by the Skool lesson title when we have it (Mux streams carry no title,
    # and the lesson title is more consistent than host metadata anyway).
    name_template = f"{_sanitize_filename(title)}.%(ext)s" if title else filename_template
    output_path = os.path.join(output_dir, name_template)

    cmd = [
        "yt-dlp",
        "--output", output_path,
        "--no-warnings",
        "--newline",        # print progress on new lines so it shows cleanly in the terminal
        "--js-runtimes", "nodejs",  # use Node.js to resolve HD format URLs (required for YouTube)
        "--referer", referer,
        # HLS (Loom/Mux/Wistia) is delivered as many small fragments; downloading
        # them one at a time is very slow, so fetch several in parallel.
        "--concurrent-fragments", "8",
        "--format",
        f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
    ]

    if skip_if_exists:
        cmd.append("--no-overwrites")

    cmd.append(video_url)

    try:
        result = subprocess.run(
            cmd,
            stderr=subprocess.PIPE,  # capture stderr for error messages
            text=True,
            timeout=3600
        )
        if result.returncode == 0:
            return True, "Downloaded successfully"
        else:
            error_msg = result.stderr.strip() or "Unknown yt-dlp error"
            return False, error_msg

    except subprocess.TimeoutExpired:
        return False, "Timed out after 1 hour"
    except FileNotFoundError:
        return False, (
            "yt-dlp not found. Install it:\n"
            "  Windows: winget install yt-dlp\n"
            "  Or download from: https://github.com/yt-dlp/yt-dlp/releases"
        )
    except Exception as e:
        return False, str(e)
