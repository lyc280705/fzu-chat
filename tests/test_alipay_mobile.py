from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient

from app import alipay_mobile as bridge, oauth
from app.auth import delete_user_storage, invalidate_user_sessions
from app.server import app, AUTH_COOKIE_NAME, ALIPAY_STATE_COOKIE, _mobile_snapshot

HEADERS = {"Origin": "https://testserver", "X-FZU-Alipay-Mobile": "1"}
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile Safari/604.1"


class AlipayMobileTests(unittest.TestCase):
    def setUp(self):
        self.owner = TestClient(app, base_url="https://testserver", headers=HEADERS)
        self.phone = TestClient(app, base_url="https://testserver", headers=HEADERS)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.phone.close)
        self.profile = oauth._safe_profile("alipay", "test-mobile-" + uuid4().hex, {"nickname": "手机测试用户"})
        self.addCleanup(delete_user_storage, self.profile["user_id"])
        self.addCleanup(invalidate_user_sessions, self.profile["user_id"])
        config = SimpleNamespace(key="alipay", label="支付宝", configured=True, enabled=True,
                                 client_id="test-app", redirect_uri="https://testserver/api/auth/oauth/alipay/callback")
        patches = [
            patch("app.server.get_provider_config", return_value=config),
            patch("app.server.visible_provider_keys", return_value=["alipay"]),
            patch("app.server.fetch_visitor_profile", return_value=self.profile),
            patch("app.server.fixed_window_rate_limit", return_value=True),
            patch("app.oauth.redis_set_json", return_value=False),
            patch("app.oauth.redis_pop_json", return_value=None),
            patch("app.alipay_mobile.get_redis_client", return_value=None),
            patch("app.alipay_mobile.redis_configured", return_value=False),
        ]
        for mocked in patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    def prepare(self):
        response = self.owner.post("/api/auth/oauth/alipay/mobile/prepare", json={"accepted_legal": True, "return_browser": "edge_android"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        landing = parse_qs(urlparse(data["launch_url"]).query)["url"][0]
        self.assertEqual(urlparse(landing).netloc, "openauth.alipay.com")
        self.assertEqual(urlparse(landing).path, "/oauth2/publicAppAuthorize.htm")
        state = parse_qs(urlparse(landing).query)["state"][0]
        self.assertTrue(state.startswith(bridge.DIRECT_STATE_PREFIX))
        self.assertNotIn("alipay_mobile=authorize", landing)
        return data, state

    def legacy_prepare(self):
        # Keep already-issued pre-v7.26 flows supported, without issuing new ones.
        secret, record = bridge.prepare("https://testserver/api/auth/oauth/alipay/callback", "safari")
        self.owner.cookies.set(bridge.OWNER_COOKIE, secret, domain="testserver.local", path=bridge.COOKIE_PATH)
        return _mobile_snapshot(record), record["ticket"]

    def begin(self, data, ticket):
        if ticket.startswith(bridge.DIRECT_STATE_PREFIX):
            self.assertEqual(data["status"], "authorizing")
            self.assertFalse(self.phone.cookies.get(ALIPAY_STATE_COOKIE))
            return ticket
        response = self.phone.post("/api/auth/oauth/alipay/mobile/begin", json={
            "ticket": ticket,
        })
        self.assertEqual(response.status_code, 200, response.text)
        state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
        self.assertEqual(self.phone.cookies[ALIPAY_STATE_COOKIE], state)
        return state

    def callback(self, state, **extra):
        return self.phone.get("/api/auth/oauth/alipay/callback", params={
            "state": state, "auth_code": "test-code", "app_id": "test-app", **extra,
        }, follow_redirects=False)

    def status(self, flow, client=None):
        return (client or self.owner).get("/api/auth/oauth/alipay/mobile/status", params={"flow": flow})

    def ready(self):
        data, ticket = self.prepare()
        state = self.begin(data, ticket)
        response = self.callback(state)
        location = urlparse(response.headers["location"])
        self.assertEqual(location.query, "alipay_mobile=complete")
        completion = parse_qs(location.fragment)
        data["receipt"] = completion["receipt"][0]
        self.assertEqual(completion["flow"][0], data["flow"])
        self.assertEqual(completion["browser"], ["edge_android"])
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        return data

    def test_two_browser_handoff_preserves_state_binding_and_claims_once(self):
        data = self.ready()
        self.assertFalse(self.phone.cookies.get(AUTH_COOKIE_NAME))
        self.assertFalse(self.owner.cookies.get(AUTH_COOKIE_NAME))
        status = self.status(data["flow"]).json()
        self.assertEqual(status["status"], "ready")
        self.assertNotIn("display_name", status)
        self.assertNotIn("receipt", status)
        self.assertNotIn("profile", status)
        self.assertNotIn("user_id", status)
        self.assertNotIn("ticket", status)
        result = self.owner.post("/api/auth/oauth/alipay/mobile/claim", json={"flow": data["flow"], "receipt": data["receipt"]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.owner.get("/api/auth/me").json()["user_id"], self.profile["user_id"])
        self.assertFalse(self.owner.get("/api/auth/me").json()["edu_authenticated"])
        self.assertFalse(self.owner.cookies.get(bridge.OWNER_COOKIE))
        self.assertEqual(self.owner.post("/api/auth/oauth/alipay/mobile/claim", json={"flow": data["flow"], "receipt": data["receipt"]}).status_code, 403)

    def test_foreign_browser_and_ticket_cannot_read_or_claim(self):
        data = self.ready()
        self.assertEqual(self.status(data["flow"], self.phone).status_code, 403)
        self.assertEqual(self.phone.post("/api/auth/oauth/alipay/mobile/claim", json={"flow": data["flow"], "receipt": data["receipt"]}).status_code, 403)

    def test_owner_secret_never_in_launch_or_status_and_is_httponly(self):
        data, _ = self.prepare()
        secret = self.owner.cookies[bridge.OWNER_COOKIE]
        self.assertNotIn(secret, json.dumps(data))
        self.assertNotIn(secret, self.status(data["flow"]).text)
        cookie = next(c for c in self.owner.cookies.jar if c.name == bridge.OWNER_COOKIE)
        self.assertTrue(cookie.secure)
        self.assertIn("HttpOnly", cookie._rest)
        self.assertEqual(cookie._rest["SameSite"], "strict")

    def test_owner_cannot_claim_without_receipt_from_authorizing_device(self):
        data = self.ready()
        # Even the creator of a forwarded/phishing launch link cannot get the
        # victim's profile by polling and claiming with just their own cookie.
        response = self.owner.post("/api/auth/oauth/alipay/mobile/claim", json={"flow": data["flow"], "receipt": "0" * 64})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(data["receipt"], self.status(data["flow"]).text)
        self.assertFalse(self.owner.cookies.get(AUTH_COOKIE_NAME))
        self.assertEqual(self.status(data["flow"]).json()["status"], "ready")
        self.assertEqual(self.owner.post("/api/auth/oauth/alipay/mobile/claim", json={"flow": data["flow"]}).status_code, 422)

    def test_begin_attempts_rate_limited(self):
        data, ticket = self.legacy_prepare()
        with patch("app.server.fixed_window_rate_limit", return_value=False):
            response = self.phone.post("/api/auth/oauth/alipay/mobile/begin", json={"ticket": ticket})
        self.assertEqual(response.status_code, 429)

    def test_launch_is_single_use(self):
        data, ticket = self.legacy_prepare()
        self.begin(data, ticket)
        response = self.phone.post("/api/auth/oauth/alipay/mobile/begin", json={"ticket": ticket})
        self.assertEqual(response.status_code, 409)

    def test_callback_cookie_required_in_alipay_browser(self):
        data, ticket = self.legacy_prepare()
        state = self.begin(data, ticket)
        self.phone.cookies.clear()
        self.assertIn("oauth_error=failed", self.callback(state).headers["location"])
        self.assertEqual(self.status(data["flow"]).json()["status"], "authorizing")

    def test_direct_state_is_consumed_once_without_creating_an_alipay_session(self):
        data, state = self.prepare()
        with patch("app.server.fetch_visitor_profile", return_value=self.profile) as fetch:
            self.assertIn("alipay_mobile=complete", self.callback(state).headers["location"])
            self.assertIn("status=failed", self.callback(state).headers["location"])
            fetch.assert_called_once()
        self.assertFalse(self.phone.cookies.get(AUTH_COOKIE_NAME))
        self.assertEqual(self.status(data["flow"]).json()["status"], "ready")

    def test_forged_direct_namespace_does_not_bypass_cookie_check(self):
        result = self.owner.get("/api/auth/oauth/alipay/start?accepted_legal=true", follow_redirects=False)
        normal_state = parse_qs(urlparse(result.headers["location"]).query)["state"][0]
        with patch("app.server.fetch_visitor_profile") as fetch:
            self.assertIn("status=failed", self.callback(bridge.DIRECT_STATE_PREFIX + normal_state).headers["location"])
            fetch.assert_not_called()
        self.assertIn(normal_state, oauth._memory_states)

    def test_direct_callback_expiry_and_cancel_reject_before_provider_exchange(self):
        data, state = self.prepare()
        with patch("app.server.fetch_visitor_profile") as fetch:
            with patch("app.alipay_mobile.time.time", return_value=data["expires_at"] + 1):
                self.assertIn("status=failed", self.callback(state).headers["location"])
            fetch.assert_not_called()
        self.owner.post("/api/auth/oauth/alipay/mobile/cancel", json={"flow": data["flow"]})
        with patch("app.server.fetch_visitor_profile") as fetch:
            self.assertIn("status=failed", self.callback(state).headers["location"])
            fetch.assert_not_called()

    def test_cancel_and_late_callback_cannot_resurrect_task(self):
        data, ticket = self.prepare()
        state = self.begin(data, ticket)
        secret = self.owner.cookies[bridge.OWNER_COOKIE]
        result = self.owner.post("/api/auth/oauth/alipay/mobile/cancel", json={"flow": data["flow"]})
        self.assertEqual(result.status_code, 200)
        self.assertIn("status=failed", self.callback(state).headers["location"])
        self.assertEqual(bridge.status(secret, data["flow"])["status"], "cancelled")
        with self.assertRaises(bridge.BridgeError):
            bridge.claim(secret, data["flow"], "0" * 64)

    def test_provider_cancellation_reaches_owner(self):
        data, ticket = self.prepare()
        state = self.begin(data, ticket)
        self.assertIn("status=cancelled", self.callback(state, error="access_denied").headers["location"])
        self.assertEqual(self.status(data["flow"]).json()["status"], "cancelled")

    def test_signature_failure_cannot_publish_profile(self):
        data, ticket = self.prepare()
        state = self.begin(data, ticket)
        with patch("app.server.fetch_visitor_profile", side_effect=oauth.OAuthError("验签失败")):
            self.assertIn("status=failed", self.callback(state).headers["location"])
        self.assertEqual(self.status(data["flow"]).json()["status"], "failed")

    def test_reprepare_invalidates_previous_tab(self):
        first, ticket = self.prepare()
        second, _ = self.prepare()
        self.assertNotEqual(first["flow"], second["flow"])
        self.assertEqual(self.status(first["flow"]).status_code, 403)
        with self.assertRaises(bridge.BridgeError):
            bridge.consume_direct_state(ticket)

    def test_expiration_is_not_extended_by_polling(self):
        data, _ = self.prepare()
        secret = self.owner.cookies[bridge.OWNER_COOKIE]
        self.assertEqual(self.status(data["flow"]).json()["expires_at"], data["expires_at"])
        with patch("app.alipay_mobile.time.time", return_value=data["expires_at"] + 1):
            # A normal browser already drops its expired cookie. Force it here
            # to prove the server independently enforces the original expiry.
            response = self.owner.get("/api/auth/oauth/alipay/mobile/status", params={"flow": data["flow"]},
                                      headers={"Cookie": f"{bridge.OWNER_COOKIE}={secret}"})
            self.assertEqual(response.status_code, 410)

    def test_csrf_rejected_even_with_cookie(self):
        data, _ = self.prepare()
        response = self.owner.post("/api/auth/oauth/alipay/mobile/cancel", json={"flow": data["flow"]}, headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        response = self.owner.post("/api/auth/oauth/alipay/mobile/cancel", json={"flow": data["flow"]}, headers={"X-FZU-Alipay-Mobile": ""})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.status(data["flow"]).json()["status"], "authorizing")

    def test_legal_consent_required(self):
        self.assertEqual(self.owner.post("/api/auth/oauth/alipay/mobile/prepare", json={"accepted_legal": False}).status_code, 400)

    def test_return_browser_is_allowlisted(self):
        self.assertEqual(self.owner.post("/api/auth/oauth/alipay/mobile/prepare", json={"accepted_legal": True, "return_browser": "https://evil.example"}).status_code, 422)

    def test_receipt_bound_to_flow_and_revoked_on_cancel(self):
        first = self.ready()
        second = self.ready()
        with self.assertRaises(bridge.BridgeError):
            bridge.claim(self.owner.cookies[bridge.OWNER_COOKIE], second["flow"], first["receipt"])
        secret = self.owner.cookies[bridge.OWNER_COOKIE]
        bridge.cancel(secret, second["flow"])
        with self.assertRaises(bridge.BridgeError):
            bridge.claim(secret, second["flow"], second["receipt"])

    def test_receipt_expires_and_plaintext_never_stored(self):
        data = self.ready()
        secret = self.owner.cookies[bridge.OWNER_COOKIE]
        record = bridge.status(secret, data["flow"])
        self.assertNotIn(data["receipt"], json.dumps(record))
        with patch("app.alipay_mobile.time.time", return_value=data["expires_at"] + 1):
            with self.assertRaises(bridge.BridgeError):
                bridge.claim(secret, data["flow"], data["receipt"])

    def test_mobile_legacy_start_redirects_home_but_in_app_keeps_direct_oauth(self):
        result = self.owner.get("/api/auth/oauth/alipay/start?accepted_legal=true", headers={"User-Agent": MOBILE_UA}, follow_redirects=False)
        self.assertIn("oauth_error=mobile_required", result.headers["location"])
        result = self.phone.get("/api/auth/oauth/alipay/start?accepted_legal=true", headers={"User-Agent": MOBILE_UA + " AlipayClient/10.0"}, follow_redirects=False)
        self.assertEqual(urlparse(result.headers["location"]).netloc, "openauth.alipay.com")

    def test_redis_outage_fails_closed(self):
        with patch("app.alipay_mobile.redis_configured", return_value=True):
            self.assertEqual(self.owner.post("/api/auth/oauth/alipay/mobile/prepare", json={"accepted_legal": True}).status_code, 503)

    def test_concurrent_claim_exactly_once_and_profile_encrypted(self):
        data = self.ready()
        secret = self.owner.cookies[bridge.OWNER_COOKIE]
        stored = bridge._memory[bridge._flow_key(data["flow"])]
        self.assertNotIn(self.profile["user_id"], stored)
        self.assertNotIn(self.profile["display_name"], stored)
        def claim(_):
            try:
                return bridge.claim(secret, data["flow"], data["receipt"])
            except bridge.BridgeError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(x is not None for x in pool.map(claim, range(8))), 1)

    @unittest.skipUnless(os.getenv("FZU_TEST_REDIS_SOCKET"), "isolated Redis socket not configured")
    def test_real_redis_cas_and_encryption(self):
        import redis
        client = redis.Redis(unix_socket_path=os.environ["FZU_TEST_REDIS_SOCKET"], decode_responses=True)
        with patch("app.alipay_mobile.get_redis_client", return_value=client):
            secret, record = bridge.prepare("https://testserver/api/auth/oauth/alipay/callback")
            flow = record["flow"]
            bridge.authorize(flow, "test-state")
            completion = bridge.finish(flow, "test-state", profile=self.profile)
            raw = client.get(bridge._flow_key(flow))
            self.assertNotIn(self.profile["user_id"], raw)
            self.assertTrue(0 < client.ttl(bridge._flow_key(flow)) <= bridge.TTL)
            def claim(_):
                try:
                    return bridge.claim(secret, flow, completion["receipt"])
                except bridge.BridgeError:
                    return None
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(x is not None for x in pool.map(claim, range(8))), 1)
            self.assertEqual(bridge.status(secret, flow)["status"], "consumed")

            _, direct = bridge.prepare("https://testserver/api/auth/oauth/alipay/callback", direct=True)
            def consume(_):
                try:
                    return bridge.consume_direct_state(direct["direct_state"])
                except bridge.BridgeError:
                    return None
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(x is not None for x in pool.map(consume, range(8))), 1)


if __name__ == "__main__":
    unittest.main()
