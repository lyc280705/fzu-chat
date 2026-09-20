"""Real ES256/CBOR WebAuthn verification, without mocking cryptography."""
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from webauthn.helpers import bytes_to_base64url as b64

from app import passkeys
from app.auth import invalidate_user_sessions, delete_user_storage
from app.server import app, AUTH_COOKIE_NAME

ORIGIN = "https://testserver"
HEADERS = {"Origin": ORIGIN, "X-FZU-Passkey": "1"}


class Authenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        pub = self.key.public_key().public_numbers()
        self.cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: pub.x.to_bytes(32, 'big'), -3: pub.y.to_bytes(32, 'big')})

    def response(self, options, register=False, *, origin=ORIGIN, uv=True, count=1, rp="testserver", cross_origin=False, synced=False):
        data = json.dumps({"type": "webauthn.create" if register else "webauthn.get", "origin": origin,
                           "challenge": options["challenge"], "crossOrigin": cross_origin}).encode()
        auth = hashlib.sha256(rp.encode()).digest() + bytes([1 | (4 if uv else 0) | (64 if register else 0) | (24 if synced else 0)]) + (0 if register else count).to_bytes(4, 'big')
        response = {"clientDataJSON": b64(data)}
        if register:
            self.handle = options["user"]["id"]
            auth += bytes(16) + len(self.id).to_bytes(2, 'big') + self.id + self.cose
            response["attestationObject"] = b64(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth}))
            response["transports"] = ["internal"]
        else:
            response.update(authenticatorData=b64(auth), userHandle=self.handle,
                signature=b64(self.key.sign(auth + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256()))))
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "response": response,
                "clientExtensionResults": {}}


class PasskeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = passkeys.PasskeyStore(Path(self.temp.name) / "passkeys.sqlite")
        self.addCleanup(self.store.db.close)
        for target, value in (("app.passkeys.store", self.store), ("app.passkeys.ORIGIN", ORIGIN),
                              ("app.passkeys.RP_ID", "testserver"), ("app.passkey_routes.fixed_window_rate_limit", lambda *a: True)):
            p = patch(target, value); p.start(); self.addCleanup(p.stop)
        self.client = TestClient(app, base_url=ORIGIN, headers=HEADERS)
        self.addCleanup(self.client.close)
        self.auth = Authenticator()

    def options(self, kind="register", client=None, **body):
        r = (client or self.client).post(f"/api/auth/passkey/{kind}/options", json={"accepted_legal": True, **body})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def verify(self, kind, credential, client=None):
        return (client or self.client).post(f"/api/auth/passkey/{kind}/verify", json={"credential": credential})

    def signup(self):
        options = self.options()
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "required")
        r = self.verify("register", self.auth.response(options, True))
        self.assertEqual(r.status_code, 200, r.text)
        me = self.client.get("/api/auth/me").json()
        self.addCleanup(delete_user_storage, me["user_id"])
        self.addCleanup(invalidate_user_sessions, me["user_id"])
        return me

    def test_anonymous_signup_and_discoverable_login_preserve_identity(self):
        me = self.signup()
        self.assertEqual(me["auth_provider"], "passkey")
        self.assertEqual(me["student_type"], "visitor")
        self.assertFalse(me["edu_authenticated"])
        self.client.cookies.clear()
        options = self.options("login")
        self.assertFalse(options.get("allowCredentials"))
        self.assertEqual(self.verify("login", self.auth.response(options)).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json()["user_id"], me["user_id"])

    def test_origin_challenge_rp_and_user_verification_required(self):
        for kwargs in ({"origin": "https://evil.example"}, {"rp": "evil.example"}, {"uv": False}, {"cross_origin": True}):
            options = self.options()
            self.assertEqual(self.verify("register", self.auth.response(options, True, **kwargs)).status_code, 400)
        options = self.options()
        bad = {**options, "challenge": b64(secrets.token_bytes(32))}
        self.assertEqual(self.verify("register", self.auth.response(bad, True)).status_code, 400)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)

    def test_cookie_binding_csrf_and_consent(self):
        self.assertEqual(self.client.post("/api/auth/passkey/register/options", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/passkey/login/options", json={"accepted_legal": True}, headers={"Origin": "https://evil.example"}).status_code, 403)
        options = self.options()
        with TestClient(app, base_url=ORIGIN, headers=HEADERS) as other:
            self.assertEqual(self.verify("register", self.auth.response(options, True), other).status_code, 400)
        self.assertEqual(self.verify("register", self.auth.response(options, True)).status_code, 200)
        me = self.client.get("/api/auth/me").json()
        invalidate_user_sessions(me["user_id"]); delete_user_storage(me["user_id"])

    def test_expired_challenge_and_failed_response_are_single_use(self):
        options = self.options()
        self.store.db.execute("UPDATE ceremonies SET expires=0"); self.store.db.commit()
        self.assertEqual(self.verify("register", self.auth.response(options, True)).status_code, 400)
        options = self.options()
        cookie = self.client.cookies[passkeys.COOKIE]
        self.assertEqual(self.verify("register", self.auth.response(options, True, uv=False)).status_code, 400)
        self.client.cookies.set(passkeys.COOKIE, cookie, domain="testserver.local", path=passkeys.COOKIE_PATH)
        self.assertEqual(self.verify("register", self.auth.response(options, True)).status_code, 400)

    def test_bad_signature_handle_counter_and_login_replay_rejected(self):
        self.signup()
        for field in ("signature", "userHandle"):
            options = self.options("login")
            credential = self.auth.response(options)
            credential["response"][field] = b64(b"invalid")
            self.assertEqual(self.verify("login", credential).status_code, 400)
        options = self.options("login")
        credential = self.auth.response(options)
        cookie = self.client.cookies[passkeys.COOKIE]
        self.assertEqual(self.verify("login", credential).status_code, 200)
        self.client.cookies.set(passkeys.COOKIE, cookie, domain="testserver.local", path=passkeys.COOKIE_PATH)
        self.assertEqual(self.verify("login", credential).status_code, 400)
        options = self.options("login")
        self.assertEqual(self.verify("login", self.auth.response(options, count=1)).status_code, 400)

    def test_key_management_last_key_guard_and_revocation(self):
        self.signup()
        first = self.client.get("/api/auth/passkey/credentials").json()[0]
        self.assertEqual(self.client.request("DELETE", "/api/auth/passkey/credentials", json={"credential_id": first["id"]}).status_code, 400)
        second = Authenticator()
        options = self.options(enroll=True)
        self.assertEqual(self.verify("register", second.response(options, True)).status_code, 200)
        self.assertEqual(len(self.client.get("/api/auth/passkey/credentials").json()), 2)
        self.assertEqual(self.client.request("DELETE", "/api/auth/passkey/credentials", json={"credential_id": first["id"]}).status_code, 200)
        options = self.options("login")
        self.assertEqual(self.verify("login", self.auth.response(options)).status_code, 400)

    def test_enrollment_requires_recent_authenticated_session(self):
        self.assertEqual(self.client.post("/api/auth/passkey/register/options", json={"accepted_legal": True, "enroll": True}).status_code, 401)
        self.signup()
        with patch("app.passkeys.time.time", return_value=time.time() + 601):
            self.assertEqual(self.client.post("/api/auth/passkey/register/options", json={"accepted_legal": True, "enroll": True}).status_code, 403)

    def test_account_deletion_removes_keys_and_blocks_pending_login(self):
        self.signup()
        options = self.options("login")
        credential = self.auth.response(options)
        r = self.client.delete("/api/account")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM accounts").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)
        self.assertEqual(self.verify("login", credential).status_code, 400)
        self.assertNotIn(AUTH_COOKIE_NAME, self.client.cookies)

    def test_public_credentials_persist_across_store_reopen(self):
        me = self.signup()
        other = passkeys.PasskeyStore(self.store.path)
        try:
            self.assertEqual(len(other.list_keys(me["user_id"])), 1)
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        finally:
            other.db.close()

    def test_synced_passkey_with_zero_signature_counter_can_login_repeatedly(self):
        options = self.options()
        self.assertEqual(self.verify("register", self.auth.response(options, True, synced=True)).status_code, 200)
        me = self.client.get("/api/auth/me").json()
        self.addCleanup(delete_user_storage, me["user_id"])
        self.addCleanup(invalidate_user_sessions, me["user_id"])
        for _ in range(2):
            options = self.options("login")
            self.assertEqual(self.verify("login", self.auth.response(options, count=0, synced=True)).status_code, 200)
        self.assertTrue(self.client.get("/api/auth/passkey/credentials").json()[0]["backed_up"])

    def test_pending_enrollment_is_bound_to_original_session_and_cannot_restore_deleted_identity(self):
        self.signup()
        second = Authenticator()
        options = self.options(enroll=True)
        credential = second.response(options, True)
        cookie = self.client.cookies[passkeys.COOKIE]
        # Even a client that knows the public options and ceremony cookie needs
        # the recent original session to attach a key to that identity.
        with TestClient(app, base_url=ORIGIN, headers=HEADERS) as other:
            other.cookies.set(passkeys.COOKIE, cookie, domain="testserver.local", path=passkeys.COOKIE_PATH)
            self.assertEqual(self.verify("register", credential, other).status_code, 403)
        options = self.options(enroll=True)
        credential = second.response(options, True)
        self.assertEqual(self.client.delete("/api/account").status_code, 200)
        self.assertEqual(self.verify("register", credential).status_code, 400)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM credentials").fetchone()[0], 0)

    def test_duplicate_credentials_cannot_be_reassigned_to_a_new_identity(self):
        me = self.signup()
        options = self.options()  # a second independent signup, not enrollment
        self.assertEqual(self.verify("register", self.auth.response(options, True)).status_code, 400)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM accounts").fetchone()[0], 1)
        self.assertEqual(self.store.list_keys(me["user_id"])[0]["id"], b64(self.auth.id))

    def test_cross_identity_key_removal_is_rejected(self):
        me = self.signup()
        key_id = b64(self.auth.id)
        from app.auth import create_session
        other_id = "visitor_passkey_" + secrets.token_hex(16)
        token = create_session(other_id, "visitor", "test")
        self.addCleanup(delete_user_storage, other_id)
        self.addCleanup(invalidate_user_sessions, other_id)
        with self.assertRaises(passkeys.PasskeyError):
            self.store.remove_key(other_id, key_id, token)
        self.assertEqual(len(self.store.list_keys(me["user_id"])), 1)

    def test_rate_limits_and_cookie_flags(self):
        with patch("app.passkey_routes.fixed_window_rate_limit", return_value=False):
            self.assertEqual(self.client.post("/api/auth/passkey/login/options", json={"accepted_legal": True}).status_code, 429)
        self.options()
        cookie = next(c for c in self.client.cookies.jar if c.name == passkeys.COOKIE)
        self.assertTrue(cookie.secure)
        self.assertIn("HttpOnly", cookie._rest)
        self.assertEqual(cookie._rest["SameSite"], "strict")


if __name__ == '__main__':
    unittest.main()
