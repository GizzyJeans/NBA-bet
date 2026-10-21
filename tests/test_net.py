import gzip
import json
from datetime import datetime, timezone

import pytest

from bethero_nba import net


class FakeResponse:
    def __init__(self, body, headers=None, status=200):
        self._body, self.headers, self.status = body, headers or {}, status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, body=b'{"ok": true}', headers=None):
        self.requests = []
        self.body, self.headers = body, headers or {"Content-Type": "application/json",
                                                   "X-Requests-Remaining": "497"}

    def __call__(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(self.body, self.headers)


def make_client(tmp_path, live=True, **kwargs):
    t = {"now": 100.0}
    slept = []

    def sleep(s):
        slept.append(s)
        t["now"] += s

    client = net.HttpClient(tmp_path, live=live, user_agent="bethero-nba/test (+repo)",
                            min_interval_s=1.0, clock=lambda: t["now"], sleep=sleep,
                            now=lambda: datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc), **kwargs)
    return client, slept


def test_refuses_without_live_flag(tmp_path):
    opener = FakeOpener()
    client, _ = make_client(tmp_path, live=False, opener=opener)
    with pytest.raises(net.LiveRequestsDisabled, match="REDACTED"):
        client.get("https://api.example.com/v4/odds", {"apiKey": "secret123"})
    assert opener.requests == []


def test_redacts_key_sets_user_agent_and_caches(tmp_path):
    opener = FakeOpener()
    client, _ = make_client(tmp_path, opener=opener)
    fetched = client.get("https://api.example.com/v4/odds", {"apiKey": "secret123", "regions": "us"})
    assert opener.requests[0].get_header("User-agent") == "bethero-nba/test (+repo)"
    assert "secret123" not in fetched.url and "REDACTED" in fetched.url
    meta_files = list(tmp_path.rglob("*.meta.json"))
    assert len(meta_files) == 1
    meta_text = meta_files[0].read_text(encoding="utf-8")
    assert "secret123" not in meta_text
    meta = json.loads(meta_text)
    assert meta["headers"]["x-requests-remaining"] == "497"
    with gzip.open(fetched.path, "rb") as fh:
        assert fh.read() == b'{"ok": true}'
    again = net.load_cached(fetched.path)
    assert again.sha256 == fetched.sha256 and again.json() == {"ok": True}


def test_rate_limit_spaces_requests_to_one_host(tmp_path):
    client, slept = make_client(tmp_path, opener=FakeOpener())
    client.get("https://api.example.com/a")
    client.get("https://api.example.com/b")
    client.get("https://other.example.com/c")
    assert slept == [pytest.approx(1.0)]


def test_tampered_cache_is_caught(tmp_path):
    client, _ = make_client(tmp_path, opener=FakeOpener())
    fetched = client.get("https://api.example.com/a")
    with gzip.GzipFile(fetched.path, "wb", mtime=0) as fh:
        fh.write(b'{"ok": false}')
    with pytest.raises(net.FetchError, match="SHA-256"):
        net.load_cached(fetched.path)
