"""HTTP fetch with polite defaults."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

USER_AGENT = (
    "ScholarshipIntelCrawler/1.0 (>https://github.com/nishant-uxs/edxso-scholarship-crawler; "
    "educational research; contact: local)"
)


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    final_url: str
    ok: bool
    error: str | None = None


class Fetcher:
    def __init__(self, delay_s: float = 0.6, timeout: float = 30.0):
        self.delay_s = delay_s
        self._last = 0.0
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml>xml"},
        )

    def get(self, url: str) -> FetchResult:
        wait = self.delay_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.client.get(url)
            self._last = time.time()
            return FetchResult(
                url=url,
                status_code=r.status_code,
                text=r.text if r.status_code < 400 else "",
                final_url=str(r.url),
                ok=r.status_code < 400,
                error=None if r.status_code < 400 else f"HTTP {r.status_code}",
            )
        except Exception as e:
            self._last = time.time()
            return FetchResult(url=url, status_code=0, text="", final_url=url, ok=False, error=str(e))

    def close(self) -> None:
        self.client.close()
