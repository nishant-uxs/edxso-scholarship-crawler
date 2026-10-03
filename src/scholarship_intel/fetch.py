"""HTTP fetch with polite defaults."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "ScholarshipIntelCrawler/1.1"
)


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    final_url: str
    ok: bool
    error: str | None = None
    content: bytes | None = None


class Fetcher:
    def __init__(self, delay_s: float = 0.6, timeout: float = 45.0):
        self.delay_s = delay_s
        self._last = 0.0
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )

    def get(self, url: str) -> FetchResult:
        # Local cached official docs
        if url.startswith("file:") or url.startswith("local:"):
            path = url.replace("file:///", "").replace("file://", "").replace("local:", "")
            p = Path(path)
            if not p.is_absolute():
                p = Path(__file__).resolve().parents[2] / path
            if not p.exists():
                return FetchResult(url, 0, "", url, False, f"missing local file {p}")
            data = p.read_bytes()
            text = "" if data.startswith(b"%PDF") else data.decode("utf-8", errors="ignore")
            return FetchResult(url, 200, text, str(p), True, None, data)

        wait = self.delay_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.client.get(url)
            self._last = time.time()
            return FetchResult(
                url=url,
                status_code=r.status_code,
                text=r.text if r.status_code < 400 and not r.content.startswith(b"%PDF") else "",
                final_url=str(r.url),
                ok=r.status_code < 400,
                error=None if r.status_code < 400 else f"HTTP {r.status_code}",
                content=r.content if r.status_code < 400 else None,
            )
        except Exception as e:
            self._last = time.time()
            return FetchResult(url=url, status_code=0, text="", final_url=url, ok=False, error=str(e))

    def close(self) -> None:
        self.client.close()
