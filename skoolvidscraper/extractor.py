import json
import re

from .page_fetcher import fetch_lesson_page


def resolve_video_url(lesson_url: str, cookiejar) -> dict:
    """Fetch a lesson page and extract its video URL (videoLink or Mux)."""
    html = fetch_lesson_page(lesson_url, cookiejar, wait_seconds=0)
    return extract_video_url(html, lesson_url)


def extract_video_url(html: str, lesson_url: str) -> dict:
    """
    Parse __NEXT_DATA__ from Skool lesson page HTML and return video metadata.

    Returns a dict:
      {
        "url": str or None,
        "title": str or None,
        "duration_ms": int or None,
        "error": str or None
      }
    """
    md_match = re.search(r'[?&]md=([a-f0-9]+)', lesson_url)
    if not md_match:
        return {"url": None, "title": None, "duration_ms": None,
                "error": "No 'md' parameter found in URL"}

    course_id = md_match.group(1)

    next_data_match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL
    )
    if not next_data_match:
        return {"url": None, "title": None, "duration_ms": None,
                "error": "__NEXT_DATA__ script tag not found in page HTML"}

    try:
        next_data = json.loads(next_data_match.group(1))
    except json.JSONDecodeError as e:
        return {"url": None, "title": None, "duration_ms": None,
                "error": f"Failed to parse __NEXT_DATA__ JSON: {e}"}

    course = _find_course_by_id(next_data, course_id, depth=0)
    metadata = course.get("metadata", {}) if course else {}
    video_link = metadata.get("videoLink")

    if video_link:
        return {
            "url": video_link,
            "title": metadata.get("title", "Untitled Lesson"),
            "duration_ms": metadata.get("videoLenMs"),
            "error": None,
        }

    # Mux-hosted lesson: the selected module's signed playback data lives in
    # pageProps.video. Build a Mux HLS URL (yt-dlp downloads it with a referer).
    video = next_data.get("props", {}).get("pageProps", {}).get("video") or {}
    playback_id = video.get("playbackId")
    token = video.get("playbackToken")
    if playback_id and token:
        return {
            "url": f"https://stream.mux.com/{playback_id}.m3u8?token={token}",
            "title": metadata.get("title", "Untitled Lesson"),
            "duration_ms": metadata.get("videoLenMs"),
            "error": None,
        }

    return {"url": None, "title": None, "duration_ms": None,
            "error": "Lesson found but has no videoLink or Mux playback data"}


def _find_course_by_id(obj, target_id: str, depth: int):
    """Recursively search nested dict/list for a course object with matching ID and videoLink."""
    if depth > 25 or obj is None:
        return None
    if isinstance(obj, dict):
        if obj.get("id") == target_id and obj.get("metadata", {}).get("videoLink"):
            return obj
        for value in obj.values():
            result = _find_course_by_id(value, target_id, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_course_by_id(item, target_id, depth + 1)
            if result:
                return result
    return None
