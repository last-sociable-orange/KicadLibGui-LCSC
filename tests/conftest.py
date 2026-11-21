"""Offline test harness.

No test touches the network: recorded storefront responses live in ``fixtures/``
and :class:`FakeTransport` stands in for ``requests.Session`` so the real
:class:`lcsc_core.session.HttpSession` logic (pacing, retry, size cap, error
mapping) still runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a recorded response by file stem."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def next_data_page(webdata: dict[str, Any]) -> bytes:
    """Wrap a ``webData`` payload in the ``__NEXT_DATA__`` script an item page has."""
    payload = {"props": {"pageProps": {"webData": webdata}}}
    body = (
        "<!doctype html><html><head><title>part</title></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script></body></html>"
    )
    return body.encode("utf-8")


class FakeResponse:
    """The subset of ``requests.Response`` that :class:`HttpSession` uses."""

    def __init__(self, status_code: int = 200, body: bytes = b"",
                 headers: dict[str, str] | None = None, url: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.headers = dict(headers or {})
        self.url = url
        self.closed = False

    @property
    def content(self) -> bytes:
        return self._body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size: int = 65536):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def json(self) -> Any:
        return json.loads(self._body)

    def close(self) -> None:
        self.closed = True


def json_response(payload: Any, status_code: int = 200) -> FakeResponse:
    return FakeResponse(status_code=status_code,
                        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"})


class FakeTransport:
    """Stands in for ``requests.Session``: routes a request to a canned response."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        for key, value in self.routes.items():
            if key in url:
                if callable(value):
                    return value(method, url, kwargs)
                if isinstance(value, list):
                    return value.pop(0)
                return value
        raise AssertionError(f"unexpected request: {method} {url}")

    def close(self) -> None:
        return None

    # -- assertions ------------------------------------------------------

    def urls(self) -> list[str]:
        return [call["url"] for call in self.calls]

    def post_bodies(self) -> list[dict[str, Any]]:
        return [call["kwargs"].get("json") or {} for call in self.calls
                if call["method"] == "POST"]


def make_session(routes: dict[str, Any]):
    """An :class:`HttpSession` wired to :class:`FakeTransport`."""
    from lcsc_core.session import HttpSession

    transport = FakeTransport(routes)
    return HttpSession(session=transport, min_interval=0), transport


@pytest.fixture()
def domestic_search_payload() -> dict[str, Any]:
    return load_fixture("domestic_search")


@pytest.fixture()
def domestic_item_payload() -> dict[str, Any]:
    return load_fixture("domestic_item")


@pytest.fixture()
def workdir() -> Path:
    """A scratch directory for database and settings tests.

    ``tempfile``-based fixtures create mode-0700 directories that the Windows
    sandbox can refuse to write into, so scratch directories are created under
    the project with an inherited ACL instead.
    """
    import shutil
    import uuid

    root = ROOT / ".tmp" / "tests"
    root.mkdir(parents=True, exist_ok=True)
    target = root / uuid.uuid4().hex[:12]
    target.mkdir()
    try:
        yield target
    finally:
        shutil.rmtree(target, ignore_errors=True)
