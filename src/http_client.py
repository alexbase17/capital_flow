"""Small JSON HTTP helpers shared by external data providers."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT = 20


class JsonHttpError(RuntimeError):
    """Raised when an external JSON HTTP request fails."""


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict | list:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise JsonHttpError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise JsonHttpError(f"Network error from {url}: {reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonHttpError(f"Invalid JSON from {url}") from exc
