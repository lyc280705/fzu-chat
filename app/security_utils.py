from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in _TRUTHY_VALUES


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def ensure_private_file(path: Path) -> Path:
    if path.exists():
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path


def mask_user_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"