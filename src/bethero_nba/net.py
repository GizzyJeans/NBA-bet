"""The only way code reaches the network (RULES R-4.7).

This is the role the brief gave `pilot.py`. A client refuses to make a request
unless it was built with `live=True`, which only a command-line `--live` flag
sets; tests never pass it. Requests to one host are spaced at least
`min_interval_s` apart and identify the client by its repository URL rather
than a personal email.

Every response body is stored gzipped next to a metadata file holding the
URL, retrieval time and SHA-256, so any number derived from it can be traced
and re-run offline. Secret query parameters (the Odds API key) are redacted
before anything is written.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SECRET_PARAMS = ("apiKey", "api_key", "key", "token")


class LiveRequestsDisabled(RuntimeError):
    """A live request was attempted without the explicit live flag."""


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Fetched:
    body: bytes
    status: int
    headers: dict[str, str]
    url: str                  # secrets redacted
    retrieved_at: datetime    # UTC
    sha256: str
    path: Path | None = None

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def redact(url: str, secrets: tuple[str, ...] = SECRET_PARAMS) -> str:
    parts = urllib.parse.urlsplit(url)
    query = [(k, "REDACTED" if k in secrets else v)
             for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


class HttpClient:
    def __init__(self, cache_dir: Path | str, *, live: bool, user_agent: str,
                 min_interval_s: float, timeout: float = 30.0,
                 opener: Callable | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.cache_dir = Path(cache_dir)
        self.live = live
        self.user_agent = user_agent
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._clock, self._sleep, self._now = clock, sleep, now
        self._last: dict[str, float] = {}

    @classmethod
    def from_config(cls, cfg, cache_dir: Path | str, *, live: bool, **kwargs) -> "HttpClient":
        return cls(cache_dir, live=live, user_agent=cfg.get("data_access.user_agent"),
                   min_interval_s=cfg.get("data_access.min_interval_s"), **kwargs)

    def get(self, url: str, params: dict | None = None) -> Fetched:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        shown = redact(url)
        if not self.live:
            raise LiveRequestsDisabled(f"live requests are off (pass --live): {shown}")
        host = urllib.parse.urlsplit(url).netloc
        wait = self.min_interval_s - (self._clock() - self._last.get(host, -1e18))
        if wait > 0:
            self._sleep(wait)
        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with self._open(request, timeout=self.timeout) as response:
                body = response.read()
                status = getattr(response, "status", 200)
                headers = {k.lower(): v for k, v in dict(response.headers).items()}
        except urllib.error.HTTPError as exc:
            raise FetchError(f"HTTP {exc.code} from {shown}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchError(f"cannot reach {shown}: {exc}") from None
        finally:
            self._last[host] = self._clock()
        fetched = Fetched(body, status, headers, shown, self._now(),
                          hashlib.sha256(body).hexdigest())
        return self._store(host, fetched)

    def _store(self, host: str, fetched: Fetched) -> Fetched:
        folder = self.cache_dir / host
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{fetched.retrieved_at:%Y%m%dT%H%M%SZ}_{fetched.sha256[:12]}"
        body_path = folder / f"{stem}.json.gz"
        with gzip.GzipFile(body_path, "wb", mtime=0) as fh:
            fh.write(fetched.body)
        meta = {
            "url": fetched.url,
            "retrieved_at": fetched.retrieved_at.isoformat(),
            "status": fetched.status,
            "sha256": fetched.sha256,
            "bytes": len(fetched.body),
            "headers": {k: v for k, v in fetched.headers.items()
                        if k.startswith("x-requests") or k == "content-type"},
        }
        (folder / f"{stem}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        return Fetched(fetched.body, fetched.status, fetched.headers, fetched.url,
                       fetched.retrieved_at, fetched.sha256, body_path)


def load_cached(body_path: Path | str) -> Fetched:
    """Re-open a stored response; the hash is checked so an edited file is caught."""
    body_path = Path(body_path)
    meta_path = body_path.with_name(body_path.name.replace(".json.gz", ".meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with gzip.open(body_path, "rb") as fh:
        body = fh.read()
    digest = hashlib.sha256(body).hexdigest()
    if digest != meta["sha256"]:
        raise FetchError(f"{body_path}: SHA-256 does not match its metadata")
    return Fetched(body, meta["status"], meta.get("headers", {}), meta["url"],
                   datetime.fromisoformat(meta["retrieved_at"]), digest, body_path)
