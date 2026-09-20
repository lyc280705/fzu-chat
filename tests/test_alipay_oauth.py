from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from time import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from app import alipay_oauth, oauth, runtime_state
from app.auth import delete_user_storage, invalidate_user_sessions
from app.oauth_logging import OAuthAccessLogFilter
from app.server import ALIPAY_STATE_COOKIE, app


class AlipayOAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.vendor_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fzu-alipay-test-")
        self.addCleanup(folder.cleanup)
        private_path = Path(folder.name) / "private.pem"
        public_path = Path(folder.name) / "public.txt"
        private_path.write_bytes(self.app_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        public_path.write_bytes(base64.b64encode(self.vendor_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)))
        env = patch.dict(os.environ, {
            "FZU_CHAT_OAUTH_PROVIDERS": "alipay,microsoft,github",
            "FZU_CHAT_ALIPAY_APP_ID": "test-app",
            "FZU_CHAT_ALIPAY_PRIVATE_KEY_FILE": str(private_path),
            "FZU_CHAT_ALIPAY_PUBLIC_KEY_FILE": str(public_path),
            "FZU_CHAT_ALIPAY_REDIRECT_URI": "https://testserver/api/auth/oauth/alipay/callback",
            "FZU_CHAT_ALIPAY_ENABLED": "true",
        })
        env.start()
        self.addCleanup(env.stop)
        for target, value in (("app.oauth.redis_set_json", False), ("app.oauth.redis_pop_json", None), ("app.server.fixed_window_rate_limit", True)):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = TestClient(app, base_url="https://testserver")
        self.subject = "test-openid-" + uuid4().hex
        self.user_id = oauth._visitor_user_id("alipay", self.subject)
        self.addCleanup(delete_user_storage, self.user_id)
        self.addCleanup(invalidate_user_sessions, self.user_id)
        self.addCleanup(self.client.close)

    def signed_response(self, method, payload):
        raw_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        signature = base64.b64encode(self.vendor_key.sign(raw_payload.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
        raw = '{"' + method.replace(".", "_") + '_response":' + raw_payload + ',"sign":' + json.dumps(signature) + '}'
        response = requests.Response()
        response.status_code = 200
        response._content = raw.encode()
        return response

    def start(self):
        response = self.client.get("/api/auth/oauth/alipay/start?accepted_legal=true", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.headers["location"]).query)
        return response, query["state"][0]

    def callback(self, state, client=None, **extra):
        return (client or self.client).get("/api/auth/oauth/alipay/callback", params={
            "auth_code": "one-time-code", "state": state, "app_id": "test-app", **extra,
        }, follow_redirects=False)

    def test_start_and_safe_status(self):
        status = self.client.get("/api/auth/oauth/providers").json()[0]
        self.assertEqual(status, {"provider": "alipay", "label": "支付宝", "configured": True, "enabled": True})
        response, state = self.start()
        url = urlparse(response.headers["location"])
        query = parse_qs(url.query)
        self.assertEqual(url.netloc, "openauth.alipay.com")
        self.assertEqual(query["scope"], ["auth_user"])
        self.assertEqual(query["redirect_uri"], [os.environ["FZU_CHAT_ALIPAY_REDIRECT_URI"]])
        self.assertEqual(self.client.cookies[ALIPAY_STATE_COOKIE], state)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertIn("no-store", response.headers["cache-control"])

    def test_pending_approval_cannot_start(self):
        with patch.dict(os.environ, {"FZU_CHAT_ALIPAY_ENABLED": "false"}):
            status = self.client.get("/api/auth/oauth/providers").json()[0]
            self.assertTrue(status["configured"])
            self.assertFalse(status["enabled"])
            self.assertEqual(self.client.get("/api/auth/oauth/alipay/start?accepted_legal=true").status_code, 503)

    def test_missing_or_invalid_keys_fail_closed(self):
        for value in ("", "/nonexistent-alipay-key"):
            with patch.dict(os.environ, {"FZU_CHAT_ALIPAY_PUBLIC_KEY_FILE": value}):
                self.assertFalse(self.client.get("/api/auth/oauth/providers").json()[0]["configured"])

    def test_legal_consent_required(self):
        self.assertEqual(self.client.get("/api/auth/oauth/alipay/start").status_code, 400)

    def test_browser_binding_rejects_different_browser(self):
        _, state = self.start()
        with TestClient(app, base_url="https://testserver") as other, patch("app.alipay_oauth.requests.post") as post:
            result = self.callback(state, client=other)
        self.assertIn("oauth_error=failed", result.headers["location"])
        post.assert_not_called()
        # The original browser's state was not consumed by the foreign request.
        self.assertIn(state, oauth._memory_states)

    def test_expired_state_rejected(self):
        _, state = self.start()
        payload = oauth._memory_states[state][1]
        oauth._memory_states[state] = (time() - 1, payload)
        with patch("app.alipay_oauth.requests.post") as post:
            self.assertIn("oauth_error=failed", self.callback(state).headers["location"])
        post.assert_not_called()

    def test_mismatched_app_id_rejected(self):
        _, state = self.start()
        with patch("app.alipay_oauth.requests.post") as post:
            self.assertIn("oauth_error=failed", self.callback(state, app_id="other-app").headers["location"])
        post.assert_not_called()

    def test_cancel_consumes_state_and_clears_cookie(self):
        _, state = self.start()
        self.assertIn("oauth_error=cancelled", self.callback(state, error="access_denied").headers["location"])
        self.assertNotIn(state, oauth._memory_states)
        self.assertNotIn(ALIPAY_STATE_COOKIE, self.client.cookies)

    def test_signed_exchange_creates_visitor_without_storing_tokens_and_no_replay(self):
        _, state = self.start()
        responses = [
            self.signed_response("alipay.system.oauth.token", {"access_token": "private-access-token", "refresh_token": "private-refresh-token", "open_id": self.subject}),
            self.signed_response("alipay.user.info.share", {"code": "10000", "open_id": self.subject, "nick_name": '林同学 } "sign":', "avatar": "https://example.org/avatar.png", "mobile": "not-retained"}),
        ]
        with patch("app.alipay_oauth.requests.post", side_effect=responses) as post:
            result = self.callback(state, user_id="attacker", open_id="attacker")
            self.assertEqual(result.headers["location"], "/")
            for call in post.call_args_list:
                data = call.kwargs["data"]
                content = "&".join(f"{key}={value}" for key, value in sorted(data.items()) if key != "sign" and value)
                self.app_key.public_key().verify(base64.b64decode(data["sign"]), content.encode(), padding.PKCS1v15(), hashes.SHA256())
                self.assertEqual(call.args[0], alipay_oauth.GATEWAY_URL)
                self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(post.call_args_list[1].kwargs["data"]["auth_token"], "private-access-token")
            # Replay with the original cookie still fails, proving single-use state.
            self.client.cookies.set(ALIPAY_STATE_COOKIE, state, domain="testserver.local", path="/api/auth/oauth/alipay")
            self.assertIn("oauth_error=failed", self.callback(state).headers["location"])
            self.assertEqual(post.call_count, 2)
        me = self.client.get("/api/auth/me").json()
        self.assertEqual(me["user_id"], self.user_id)
        self.assertEqual(me["auth_provider"], "alipay")
        self.assertEqual(me["student_type"], "visitor")
        self.assertFalse(me["edu_authenticated"])
        from app.auth import get_session
        from app.server import AUTH_COOKIE_NAME
        serialized = json.dumps(get_session(self.client.cookies[AUTH_COOKIE_NAME]))
        for forbidden in ("private-access-token", "private-refresh-token", "not-retained", self.subject):
            self.assertNotIn(forbidden, serialized)

    def test_identity_mismatch_rejected(self):
        _, state = self.start()
        with patch("app.alipay_oauth.requests.post", side_effect=[
            self.signed_response("alipay.system.oauth.token", {"access_token": "token", "open_id": self.subject}),
            self.signed_response("alipay.user.info.share", {"code": "10000", "open_id": "other-user"}),
        ]):
            self.assertIn("oauth_error=failed", self.callback(state).headers["location"])

    def test_legacy_user_id_supported_but_untrusted_avatar_discarded(self):
        config = oauth.get_provider_config("alipay", "https://testserver/api/auth/oauth/alipay/callback")
        with patch("app.alipay_oauth.requests.post", side_effect=[
            self.signed_response("alipay.system.oauth.token", {"access_token": "token", "user_id": self.subject}),
            self.signed_response("alipay.user.info.share", {"code": "10000", "user_id": self.subject, "nick_name": "访客", "avatar": "javascript:alert(1)"}),
        ]):
            profile = oauth.fetch_visitor_profile(config, "code")
        self.assertEqual(profile["user_id"], self.user_id)
        self.assertEqual(profile["avatar_url"], "")
        self.assertEqual(set(profile), {"user_id", "display_name", "avatar_url", "provider_subject_hash"})

    def test_missing_signed_identity_rejected(self):
        config = oauth.get_provider_config("alipay", "")
        with patch("app.alipay_oauth.requests.post", return_value=self.signed_response("alipay.system.oauth.token", {"access_token": "token"})), self.assertRaises(oauth.OAuthError):
            oauth.fetch_visitor_profile(config, "code", {"open_id": "untrusted", "user_id": "untrusted"})

    def test_gateway_redirect_never_followed(self):
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "https://example.org/steal"
        with patch("app.alipay_oauth.requests.post", return_value=response), self.assertRaises(alipay_oauth.AlipayError):
            alipay_oauth.gateway_request("test-app", "alipay.system.oauth.token", {"code": "code"}, self.app_key, self.vendor_key.public_key(), 6)

    def test_response_signature_tamper_and_duplicate_rejected(self):
        method = "alipay.system.oauth.token"
        raw = self.signed_response(method, {"open_id": "original", "access_token": "token"}).text
        for malformed in (raw.replace("original", "forged"), raw[:-1] + ',"sign":"duplicate"}', '{"error_response":{"code":"40002"}}', '{"alipay_system_oauth_token_response":{}}', '[]'):
            with self.subTest(response=malformed[:50]), self.assertRaises(alipay_oauth.AlipayError):
                alipay_oauth.verify_response(malformed, method, self.vendor_key.public_key())

    def test_response_gateway_business_error_and_wrong_method_rejected(self):
        method = "alipay.user.info.share"
        raw = self.signed_response(method, {"code": "40004", "msg": "not allowed"}).text
        for expected in (method, "alipay.system.oauth.token"):
            with self.assertRaises(alipay_oauth.AlipayError):
                alipay_oauth.verify_response(raw, expected, self.vendor_key.public_key())

    def test_redis_consumption_is_atomic(self):
        client = Mock()
        client.getdel.return_value = '{"provider":"alipay"}'
        with patch("app.runtime_state.get_redis_client", return_value=client):
            self.assertEqual(runtime_state.redis_pop_json("test-key"), {"provider": "alipay"})
        client.getdel.assert_called_once_with("test-key")
        client.get.assert_not_called()
        client.delete.assert_not_called()

    def test_access_logs_redact_oauth_query(self):
        record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d', ("ip", "GET", "/api/auth/oauth/alipay/callback?auth_code=secret&state=secret", "1.1", 302), None)
        OAuthAccessLogFilter().filter(record)
        self.assertNotIn("secret", record.getMessage())
        self.assertIn("/api/auth/oauth/alipay/callback", record.getMessage())


if __name__ == "__main__":
    unittest.main()
