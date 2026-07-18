import json
import re


def classroom_dir_name(classroom_url: str) -> str:
    """
    Derive a stable, filesystem-safe subfolder name for a classroom from its URL,
    e.g. https://www.skool.com/leadbase-pro/classroom/29f082b3?md=... -> leadbase-pro-29f082b3.
    """
    m = re.search(r"skool\.com/([^/]+)/classroom/([^/?#]+)", classroom_url)
    raw = f"{m.group(1)}-{m.group(2)}" if m else "classroom"
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)


def discover_lessons(classroom_url: str, html: str) -> list:
    """
    Parse the classroom root page and return a flat list of all lessons that have videos.

    The Skool __NEXT_DATA__ structure is a recursive tree:
      pageProps.course.children -> list of nodes
      Each node: { course: {id, metadata: {title, videoLink, ...}, unitType}, children: [...] }
      unitType "set" = a section grouping; unitType "module" = an actual lesson.

    Returns a list of dicts:
    [
      {
        "lesson_url":   "https://www.skool.com/.../classroom/ID?md=LESSON_ID",
        "lesson_id":    "abc123...",
        "lesson_title": "Lesson 1 - Welcome",
        "section_title": "Section Name",
        "video_url":    "https://youtu.be/...",   # None for Mux -> resolved per-lesson
      },
      ...
    ]
    """
    next_data_match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL
    )
    if not next_data_match:
        raise RuntimeError(
            "__NEXT_DATA__ not found on classroom page.\n"
            "The page may not have loaded correctly or Skool's structure has changed."
        )

    try:
        next_data = json.loads(next_data_match.group(1))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse __NEXT_DATA__ JSON: {e}")

    page_props = next_data.get("props", {}).get("pageProps", {})
    course_root = page_props.get("course")

    if not course_root or not isinstance(course_root, dict):
        available_keys = list(page_props.keys())
        raise RuntimeError(
            "Could not find 'course' key in pageProps.\n"
            f"Available pageProps keys: {available_keys}"
        )

    base_url = classroom_url.split("?")[0].rstrip("/")
    lessons = []

    _walk_tree(
        node=course_root,
        base_url=base_url,
        section_title=None,
        lessons=lessons,
    )

    return lessons


def _walk_tree(node: dict, base_url: str, section_title: str, lessons: list):
    """
    Recursively walk the course tree.
    Nodes with unitType "set" are sections - their title becomes the section label for children.
    Nodes with unitType "module" are lessons.
    """
    course_info = node.get("course", {})
    meta = course_info.get("metadata", {}) if isinstance(course_info.get("metadata"), dict) else {}
    title = meta.get("title") or course_info.get("name", "Untitled")
    unit_type = course_info.get("unitType", "")
    children = node.get("children", [])

    if unit_type == "set":
        # This is a section grouping - recurse into its children using this title as section
        for child in children:
            _walk_tree(child, base_url, section_title=title, lessons=lessons)

    elif unit_type in ("module", "course"):
        # Two hosting styles: a direct videoLink (Wistia/YouTube/Loom), or a Mux
        # videoId whose playable URL must be resolved from the lesson page later.
        video_url = meta.get("videoLink")
        has_video = bool(video_url) or bool(meta.get("videoId"))
        lesson_id = course_info.get("id")

        if lesson_id and has_video:
            lessons.append({
                "lesson_url": f"{base_url}?md={lesson_id}",
                "lesson_id": lesson_id,
                "lesson_title": title,
                "section_title": section_title or "General",
                "video_url": video_url,  # None for Mux -> resolved per-lesson at download time
            })

        # Recurse in case there are nested sets/modules inside a module
        for child in children:
            _walk_tree(child, base_url, section_title=section_title, lessons=lessons)
