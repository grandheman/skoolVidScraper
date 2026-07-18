import json
import re


def _sanitize_dir(name: str) -> str:
    """Make a classroom title safe as a folder name."""
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', " ", name).strip().rstrip(". ")
    name = re.sub(r"\s+", " ", name)
    return name or "classroom"


def _classroom_title(html: str):
    """The human classroom title from __NEXT_DATA__ (pageProps.course.course.metadata.title)."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        nd = json.loads(m.group(1))
        return nd["props"]["pageProps"]["course"]["course"]["metadata"].get("title")
    except (ValueError, KeyError, TypeError):
        return None


def classroom_dir_name(classroom_url: str, html: str = None) -> str:
    """
    Filesystem-safe subfolder name for a classroom. Prefers the real classroom
    title (e.g. "The Agentic Agency Playbook") when the page HTML is available;
    falls back to <community>-<classroomId> from the URL otherwise.
    """
    if html:
        title = _classroom_title(html)
        if title:
            return _sanitize_dir(title)
    m = re.search(r"skool\.com/([^/]+)/classroom/([^/?#]+)", classroom_url)
    raw = f"{m.group(1)}-{m.group(2)}" if m else "classroom"
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)


def _community_display_name(html: str):
    """The community name from __NEXT_DATA__ (pageProps.currentGroup.metadata.displayName)."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        nd = json.loads(m.group(1))
        return nd["props"]["pageProps"]["currentGroup"]["metadata"].get("displayName")
    except (ValueError, KeyError, TypeError):
        return None


def community_dir_name(url: str, html: str = None) -> str:
    """
    Filesystem-safe top-level folder for the whole community. Prefers the real
    community display name (e.g. "Leadbase Pro") from the page; falls back to the
    URL slug (e.g. "leadbase-pro"). Output nests as <community>/<classroom>/.
    """
    if html:
        name = _community_display_name(html)
        if name:
            return _sanitize_dir(name)
    m = re.search(r"skool\.com/([^/?#]+)", url)
    slug = m.group(1) if m else "community"
    return re.sub(r"[^A-Za-z0-9._-]", "_", slug)


def safe_base(title: str) -> str:
    """
    Filename base for a lesson, matching how downloader.py names its video file
    (minus the yt-dlp %%-escaping). Used to couple a lesson's resources to the
    video/transcript that shares this base.
    """
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', " ", title).strip().rstrip(". ")
    name = re.sub(r"\s+", " ", name)
    return name or "lesson"


def _parse_resources(raw) -> list:
    """
    Normalize a lesson's `resources` (a JSON string in __NEXT_DATA__) into a list.
    Each item is either a Skool-hosted file or an external link:
      {"type": "file", "title", "file_id", "file_name", "content_type"}
      {"type": "link", "title", "link"}
    """
    if not raw:
        return []
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        if it.get("file_id"):
            out.append({
                "type": "file",
                "title": it.get("title"),
                "file_id": it["file_id"],
                "file_name": it.get("file_name"),
                "content_type": it.get("file_content_type"),
            })
        elif it.get("link"):
            out.append({"type": "link", "title": it.get("title"), "link": it["link"]})
    return out


def parse_lesson_spec(spec: str) -> set:
    """Parse a 1-based selection like '1-5,8,10-12' into a set of ints."""
    ids = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ids.update(range(int(a), int(b) + 1))
        else:
            ids.add(int(part))
    return ids


def select_lessons(lessons: list, section: str = None, spec: str = None) -> list:
    """
    Filter a discovered lesson list. `section` keeps lessons whose section title
    contains the given text (case-insensitive); `spec` then keeps 1-based
    positions in the (already section-filtered) order, e.g. '1-5,8'.
    """
    out = lessons
    if section:
        s = section.lower()
        out = [L for L in out if s in (L.get("section_title") or "").lower()]
    if spec:
        idxs = parse_lesson_spec(spec)
        out = [L for i, L in enumerate(out, 1) if i in idxs]
    return out


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
    Nodes with unitType "module" are lessons. The root node is unitType "course"
    (the classroom itself) and is never emitted as a lesson.
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
        return

    if unit_type == "module":
        # The lesson (not the video) is the unit. A module can carry a video, a set
        # of resources (files/links), a text description, or any combination. Two
        # video hosting styles: a direct videoLink (Wistia/YouTube/Loom), or a Mux
        # videoId whose playable URL is resolved from the lesson page later.
        video_url = meta.get("videoLink")
        has_video = bool(video_url) or bool(meta.get("videoId"))
        resources = _parse_resources(meta.get("resources"))
        desc = meta.get("desc")
        lesson_id = course_info.get("id")

        # Emit any module that has some content (video, resources, or a description).
        if lesson_id and (has_video or resources or desc):
            lessons.append({
                "lesson_url": f"{base_url}?md={lesson_id}",
                "lesson_id": lesson_id,
                "lesson_title": title,
                "section_title": section_title or "General",
                "video_url": video_url,  # None for Mux -> resolved per-lesson at download time
                "has_video": has_video,
                "resources": resources,
                "desc": desc,
            })

    # Recurse in case there are nested sets/modules (and to descend the root course).
    for child in children:
        _walk_tree(child, base_url, section_title=section_title, lessons=lessons)
