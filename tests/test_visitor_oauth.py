from __future__ import annotations

import base64
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app import graph
from app.server import app


class FakeOAuthResponse:
    def __init__(self, payload: dict, text: str | None = None):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class VisitorOAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_provider_status_does_not_expose_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.get("/api/auth/oauth/providers")

        self.assertEqual(response.status_code, 200)
        providers = response.json()
        self.assertEqual(
            {provider["provider"] for provider in providers},
            {"wechat", "qq", "microsoft", "apple", "github"},
        )
        for provider in providers:
            self.assertEqual(set(provider.keys()), {"provider", "label", "configured"})

    def test_provider_status_can_be_limited_for_production(self):
        with patch.dict(os.environ, {"FZU_CHAT_OAUTH_PROVIDERS": "microsoft,apple,github"}, clear=True):
            response = self.client.get("/api/auth/oauth/providers")
            blocked = self.client.get("/api/auth/oauth/qq/start?accepted_legal=true", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([provider["provider"] for provider in response.json()], ["microsoft", "apple", "github"])
        self.assertEqual(blocked.status_code, 404)

    def test_invalid_visible_provider_allowlist_does_not_fall_back_to_all(self):
        with patch.dict(os.environ, {"FZU_CHAT_OAUTH_PROVIDERS": "unknown"}, clear=True):
            response = self.client.get("/api/auth/oauth/providers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_qq_oauth_callback_creates_visitor_session(self):
        env = {
            **os.environ,
            "FZU_CHAT_OAUTH_PROVIDERS": "wechat,qq,microsoft,apple,github",
            "FZU_CHAT_QQ_CLIENT_ID": "qq-client-id",
            "FZU_CHAT_QQ_CLIENT_SECRET": "qq-client-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            start = self.client.get("/api/auth/oauth/qq/start?accepted_legal=true", follow_redirects=False)
            self.assertEqual(start.status_code, 302)
            location = start.headers["location"]
            parsed = urlparse(location)
            self.assertEqual(parsed.netloc, "graph.qq.com")
            state = parse_qs(parsed.query)["state"][0]

            with patch(
                "app.oauth.requests.get",
                side_effect=[
                    FakeOAuthResponse({"access_token": "access-token"}),
                    FakeOAuthResponse({"openid": "openid-1"}),
                    FakeOAuthResponse({"ret": 0, "nickname": "QQ访客", "figureurl_qq_2": "https://q.qlogo.cn/avatar.jpg"}),
                ],
            ):
                callback = self.client.get(f"/api/auth/oauth/qq/callback?code=oauth-code&state={state}", follow_redirects=False)

        self.assertEqual(callback.status_code, 302)
        self.assertEqual(callback.headers["location"], "/")

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        payload = me.json()
        self.assertEqual(payload["student_type"], "visitor")
        self.assertEqual(payload["display_name"], "QQ访客")
        self.assertEqual(payload["auth_provider"], "qq")
        self.assertEqual(payload["avatar_url"], "https://q.qlogo.cn/avatar.jpg")
        self.assertFalse(payload["edu_authenticated"])
        self.assertTrue(payload["user_id"].startswith("visitor_qq_"))

    def test_github_oauth_callback_creates_visitor_session(self):
        env = {
            **os.environ,
            "FZU_CHAT_OAUTH_PROVIDERS": "github",
            "FZU_CHAT_GITHUB_CLIENT_ID": "github-client-id",
            "FZU_CHAT_GITHUB_CLIENT_SECRET": "github-client-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            start = self.client.get("/api/auth/oauth/github/start?accepted_legal=true", follow_redirects=False)
            self.assertEqual(start.status_code, 302)
            parsed = urlparse(start.headers["location"])
            self.assertEqual(parsed.netloc, "github.com")
            self.assertEqual(parsed.path, "/login/oauth/authorize")
            state = parse_qs(parsed.query)["state"][0]

            with patch("app.oauth.requests.post", return_value=FakeOAuthResponse({"access_token": "github-token"})), patch(
                "app.oauth.requests.get",
                return_value=FakeOAuthResponse(
                    {
                        "id": 12345,
                        "login": "octocat",
                        "name": "GitHub 访客",
                        "email": "octocat@example.com",
                        "avatar_url": "https://avatars.githubusercontent.com/u/12345",
                    }
                ),
            ):
                callback = self.client.get(
                    f"/api/auth/oauth/github/callback?code=oauth-code&state={state}",
                    follow_redirects=False,
                )

        self.assertEqual(callback.status_code, 302)
        me = self.client.get("/api/auth/me")
        payload = me.json()
        self.assertEqual(payload["student_type"], "visitor")
        self.assertEqual(payload["display_name"], "GitHub 访客")
        self.assertEqual(payload["auth_provider"], "github")
        self.assertTrue(payload["user_id"].startswith("visitor_github_"))

    def test_apple_form_post_callback_creates_visitor_session(self):
        id_token = _unsigned_jwt({"sub": "apple-subject-1", "email": "apple@example.com"})
        env = {
            **os.environ,
            "FZU_CHAT_OAUTH_PROVIDERS": "apple",
            "FZU_CHAT_APPLE_CLIENT_ID": "apple-service-id",
            "FZU_CHAT_APPLE_CLIENT_SECRET": "apple-client-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            start = self.client.get("/api/auth/oauth/apple/start?accepted_legal=true", follow_redirects=False)
            self.assertEqual(start.status_code, 302)
            parsed = urlparse(start.headers["location"])
            self.assertEqual(parsed.netloc, "appleid.apple.com")
            query = parse_qs(parsed.query)
            self.assertEqual(query["response_mode"], ["form_post"])
            state = query["state"][0]

            with patch("app.oauth.requests.post", return_value=FakeOAuthResponse({"id_token": id_token})):
                callback = self.client.post(
                    "/api/auth/oauth/apple/callback",
                    data={
                        "code": "oauth-code",
                        "state": state,
                        "user": json.dumps({"name": {"firstName": "Ada", "lastName": "Lovelace"}}),
                    },
                    follow_redirects=False,
                )

        self.assertEqual(callback.status_code, 302)
        me = self.client.get("/api/auth/me")
        payload = me.json()
        self.assertEqual(payload["student_type"], "visitor")
        self.assertEqual(payload["display_name"], "Ada Lovelace")
        self.assertEqual(payload["auth_provider"], "apple")
        self.assertTrue(payload["user_id"].startswith("visitor_apple_"))

    def test_microsoft_oauth_start_uses_oidc_scopes(self):
        env = {
            **os.environ,
            "FZU_CHAT_OAUTH_PROVIDERS": "microsoft",
            "FZU_CHAT_MICROSOFT_CLIENT_ID": "microsoft-client-id",
            "FZU_CHAT_MICROSOFT_CLIENT_SECRET": "microsoft-client-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            start = self.client.get("/api/auth/oauth/microsoft/start?accepted_legal=true", follow_redirects=False)

        self.assertEqual(start.status_code, 302)
        parsed = urlparse(start.headers["location"])
        self.assertEqual(parsed.netloc, "login.microsoftonline.com")
        self.assertEqual(parsed.path, "/common/oauth2/v2.0/authorize")
        self.assertEqual(parse_qs(parsed.query)["scope"], ["openid profile email"])

    def test_visitor_graph_does_not_build_edu_tools(self):
        self.assertFalse(graph.should_include_edu_tools({"student_type": "visitor"}))

        with patch("app.edu_tools.build_edu_tools", side_effect=AssertionError("visitor should not bind edu tools")):
            graph.build_graph({"student_type": "visitor", "user_id": "visitor_qq_demo"}, use_checkpointer=False)


def _unsigned_jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def encode(part: dict) -> str:
        raw = json.dumps(part, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode(header)}.{encode(payload)}."


if __name__ == "__main__":
    unittest.main()
