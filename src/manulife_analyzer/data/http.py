"""Shared HTTP client with retries, caching and polite rate-limiting."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import DATA_DIR

DEFAULT_CACHE_DIR = DATA_DIR / "raw" / "http_cache"


@dataclass
class HttpClient:
    user_agent: str
    timeout: int = 20
    cache_hours: int = 24
    rate_limit_seconds: float = 1.5
    cache_dir: Path | None = None
    _last_request_at: float = 0.0

    def _resolve_cache_dir(self) -> Path:
        return self.cache_dir or DEFAULT_CACHE_DIR

    def _cache_key(self, url: str, params: dict | None) -> Path:
        key_src = url + json.dumps(params or {}, sort_keys=True)
        digest = hashlib.sha256(key_src.encode()).hexdigest()[:24]
        host = httpx.URL(url).host.replace(".", "_")
        return self._resolve_cache_dir() / host / f"{digest}.bin"

    def _cache_fresh(self, path: Path) -> bool:
        if not path.exists() or self.cache_hours <= 0:
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return mtime > datetime.now() - timedelta(hours=self.cache_hours)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    def get(self, url: str, params: dict | None = None, use_cache: bool = True) -> bytes:
        cache_path = self._cache_key(url, params)
        if use_cache and self._cache_fresh(cache_path):
            return cache_path.read_bytes()

        self._throttle()
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        with httpx.Client(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            body = resp.content

        if use_cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(body)
        return body

    def get_json(self, url: str, params: dict | None = None, use_cache: bool = True) -> Any:
        return json.loads(self.get(url, params=params, use_cache=use_cache))
