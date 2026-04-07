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
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

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
    with _lock:
        _sessions[token] = {
            "user_id": user_id,
            "student_type": student_type,
            "display_name": display_name or user_id,
            "created_at": time.time(),
            "edu_authenticated": edu_authenticated,
            "edu_cookies": edu_cookies,
        }
    user_dir(user_id)  # ensure directory exists
    return token


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """Return session data for *token*, or ``None`` if invalid / expired."""
    with _lock:
        session = _sessions.get(token)
    if session is None:
        return None
    if time.time() - session["created_at"] > SESSION_TTL:
        invalidate_session(token)
        return None
    return session


def invalidate_session(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)


def update_session(token: str, updates: Dict[str, Any]) -> None:
    with _lock:
        if token in _sessions:
            _sessions[token].update(updates)
