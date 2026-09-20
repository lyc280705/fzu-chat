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

from .runtime_state import get_redis_client, redis_configured, redis_delete, redis_get_json, redis_set_json
from .security_utils import ensure_private_dir
from .session_crypto import open_session, seal_session, session_cipher

logger = logging.getLogger(__name__)

STORAGE_DIR = ensure_private_dir(Path(__file__).resolve().parent / "storage")
USERS_DIR = ensure_private_dir(STORAGE_DIR / "users")

# In-memory session store  –  token → session dict
_sessions: Dict[str, Dict[str, Any]] = {}
_edu_sessions: Dict[str, Dict[str, Any]] = {}
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
    return f"session:v2:{hashlib.sha256(token.encode()).hexdigest()}"


def _edu_session_key(user_id: str) -> str:
    return f"edu-session:{hashlib.sha256(user_id.encode()).hexdigest()}"


def _with_shared_edu_state(session: Dict[str, Any]) -> Dict[str, Any]:
    # Visitor identities must never inherit undergraduate credentials.
    if session.get("student_type") != "undergraduate":
        return dict(session)
    key = _edu_session_key(session["user_id"])
    raw_shared = redis_get_json(key)
    shared = open_session(raw_shared)
    if raw_shared is not None and shared is None:
        # Corrupt shared data must not reactivate a legacy per-device credential.
        return {**session, "edu_authenticated": False, "edu_cookies": None,
                "edu_identifier": "", "edu_status_message": "教务连接状态无法读取，请重新连接教务。"}
    if shared is None:
        with _lock:
            shared = _edu_sessions.get(key)
            if shared and float(shared.get("shared_expires_at", 0)) <= time.time():
                _edu_sessions.pop(key, None)
                shared = None
    return {**session, **(shared or {})}


def update_user_edu_session(
    user_id: str, state: Dict[str, Any], *, expected_revision: str | None = None,
) -> bool:
    """Share only education state across this student's authenticated devices.

    Conditional writes prevent an old in-flight validation from clearing a
    newer connection. Redis performs the revision comparison atomically.
    """
    key = _edu_session_key(user_id)
    fields = ("edu_authenticated", "edu_cookies", "edu_identifier", "edu_status_message",
              "edu_session_expires_at")
    shared = {name: state.get(name) for name in fields}
    shared.update(edu_revision=secrets.token_hex(16), shared_expires_at=time.time() + SESSION_TTL)
    client = get_redis_client()
    if client is None and redis_configured():
        raise RuntimeError("教务连接状态暂时无法同步，请稍后重试。")
    if client is not None:
        try:
            changed = client.eval("""
                local raw = redis.call('GET', KEYS[1])
                local revision = ''
                if raw then revision = cjson.decode(raw).edu_revision or '' end
                if ARGV[1] == 'check' and revision ~= ARGV[2] then return 0 end
                redis.call('SET', KEYS[1], ARGV[3], 'EX', ARGV[4])
                return 1
            """, 1, key, "check" if expected_revision is not None else "set",
                expected_revision or "", json.dumps(seal_session(shared)), SESSION_TTL)
            if changed:
                with _lock:
                    _edu_sessions.pop(key, None)
            return bool(changed)
        except Exception as exc:
            logger.warning("Shared education state update failed: %s", type(exc).__name__)
            # Do not create divergent credentials when the shared store is failing.
            raise RuntimeError("教务连接状态暂时无法同步，请稍后重试。") from exc
    with _lock:
        previous = _edu_sessions.get(key, {})
        if float(previous.get("shared_expires_at", 0)) <= time.time():
            previous = {}
        if expected_revision is not None and previous.get("edu_revision", "") != expected_revision:
            return False
        _edu_sessions[key] = shared
    return True


def delete_user_edu_session(user_id: str) -> None:
    key = _edu_session_key(user_id)
    redis_delete(key)
    with _lock:
        _edu_sessions.pop(key, None)


def migrate_legacy_sessions() -> int:
    """Encrypt legacy Redis values and hash bearer-token keys before serving."""
    session_cipher()  # Fail closed on a missing production key.
    client = get_redis_client()
    if client is None:
        if redis_configured():
            raise RuntimeError("Session storage unavailable during startup")
        return 0
    migrated = 0
    for raw_key in client.scan_iter(match="session:*", count=100):
        key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        raw = client.get(key)
        if not raw:
            continue
        payload = json.loads(raw)
        if key.startswith("session:v2:"):
            if open_session(payload) is None:
                raise RuntimeError("Existing sessions cannot be decrypted; check the encryption key")
            continue
        if not isinstance(payload, dict) or not payload.get("user_id"):
            continue
        ttl = min(client.ttl(key), _remaining_session_ttl(payload))
        if ttl <= 0:
            client.delete(key)
            continue
        with client.pipeline(transaction=True) as transaction:
            transaction.set(_session_key(key.split(":", 1)[1]), json.dumps(seal_session(payload)), ex=ttl, nx=True)
            transaction.delete(key)
            transaction.execute()
        migrated += 1
    return migrated


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
    if not redis_set_json(_session_key(token), seal_session(session), SESSION_TTL):
        with _lock:
            _sessions[token] = session
    user_dir(user_id)  # ensure directory exists
    return token


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """Return session data for *token*, or ``None`` if invalid / expired."""
    session = open_session(redis_get_json(_session_key(token)))
    if session is not None:
        if time.time() - float(session.get("created_at") or 0) > SESSION_TTL:
            invalidate_session(token)
            return None
        return _with_shared_edu_state(session)
    with _lock:
        session = _sessions.get(token)
    if session is None:
        return None
    if time.time() - session["created_at"] > SESSION_TTL:
        invalidate_session(token)
        return None
    return _with_shared_edu_state(session)


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
                    session = open_session(json.loads(raw_session))
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

    delete_user_edu_session(normalized_user_id)
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
    session = open_session(redis_get_json(_session_key(token)))
    if session is not None:
        session.update(updates)
        if not redis_set_json(_session_key(token), seal_session(session), _remaining_session_ttl(session)):
            with _lock:
                _sessions[token] = session
        return
    with _lock:
        if token in _sessions:
            _sessions[token].update(updates)
