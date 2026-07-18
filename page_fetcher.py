import requests
import time

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch_lesson_page(url: str, cookiejar, wait_seconds: float = 2) -> str:
    """
    Fetch a Skool lesson page and return the raw HTML.
    Raises requests.HTTPError on non-200 responses.
    """
    time.sleep(wait_seconds)

    response = requests.get(url, cookies=cookiejar, headers=HEADERS, timeout=30)

    if response.status_code == 403:
        raise requests.HTTPError(
            "403 Forbidden - cookies may be expired or you may not have access to this lesson.\n"
            "Try logging into Skool in Chrome and running again."
        )

    response.raise_for_status()
    return response.text
