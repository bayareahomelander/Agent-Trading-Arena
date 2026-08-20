"""E3: injectable GET. No listening sockets."""

from __future__ import annotations

from urllib.error import URLError
from urllib.request import Request

import pytest

from arena_kernel.marketdata import CommonDataUnavailable
from arena_runtime.audit import REDACTION_MARKER, redact_provider_bytes
from arena_runtime.vendors.transport import fetch


def test_injected_get_receives_the_caller_url() -> None:
    seen: dict[str, object] = {}

    def get(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        seen["url"] = url
        seen["timeout"] = timeout
        seen["headers"] = headers
        return b'{"ok":true}'

    body = fetch(
        "https://example.test/bars",
        timeout=5,
        headers={"Accept": "application/json"},
        get=get,
    )
    assert body == b'{"ok":true}'
    assert seen["url"] == "https://example.test/bars"
    assert seen["timeout"] == 5
    assert seen["headers"] == {"Accept": "application/json"}


def test_redacting_wrapper_strips_api_key_from_returned_bytes() -> None:
    def get(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        return (
            b'{"api_key":"secret-live-key-1234567890",'
            b'"Authorization":"Bearer secret-live-key-1234567890"}'
        )

    def wrapped(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        return redact_provider_bytes(get(url, timeout=timeout, headers=headers))

    body = fetch(
        "https://example.test/bars?apiKey=secret-live-key-1234567890",
        timeout=1,
        headers={"Authorization": "Bearer secret-live-key-1234567890"},
        get=wrapped,
    )
    assert b"secret-live-key-1234567890" not in body
    assert REDACTION_MARKER in body


def test_urlerror_becomes_common_data_unavailable() -> None:
    def get(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        raise URLError("connection refused")

    with pytest.raises(CommonDataUnavailable) as exc:
        fetch("https://example.test/bars", timeout=1, get=get)
    assert exc.value.path == "url"


def test_timeout_becomes_common_data_unavailable() -> None:
    def get(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        raise TimeoutError("timed out")

    with pytest.raises(CommonDataUnavailable) as exc:
        fetch("https://example.test/bars", timeout=1, get=get)
    assert exc.value.path == "timeout"


def test_stdlib_get_uses_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class _Response:
        def read(self) -> bytes:
            return b"ok"

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("arena_runtime.vendors.transport.urlopen", fake_urlopen)
    assert fetch("https://example.test/x", timeout=3, headers={"A": "b"}) == b"ok"
    assert seen["url"] == "https://example.test/x"
    assert seen["timeout"] == 3
