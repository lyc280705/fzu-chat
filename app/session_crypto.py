"""Authenticated encryption for server-side session credentials."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .runtime_state import redis_configured


@lru_cache(maxsize=1)
def session_cipher() -> Fernet:
    key = os.getenv("FZU_CHAT_SESSION_ENCRYPTION_KEY", "").strip()
    path = Path(os.getenv("FZU_CHAT_SESSION_ENCRYPTION_KEY_FILE", "/run/secrets/session_encryption_key"))
    if not key and path.is_file():
        key = path.read_text().strip()
    if not key:
        if redis_configured():
            raise RuntimeError("Redis session storage requires a persistent session encryption key")
        # Local process-only development has no shared or persistent credentials.
        return Fernet(Fernet.generate_key())
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Invalid session encryption key configuration") from exc


def seal_session(value: dict[str, Any]) -> dict[str, Any]:
    return {"format": "fernet-v1", "edu_revision": value.get("edu_revision", ""),
            "ciphertext": session_cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()}


def open_session(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value or value.get("format") != "fernet-v1":
        return None
    try:
        plaintext = session_cipher().decrypt(value["ciphertext"].encode())
        payload = json.loads(plaintext)
        return payload if isinstance(payload, dict) else None
    except (InvalidToken, KeyError, ValueError, TypeError, AttributeError):
        return None
