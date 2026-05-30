from __future__ import annotations

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
        response = self.client.get("/api/auth/oauth/providers")

        self.assertEqual(response.status_code, 200)
        providers = response.json()
        self.assertEqual({provider["provider"] for provider in providers}, {"wechat", "qq"})
        for provider in providers:
            self.assertEqual(set(provider.keys()), {"provider", "label", "configured"})

    def test_qq_oauth_callback_creates_visitor_session(self):
        env = {
            **os.environ,
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

    def test_visitor_graph_does_not_build_edu_tools(self):
        self.assertFalse(graph.should_include_edu_tools({"student_type": "visitor"}))

        with patch("app.edu_tools.build_edu_tools", side_effect=AssertionError("visitor should not bind edu tools")):
            graph.build_graph({"student_type": "visitor", "user_id": "visitor_qq_demo"}, use_checkpointer=False)


if __name__ == "__main__":
    unittest.main()
