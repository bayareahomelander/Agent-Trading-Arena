"""Injectable HTTP GET. Default tests never open a socket."""

from __future__ import annotations

from typing import Callable, Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen

from arena_kernel.marketdata import CommonDataUnavailable

Get = Callable[..., bytes]


def fetch(
    url: str,
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
    get: Get | None = None,
) -> bytes:
    """GET ``url``. Timeouts and transport errors are common-data failures."""

    if not isinstance(url, str) or not url.strip() or url.strip() != url:
        raise CommonDataUnavailable("url", "must be a non-empty string without padding")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise CommonDataUnavailable("timeout", "must be a positive number")
    opener = _stdlib_get if get is None else get
    try:
        return opener(url, timeout=timeout, headers=dict(headers or {}))
    except CommonDataUnavailable:
        raise
    except TimeoutError as exc:
        raise CommonDataUnavailable("timeout", "request timed out") from exc
    except URLError as exc:
        raise CommonDataUnavailable("url", "request failed") from exc


def _stdlib_get(
    url: str,
    *,
    timeout: float,
    headers: Mapping[str, str],
) -> bytes:
    request = Request(url, headers=dict(headers), method="GET")
    with urlopen(request, timeout=timeout) as response:
        return response.read()
