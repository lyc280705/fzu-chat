"""Discoverable WebAuthn identities. Only public keys are stored here.

Challenges are short-lived, cookie-bound and consumed even on verification
failure. SQLite transactions serialize verification, key removal and account
deletion across workers. RP configuration never comes from an HTTP Host header.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from threading import RLock
import time
from urllib.parse import urlparse

from webauthn import (generate_registration_options, generate_authentication_options,
                      verify_registration_response, verify_authentication_response, options_to_json)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                    UserVerificationRequirement, PublicKeyCredentialDescriptor)

from .auth import get_session
from .security_utils import ensure_private_dir, ensure_private_file

ORIGIN = os.getenv("FZU_CHAT_WEBAUTHN_ORIGIN", "https://mylingxi.cn").rstrip("/")
RP_ID = urlparse(ORIGIN).hostname
COOKIE = "fzu_passkey_ceremony"
COOKIE_PATH = "/api/auth/passkey"
TTL = 180
MAX_KEYS = 10


class PasskeyError(RuntimeError):
    def __init__(self, message="通行密钥验证失败，请重新尝试。", status=400, code="verification_failed"):
        super().__init__(message)
        self.status = status
        self.code = code


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fresh_session(token):
    session = get_session(token) if token else None
    if not session or time.time() - session.get("created_at", 0) > 600:
        raise PasskeyError("请先退出并重新登录，再管理通行密钥。", 403)
    return session


def require_top_level(credential):
    # This service does not offer embedded/iframe passkey authentication.
    client_data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
    if client_data.get("crossOrigin", False) is not False:
        raise PasskeyError()


class PasskeyStore:
    def __init__(self, path):
        self.path = Path(path)
        ensure_private_dir(self.path.parent)
        self.lock = RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS accounts (
                user_id TEXT PRIMARY KEY, handle BLOB NOT NULL UNIQUE, profile TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS credentials (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
                public_key BLOB NOT NULL, sign_count INTEGER NOT NULL, name TEXT NOT NULL,
                created REAL NOT NULL, used REAL, device_type TEXT NOT NULL, backed_up INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS credentials_user ON credentials(user_id);
            CREATE TABLE IF NOT EXISTS ceremonies (
                id TEXT PRIMARY KEY, purpose TEXT NOT NULL, user_id TEXT NOT NULL,
                binding TEXT NOT NULL, data TEXT NOT NULL, expires REAL NOT NULL);
        """)
        self._permissions()

    def _permissions(self):
        for suffix in ("", "-wal", "-shm"):
            ensure_private_file(Path(str(self.path) + suffix))

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            finally:
                self._permissions()

    def _challenge(self, db, purpose, data, user_id="", binding="", old_cookie=""):
        db.execute("DELETE FROM ceremonies WHERE expires <= ? OR id = ?", (time.time(), digest(old_cookie)))
        cookie = secrets.token_hex(32)
        db.execute("INSERT INTO ceremonies VALUES (?, ?, ?, ?, ?, ?)",
                   (digest(cookie), purpose, user_id, binding, json.dumps(data), time.time() + TTL))
        return cookie

    def consume(self, cookie, purpose):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM ceremonies WHERE id=?", (digest(cookie),)).fetchone()
            db.execute("DELETE FROM ceremonies WHERE id=?", (digest(cookie),))
        if not row or row["expires"] <= time.time() or row["purpose"] != purpose:
            raise PasskeyError("本次验证已过期或已使用，请关闭其他登录弹窗后重新尝试。", code="challenge_expired")
        return dict(row), json.loads(row["data"])

    def register_options(self, *, token="", old_cookie=""):
        with self.transaction() as db:
            if token:
                session = fresh_session(token)
                profile = {k: session.get(k, "") for k in ("user_id", "student_type", "display_name", "auth_provider", "provider_subject_hash", "avatar_url")}
                account = db.execute("SELECT * FROM accounts WHERE user_id=?", (profile["user_id"],)).fetchone()
                handle = account["handle"] if account else secrets.token_bytes(32)
            else:
                handle = secrets.token_bytes(32)
                profile = {"user_id": "visitor_passkey_" + secrets.token_hex(16), "student_type": "visitor",
                           "display_name": "通行密钥访客", "auth_provider": "passkey"}
            keys = db.execute("SELECT id FROM credentials WHERE user_id=?", (profile["user_id"],)).fetchall()
            if len(keys) >= MAX_KEYS:
                raise PasskeyError("每个身份最多可保存 10 个通行密钥。")
            options = json.loads(options_to_json(generate_registration_options(
                rp_id=RP_ID, rp_name="福大灵犀", user_id=handle,
                user_name="灵犀 · " + bytes_to_base64url(handle)[:8], user_display_name=profile["display_name"],
                authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                    require_resident_key=True, user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(k["id"])) for k in keys],
            )))
            data = {"profile": profile, "handle": bytes_to_base64url(handle), "challenge": options["challenge"]}
            cookie = self._challenge(db, "register", data, profile["user_id"], digest(token) if token else "", old_cookie)
        return cookie, options

    def login_options(self, old_cookie=""):
        options = json.loads(options_to_json(generate_authentication_options(
            rp_id=RP_ID, user_verification=UserVerificationRequirement.REQUIRED)))
        with self.transaction() as db:
            cookie = self._challenge(db, "login", {"challenge": options["challenge"]}, old_cookie=old_cookie)
        return cookie, options

    def register(self, cookie, credential, token, name, create_session):
        row, data = self.consume(cookie, "register")
        require_top_level(credential)
        with self.transaction() as db:
            profile = data["profile"]
            if row["binding"]:
                session = fresh_session(token)
                if not hmac.compare_digest(row["binding"], digest(token)) or session["user_id"] != row["user_id"]:
                    raise PasskeyError()
            verified = verify_registration_response(credential=credential,
                expected_challenge=base64url_to_bytes(data["challenge"]), expected_origin=ORIGIN,
                expected_rp_id=RP_ID, require_user_verification=True)
            handle = base64url_to_bytes(data["handle"])
            account = db.execute("SELECT handle FROM accounts WHERE user_id=?", (row["user_id"],)).fetchone()
            if account and not hmac.compare_digest(account["handle"], handle):
                raise PasskeyError("身份已更新，请重新创建通行密钥。")
            if db.execute("SELECT count(*) FROM credentials WHERE user_id=?", (row["user_id"],)).fetchone()[0] >= MAX_KEYS:
                raise PasskeyError("通行密钥数量已达上限。")
            db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?, ?)", (row["user_id"], handle, json.dumps(profile)))
            db.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (bytes_to_base64url(verified.credential_id), row["user_id"], verified.credential_public_key,
                 verified.sign_count, name, time.time(), verified.credential_device_type.value, int(verified.credential_backed_up)))
            # Session creation is inside the same lock as account deletion.
            return create_session(profile) if not row["binding"] else None

    def login(self, cookie, credential, create_session):
        _, data = self.consume(cookie, "login")
        require_top_level(credential)
        with self.transaction() as db:
            credential_id = bytes_to_base64url(base64url_to_bytes(credential.get("id", "")))
            key = db.execute("SELECT c.*, a.handle, a.profile FROM credentials c JOIN accounts a ON a.user_id=c.user_id WHERE c.id=?", (credential_id,)).fetchone()
            if not key:
                raise PasskeyError("这个通行密钥未在本站登记，或关联账号已删除。请选择其他已登记的密钥；如需重新开始，请创建新的通行密钥。", code="credential_not_found")
            user_handle = base64url_to_bytes(credential.get("response", {}).get("userHandle") or "")
            if not hmac.compare_digest(user_handle, key["handle"]):
                raise PasskeyError("密钥管理工具返回的身份信息不匹配。请重新选择正确的通行密钥，或换用其他支持的密钥管理工具。", code="identity_mismatch")
            verified = verify_authentication_response(credential=credential,
                expected_challenge=base64url_to_bytes(data["challenge"]), expected_origin=ORIGIN, expected_rp_id=RP_ID,
                credential_public_key=key["public_key"], credential_current_sign_count=key["sign_count"], require_user_verification=True)
            db.execute("UPDATE credentials SET sign_count=?, used=?, device_type=?, backed_up=? WHERE id=?",
                       (verified.new_sign_count, time.time(), verified.credential_device_type.value,
                        int(verified.credential_backed_up), credential_id))
            return create_session(json.loads(key["profile"]))

    def list_keys(self, user_id):
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT id,name,created,used,backed_up FROM credentials WHERE user_id=? ORDER BY created", (user_id,)).fetchall()]

    def remove_key(self, user_id, credential_id, token):
        with self.transaction() as db:
            session = fresh_session(token)
            if session["user_id"] != user_id:
                raise PasskeyError()
            account = db.execute("SELECT profile FROM accounts WHERE user_id=?", (user_id,)).fetchone()
            count = db.execute("SELECT count(*) FROM credentials WHERE user_id=?", (user_id,)).fetchone()[0]
            if account and json.loads(account["profile"]).get("auth_provider") == "passkey" and count <= 1:
                raise PasskeyError("这是该身份的最后一个通行密钥，请先添加另一个；如需停用，请删除账号。")
            if db.execute("DELETE FROM credentials WHERE user_id=? AND id=?", (user_id, credential_id)).rowcount != 1:
                raise PasskeyError("通行密钥不存在。", 404)

    def delete_user(self, user_id, revoke_sessions):
        with self.transaction() as db:
            db.execute("DELETE FROM ceremonies WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM accounts WHERE user_id=?", (user_id,))
            return revoke_sessions(user_id)


store = PasskeyStore(Path(__file__).resolve().parent / "storage" / "passkeys.sqlite")
