# Test Plan — v2 features (community scope, resources, queue)

Covers the four-milestone build. Test data: the live `leadbase-pro` community
(8 classrooms) via the repo `cookies.txt`. Statuses: ☐ pending · ☑ pass · ☒ fail.

## M1 — Community folder nesting

Output nests as `<output>/<Community>/<Classroom>/` (was `<output>/<Classroom>/`).

| # | Case | Expected | Status |
|---|------|----------|--------|
| M1.1 | `community_dir_name(url, html)` on a classroom page | "Leadbase Pro" (from `currentGroup.metadata.displayName`) | ☑ |
| M1.2 | `community_dir_name(url)` with no html | URL slug "leadbase-pro" | ☑ |
| M1.3 | Full nested path | `downloads/Leadbase Pro/How to Generate Leads` | ☑ |
| M1.4 | Sanitization of names with `/ : * ?` etc. | replaced with spaces, no path escape | ☐ |
| M1.5 | CLI `scrape` end-to-end lands files under community folder | video + json under nested path | ☐ |
| M1.6 | Server `/scrape` lands files under community folder | same nesting via extension path | ☐ |

## M2 — Non-video resources + doc-only lessons

Lesson (not video) is the unit. Capture `resources` (files + links) and `desc`;
stop dropping `unitType=module` lessons that have no video.

| # | Case | Expected | Status |
|---|------|----------|--------|
| M2.1 | Discover includes doc-only "Resources" lesson | present in lesson list | ☑ |
| M2.2 | Classroom root (`unitType=course`) NOT emitted as a lesson | absent | ☑ |
| M2.3 | `resources` JSON-string parsed to list | file + link items with title | ☑ |
| M2.4 | Video count unchanged vs. pre-M2 (no regression) | 20 video lessons, only modules carry video | ☑ |
| M2.5 | Per-lesson JSON carries `resources` + `desc` | fields present, links recorded not fetched | ☐ QA |
| M2.6 | Empty module (no video/resources/desc) skipped | no empty lesson entries | ☐ QA |

## M3 — Skool file attachment downloads

Extension resolves `file_id` → signed URL (passes WAF); server downloads it.

| # | Case | Expected | Status |
|---|------|----------|--------|
| M3.1 | Extension POST to `api2.skool.com/files/<id>/download-url?expire=28800` | 200 + signed `files.skool.com` URL | ☐ |
| M3.2 | Server GET of signed URL (no auth) | file bytes saved to `resources/` | ☐ |
| M3.3 | PDF saved with correct `file_name` | e.g. `Leadbase_Pro_Checklist_2025.pdf` | ☐ |
| M3.4 | file_id with no resolvable URL | logged, run continues | ☐ |
| M3.5 | External links (Google Docs/Drive/GPT) recorded, not downloaded | listed in JSON only | ☐ |

## M4 — Community recursion + job queue

Community index URL scrapes all classrooms; server runs a sequential job queue.

| # | Case | Expected | Status |
|---|------|----------|--------|
| M4.1 | Community URL (no `/classroom/<id>`) enumerates `allCourses` | 8 classroom jobs queued | ☐ |
| M4.2 | Individual classroom URL scrapes just that one | 1 job | ☐ |
| M4.3 | Queue runs jobs sequentially (one at a time) | no concurrent GPU/network use | ☐ |
| M4.4 | Second `/scrape` while running enqueues (not 409) | job appended | ☐ |
| M4.5 | `/status` reports active job + pending queue | popup shows queue | ☐ |
| M4.6 | One classroom failing does not abort the batch | others still run | ☐ |
| M4.7 | Per-job cookie snapshot (no shared temp-file clobber) | each job uses its own cookies | ☐ |

## Regression

| # | Case | Expected | Status |
|---|------|----------|--------|
| R.1 | Single-classroom download-only run still works | video only, nested path | ☐ |
| R.2 | `--transcribe` intake still produces txt/srt/json + frames | unchanged | ☐ |
| R.3 | Mux HLS lesson still resolves + merges | merged mp4 | ☐ |
| R.4 | Existing `skip_if_exists` still skips done work | skipped | ☐ |
