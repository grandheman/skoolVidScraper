import sys


def ensure_utf8_output():
    """
    Force stdout/stderr to UTF-8 so printing a lesson title can never crash.

    Skool section and lesson titles are full of emoji. On Windows a real console
    handles them, but the moment output is redirected to a file or a pipe
    (`skoolvidscraper scrape > log.txt`), Python falls back to the locale codec
    (cp1252) and every print of a non-Latin-1 title raises UnicodeEncodeError.

    This is the encode-side mirror of the ffmpeg stderr decode fix in
    screenshots.py. errors="replace" keeps a run alive on any console.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # Already swapped for a file (tray mode), or not reconfigurable.
            pass
