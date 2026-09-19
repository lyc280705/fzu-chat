"""Authentication and session management for FZU Chat.

Provides token-based authentication with per-student conversation isolation.
Each student logs in with their FZU student ID and password. The password is
used to authenticate with the educational system; only session cookies are
persisted (never the raw password).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shutil
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from .runtime_state import get_redis_client, redis_delete, redis_get_json, redis_set_json
from .security_utils import ensure_private_dir

logger = logging.getLogger(__name__)

STORAGE_DIR = ensure_private_dir(Path(__file__).resolve().parent / "storage")
USERS_DIR = ensure_private_dir(STORAGE_DIR / "users")

# In-memory session store  –  token → session dict
_sessions: Dict[str, Dict[str, Any]] = {}
_lock = Lock()

SESSION_TTL = 86400 * 7  # 7 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_user_dir_name(user_id: str) -> str:
    """Derive a filesystem-safe directory name from a user ID."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def user_dir(user_id: str) -> Path:
    """Return (and ensure existence of) the per-user storage directory."""
    d = USERS_DIR / _safe_user_dir_name(user_id)
    return ensure_private_dir(d)


def user_store_path(user_id: str) -> Path:
    """Path to a user's conversation store file."""
    return user_dir(user_id) / "conversations.json"


def _session_key(token: str) -> str:
    return f"session:{token}"


def _remaining_session_ttl(session: Dict[str, Any]) -> int:
    created_at = float(session.get("created_at") or time.time())
    return max(1, int(SESSION_TTL - (time.time() - created_at)))


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(
    user_id: str,
    student_type: str = "undergraduate",
    display_name: str = "",
    edu_authenticated: bool = False,
    edu_cookies: Any = None,
) -> str:
    """Create a new authentication session and return the bearer token."""
    token = secrets.token_urlsafe(32)
    session = {
        "user_id": user_id,
        "student_type": student_type,
        "display_name": display_name or user_id,
        "created_at": time.time(),
        "edu_authenticated": edu_authenticated,
        "edu_cookies": edu_cookies,
    }
    if not redis_set_json(_session_key(token), session, SESSION_TTL):
        with _lock:
            _sessions[token] = session
    user_dir(user_id)  # ensure directory exists
    return token


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """Return session data for *token*, or ``None`` if invalid / expired."""
    session = redis_get_json(_session_key(token))
    if session is not None:
        if time.time() - float(session.get("created_at") or 0) > SESSION_TTL:
            invalidate_session(token)
            return None
        return session
    with _lock:
        session = _sessions.get(token)
    if session is None:
        return None
    if time.time() - session["created_at"] > SESSION_TTL:
        invalidate_session(token)
        return None
    return session


def invalidate_session(token: str) -> None:
    redis_delete(_session_key(token))
    with _lock:
        _sessions.pop(token, None)


def invalidate_user_sessions(user_id: str) -> int:
    """Invalidate every active session associated with a user."""
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return 0

    deleted_tokens: set[str] = set()
    client = get_redis_client()
    if client is not None:
        try:
            redis_keys: list[str] = []
            for raw_key in client.scan_iter(match="session:*", count=100):
                key = raw_key.decode("utf-8", errors="replace") if isinstance(raw_key, bytes) else str(raw_key)
                raw_session = client.get(key)
                if not raw_session:
                    continue
                try:
                    session = json.loads(raw_session)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(session, dict) and session.get("user_id") == normalized_user_id:
                    redis_keys.append(key)
                    deleted_tokens.add(key.split(":", 1)[1])
            if redis_keys:
                client.delete(*redis_keys)
        except Exception as exc:
            logger.warning("Redis user-session purge failed: %s", type(exc).__name__)

    with _lock:
        memory_tokens = [
            token for token, session in _sessions.items()
            if session.get("user_id") == normalized_user_id
        ]
        for token in memory_tokens:
            _sessions.pop(token, None)
            deleted_tokens.add(token)

    return len(deleted_tokens)


def delete_user_storage(user_id: str) -> bool:
    """Delete the legacy per-user storage directory, if it exists."""
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return False
    path = USERS_DIR / _safe_user_dir_name(normalized_user_id)
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)
    return True


def update_session(token: str, updates: Dict[str, Any]) -> None:
    session = redis_get_json(_session_key(token))
    if session is not None:
        session.update(updates)
        if not redis_set_json(_session_key(token), session, _remaining_session_ttl(session)):
            with _lock:
                _sessions[token] = session
        return
    with _lock:
        if token in _sessions:
            _sessions[token].update(updates)
