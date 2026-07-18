import os
from datetime import datetime


class DownloadLogger:
    """
    Simple run logger: writes timestamped lines to a log file and stdout,
    tracks per-lesson results, and prints a final summary.
    """

    def __init__(self, log_file: str):
        self.log_file = log_file
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        self.records = []

    def log(self, message: str):
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
        print(line, flush=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def record(self, lesson_url: str, title: str, status: str, message: str):
        self.records.append({
            "lesson_url": lesson_url,
            "title": title,
            "status": status,
            "message": message,
        })
        self.log(f"    [{status}] {title}: {message}")

    def summary(self):
        total = len(self.records)
        ok = sum(1 for r in self.records if r["status"] == "SUCCESS")
        failed = total - ok
        self.log(f"=== Summary: {ok}/{total} succeeded, {failed} failed ===")
        for r in self.records:
            if r["status"] != "SUCCESS":
                self.log(f"    FAILED: {r['title']}: {r['message']}")
