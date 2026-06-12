"""Small configuration loader for local environment variables."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT_DIR / ".env.local"
_LOADED_ENV_FILES: set[Path] = set()


def load_env_file(path: str | os.PathLike | None = None, *, override: bool = False) -> dict[str, str]:
    env_path = Path(path) if path else DEFAULT_ENV_PATH
    if not env_path.exists():
        return {}
    env_path = env_path.resolve()
    if env_path in _LOADED_ENV_FILES and not override:
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value

    _LOADED_ENV_FILES.add(env_path)
    return loaded


def ensure_local_env_loaded() -> None:
    load_env_file()


def get_config(name: str, default: str | None = None) -> str | None:
    ensure_local_env_loaded()
    return os.environ.get(name, default)


def has_config(name: str) -> bool:
    value = get_config(name)
    return bool(value)
