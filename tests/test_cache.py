"""The on-disk response cache and its wiring into the HTTP session."""

from __future__ import annotations

import json
import time

from conftest import FakeResponse, FakeTransport, load_fixture

from lcsc_core.cache import ResponseCache, cache_key
from lcsc_core.session import HttpSession

URL = "https://item.szlcsc.com/26547.html"


class TestCacheKey:
    def test_same_request_has_the_same_key(self):
        first = cache_key("GET", URL, {"a": 1}, None)
        second = cache_key("get", URL, {"a": 1}, None)
        assert first == second

    def test_different_requests_differ(self):
        assert cache_key("GET", URL) != cache_key("GET", URL + "?x=1")
        assert cache_key("GET", URL, {"a": 1}) != cache_key("GET", URL, {"a": 2})
        assert cache_key("GET", URL) != cache_key("POST", URL)


class TestResponseCache:
    def test_round_trip(self, workdir):
        cache = ResponseCache(workdir / "cache", ttl=60)
        assert cache.get("k") is None
        cache.put("k", b"payload")
        assert cache.get("k") == b"payload"
        assert (workdir / "cache" / "k.json").exists()

    def test_expired_entry_is_dropped(self, workdir):
        cache = ResponseCache(workdir / "cache", ttl=0.02)
        cache.put("k", b"payload")
        time.sleep(0.05)
        assert cache.get("k") is None
        assert not (workdir / "cache" / "k.json").exists()

    def test_disabled_cache_does_nothing(self, workdir):
        cache = ResponseCache(workdir / "cache", ttl=0)
        cache.put("k", b"payload")
        assert cache.get("k") is None
        assert not (workdir / "cache").exists()

    def test_corrupt_entry_is_ignored(self, workdir):
        cache = ResponseCache(workdir / "cache", ttl=60)
        directory = workdir / "cache"
        directory.mkdir(parents=True)
        (directory / "k.json").write_text("{not json", encoding="utf-8")
        assert cache.get("k") is None

    def test_clear_removes_entries(self, workdir):
        cache = ResponseCache(workdir / "cache", ttl=60)
        cache.put("a", b"1")
        cache.put("b", b"2")
        assert cache.clear() == 2
        assert cache.get("a") is None

    def test_entry_is_readable_json(self, workdir):
        cache = ResponseCache(workdir / "cache", ttl=60)
        cache.put("k", b"hello")
        entry = json.loads((workdir / "cache" / "k.json").read_text(encoding="utf-8"))
        assert set(entry) == {"stored", "body"}


class TestSessionCaching:
    def _session(self, workdir, ttl):
        transport = FakeTransport({URL: FakeResponse(body=b"<html>page</html>")})
        cache = ResponseCache(workdir / "cache", ttl=ttl)
        return HttpSession(session=transport, min_interval=0, cache=cache), transport

    def test_detail_request_is_served_from_cache(self, workdir):
        session, transport = self._session(workdir, ttl=60)
        assert session.get_bytes(URL, cache_ttl=60) == b"<html>page</html>"
        assert session.get_bytes(URL, cache_ttl=60) == b"<html>page</html>"
        assert len(transport.calls) == 1

    def test_search_requests_are_never_cached(self, workdir):
        session, transport = self._session(workdir, ttl=60)
        session.get_bytes(URL)
        session.get_bytes(URL)
        assert len(transport.calls) == 2

    def test_json_helper_honours_the_cache(self, workdir):
        payload = load_fixture("international_detail")
        transport = FakeTransport({"product/detail": FakeResponse(
            body=json.dumps(payload).encode("utf-8"))})
        cache = ResponseCache(workdir / "cache", ttl=60)
        session = HttpSession(session=transport, min_interval=0, cache=cache)
        url = "https://wmsc.lcsc.com/ftps/wm/product/detail"
        first = session.get_json(url, params={"productCode": "C2040"}, cache_ttl=60)
        second = session.get_json(url, params={"productCode": "C2040"}, cache_ttl=60)
        assert first == second
        assert len(transport.calls) == 1
        # A different product is a different key.
        session.get_json(url, params={"productCode": "C8734"}, cache_ttl=60)
        assert len(transport.calls) == 2
