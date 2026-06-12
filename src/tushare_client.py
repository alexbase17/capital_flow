"""Minimal TuShare Pro HTTP client used by market data fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config_loader import get_config
from src.http_client import request_json


TUSHARE_API_URL = "https://api.tushare.pro"


class TushareUnavailable(RuntimeError):
    """Raised when TuShare cannot be used for the requested call."""


@dataclass(frozen=True)
class TushareClient:
    token: str | None = None
    api_url: str = TUSHARE_API_URL
    timeout: int = 25

    @classmethod
    def from_env(cls) -> "TushareClient":
        return cls(token=get_config("TUSHARE_TOKEN"))

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def query(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.token:
            raise TushareUnavailable("TUSHARE_TOKEN is not set")
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": fields or "",
        }
        data = request_json(
            self.api_url,
            method="POST",
            headers={"Content-Type": "application/json"},
            payload=payload,
            timeout=self.timeout,
        )
        if not isinstance(data, dict):
            raise TushareUnavailable(f"{api_name}: TuShare returned non-object JSON")
        if data.get("code") != 0:
            message = data.get("msg") or data.get("message") or "TuShare request failed"
            raise TushareUnavailable(f"{api_name}: {message}")
        items = (data.get("data") or {}).get("items") or []
        fields_list = (data.get("data") or {}).get("fields") or []
        return [dict(zip(fields_list, item)) for item in items]
