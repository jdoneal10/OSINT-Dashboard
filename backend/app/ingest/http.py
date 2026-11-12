"""Polite HTTP client shared by every ingester.

- Generic User-Agent with no personal details (CLAUDE.md privacy rules).
- robots.txt is honored for page/file fetches (``crawl=True``, the default). Documented APIs
  that a source explicitly provides for programmatic access (e.g. ACLED's) pass
  ``crawl=False``; their own terms and rate limits govern instead.
- At most one request per ``min_interval`` seconds per host.
- Retries with exponential backoff on 429/5xx and transport errors, honoring Retry-After.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "cartel-osint/0.1 (+local research dashboard)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

log = logging.getLogger(__name__)


class RobotsDisallowedError(RuntimeError):
    """The target path is disallowed by the host's robots.txt."""


class PoliteClient:
    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        timeout: float = 60.0,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ robots

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser = RobotFileParser()
        resp = self._send("GET", f"{origin}/robots.txt")
        if resp.status_code in (401, 403):
            parser.parse(["User-agent: *", "Disallow: /"])
        elif resp.status_code >= 400:
            parser.parse([])  # no robots.txt: everything allowed
        else:
            parser.parse(resp.text.splitlines())
        self._robots[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    # ------------------------------------------------------------------ requests

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self._min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            self._throttle(url)
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise
                delay = self._backoff_base**attempt
                log.warning("%s %s failed (%s); retrying in %.0fs", method, url, exc, delay)
            else:
                if resp.status_code not in RETRY_STATUSES or attempt >= self._max_retries:
                    return resp
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else self._backoff_base**attempt
                log.warning(
                    "%s %s -> HTTP %d; retrying in %.0fs", method, url, resp.status_code, delay
                )
            self._sleep(delay)
            attempt += 1

    def request(
        self, method: str, url: str, *, crawl: bool = True, **kwargs: Any
    ) -> httpx.Response:
        if crawl and not self.allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")
        return self._send(method, url, **kwargs)

    def get(self, url: str, *, crawl: bool = True, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, crawl=crawl, **kwargs)

    def post(self, url: str, *, crawl: bool = False, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, crawl=crawl, **kwargs)
