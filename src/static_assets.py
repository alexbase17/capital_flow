"""Helpers for cache-busted static asset URLs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, url_for


def static_asset_version(filename: str) -> str:
    static_folder = current_app.static_folder
    if not static_folder:
        return "0"
    path = Path(static_folder) / filename
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return "0"
    date = datetime.fromtimestamp(modified_at, tz=timezone.utc).strftime("%Y%m%d")
    return f"{date}-{int(modified_at)}"


def static_url(filename: str) -> str:
    return f"{url_for('static', filename=filename)}?v={static_asset_version(filename)}"
