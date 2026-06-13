"""Lightweight structured logging helpers for capital-flow operations."""

from __future__ import annotations

import json
import logging
from typing import Any


LOGGER = logging.getLogger("capital_flow")


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    LOGGER.info(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
