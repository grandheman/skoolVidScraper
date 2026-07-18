"""
Render Skool lesson content into agent-readable text + links, and resolve
"post-backed" lessons.

Two content formats show up in Skool classrooms:
- Lesson `desc` is a `[v2]` rich-text doc (ProseMirror JSON: paragraph/text/link
  nodes). We render it to plain text and pull out embedded links.
- Some lessons carry no content of their own; instead they link a pinned community
  discussion POST (associated via post.metadata.pinnedModule == lesson id). The real
  content (text + more links + an attachment) lives in that post. We fetch the lesson
  page, find the post, and lift its content onto the lesson.
"""
import json
import re

from .page_fetcher import fetch_lesson_page

_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def render_richtext(desc):
    """Render a Skool `[v2]` rich-text desc to (plain_text, links). Non-[v2] text is
    returned as-is; links is a list of {type:'link', title, link}."""
    if not desc or not isinstance(desc, str):
        return "", []
    if not desc.startswith("[v2]"):
        return desc.strip(), []
    try:
        nodes = json.loads(desc[4:])
    except (ValueError, TypeError):
        return "", []

    parts, links = [], []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        ntype = node.get("type")
        if ntype == "text":
            text = node.get("text", "")
            for mark in node.get("marks", []) or []:
                if mark.get("type") == "link":
                    href = (mark.get("attrs") or {}).get("href")
                    if href:
                        links.append({"type": "link", "title": text or href, "link": href})
            parts.append(text)
            return
        for child in node.get("content", []) or []:
            walk(child)
        if ntype in ("paragraph", "heading", "listItem", "blockquote"):
            parts.append("\n")

    walk(nodes)
    text = re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()
    return text, links


def render_post_content(content):
    """Render a Skool post `content` (markdown-ish: [text](url), [ul]/[li]) to
    (plain_text, links)."""
    if not content or not isinstance(content, str):
        return "", []
    links = [{"type": "link", "title": (t or u), "link": u} for t, u in _MD_LINK.findall(content)]
    text = _MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", content)
    text = re.sub(r"\[/?ul\]", "", text)
    text = re.sub(r"\[li\]", "\n- ", text)
    text = re.sub(r"\[/?[a-z]+\]", "", text)   # strip any remaining [xx] markers
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, links


def resolve_lesson_post(lesson_url, lesson_id, cookiejar):
    """
    Fetch a lesson page; if it is backed by a pinned discussion post
    (post.metadata.pinnedModule == lesson_id), return
    {title, text, links, attachment_ids}. Returns None otherwise.
    """
    try:
        html = fetch_lesson_page(lesson_url, cookiejar, wait_seconds=0)
    except Exception:
        return None
    m = _NEXT_DATA.search(html)
    if not m:
        return None
    try:
        pp = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    except (ValueError, TypeError):
        return None
    for entry in pp.get("pinnedPosts") or []:
        post = entry.get("post") or {}
        pm = post.get("metadata") or {}
        if pm.get("pinnedModule") == lesson_id:
            text, links = render_post_content(pm.get("content") or "")
            atts = pm.get("attachments")
            att_ids = [atts] if isinstance(atts, str) and atts else (atts if isinstance(atts, list) else [])
            return {"title": pm.get("title"), "text": text, "links": links,
                    "attachment_ids": [a for a in att_ids if a]}
    return None


def enrich_lessons_content(lessons, cookiejar=None):
    """
    Make lesson content agent-readable, in place:
    - render any `[v2]` desc to plain text and lift its links into resources;
    - for a lesson with no video/resources/text (a post-backed lesson), fetch its
      page and lift the linked post's title+text, links, and attachment onto it.
    The per-lesson fetch only happens for otherwise-empty lessons, so normal
    video/text lessons cost nothing. `cookiejar=None` skips the post lookup.
    """
    for lesson in lessons:
        raw = lesson.get("desc")
        if isinstance(raw, str) and raw.startswith("[v2]"):
            text, links = render_richtext(raw)
            lesson["desc"] = text or None
            if links:
                lesson.setdefault("resources", [])
                lesson["resources"].extend(links)

        empty = (not lesson.get("has_video") and not lesson.get("resources")
                 and not (lesson.get("desc") or "").strip())
        if empty and cookiejar is not None:
            post = resolve_lesson_post(lesson["lesson_url"], lesson["lesson_id"], cookiejar)
            if post:
                body = "\n\n".join(p for p in (post.get("title"), post.get("text")) if p).strip()
                lesson["desc"] = body or None
                lesson.setdefault("resources", [])
                lesson["resources"].extend(post.get("links", []))
                for fid in post.get("attachment_ids", []):
                    lesson["resources"].append({
                        "type": "file", "title": post.get("title"),
                        "file_id": fid, "file_name": None, "content_type": None,
                    })
