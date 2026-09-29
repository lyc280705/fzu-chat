from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import anyio.to_thread
from fastapi.testclient import TestClient
import httpx
import openai

from app import auth, graph, model_pacing, server
from app.chat_store import ChatStore
from app.model_pacing import AsyncPacedTransport, ModelQueueFull, PacedTransport, RequestPacer

URL = "https://maas.example/openai/v1/chat/completions"


def chat_request(model="glm-5.3"):
    return httpx.Request("POST", URL, content=json.dumps({"model": model, "messages": []}).encode())


class ScriptedTransport(httpx.BaseTransport):
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def handle_request(self, request):
        self.calls += 1
        return httpx.Response(self.statuses.pop(0), json={}, request=request)


class AsyncScriptedTransport(httpx.AsyncBaseTransport):
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        return httpx.Response(self.statuses.pop(0), json={}, request=request)


class RequestPacerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(model_pacing, "LIMIT_SAFETY", 1.0))

    def test_spaces_requests_at_rpm_per_model(self):
        pacer = RequestPacer({"glm-5.3": (120, 10**9)}, default_limit=(60, 10**9), max_wait=10)
        with patch("app.model_pacing.time.monotonic", return_value=100.0):
            delays = [pacer.reserve("glm-5.3") for _ in range(3)]
            other = pacer.reserve("deepseek-v4.1-flash")
            other_next = pacer.reserve("deepseek-v4.1-flash")

        self.assertEqual(delays, [0.0, 0.5, 1.0])
        self.assertEqual(other, 0.0)
        self.assertEqual(other_next, 1.0)

    def test_official_limits_stay_under_rpm_and_burst_limit(self):
        rpm, tpm = model_pacing.MODEL_LIMITS["glm-5.3"]
        self.assertEqual((rpm, tpm), (100.0, 1_000_000.0))
        self.assertEqual(model_pacing.MODEL_LIMITS["deepseek-v4.1-flash"], (100.0, 1_000_000.0))
        pacer = RequestPacer(model_pacing.MODEL_LIMITS, model_pacing.DEFAULT_LIMIT, max_wait=120)
        with patch.object(model_pacing, "LIMIT_SAFETY", 0.95), patch("app.model_pacing.time.monotonic", return_value=0.0):
            starts = [pacer.reserve("glm-5.3", tokens=5000) for _ in range(120)]

        self.assertLessEqual(sum(1 for start in starts if start < 60), 100)
        self.assertLessEqual(max(sum(1 for start in starts if second <= start < second + 1) for second in range(60)), 4)

    def test_large_requests_wait_for_tpm(self):
        pacer = RequestPacer({"glm-5.3": (6000, 60_000)}, default_limit=(60, 10**9), max_wait=100)
        with patch.object(model_pacing, "TOKEN_BURST_SECONDS", 0.0), patch("app.model_pacing.time.monotonic", return_value=0.0):
            first = pacer.reserve("glm-5.3", tokens=10_000)
            second = pacer.reserve("glm-5.3", tokens=10_000)

        self.assertEqual(first, 0.0)
        self.assertAlmostEqual(second, 10.0)

    def test_rejects_when_queue_is_too_long(self):
        pacer = RequestPacer({"glm-5.3": (60, 10**9)}, default_limit=(60, 10**9), max_wait=2)
        with patch("app.model_pacing.time.monotonic", return_value=0.0):
            for _ in range(3):
                pacer.reserve("glm-5.3")
            with self.assertRaises(ModelQueueFull):
                pacer.reserve("glm-5.3")

    def test_parses_limit_overrides(self):
        self.assertEqual(
            model_pacing._parse_limits("glm-5.3=100/1000000, kimi-k2.6=48/500000,bad,zero=0/5"),
            {"glm-5.3": (100.0, 1_000_000.0), "kimi-k2.6": (48.0, 500_000.0)},
        )

    def test_estimates_request_tokens(self):
        content = json.dumps({"model": "glm-5.3", "messages": [{"role": "user", "content": "图书馆几点开门"}], "max_tokens": 30})
        model, tokens = model_pacing._request_model(httpx.Request("POST", URL, content=content.encode()))

        self.assertEqual(model, "glm-5.3")
        self.assertGreater(tokens, 30)
        self.assertLess(tokens, 200)


class PacedTransportTests(unittest.TestCase):
    def setUp(self):
        self.pacer = RequestPacer({}, default_limit=(60_000, 10**12), max_wait=5)
        self.enterContext(patch.object(model_pacing, "pacer", self.pacer))
        self.enterContext(patch("app.model_pacing.time.sleep"))

    def test_retries_provider_rate_limits(self):
        inner = ScriptedTransport([429, 429, 200])
        response = PacedTransport(inner).handle_request(chat_request())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(inner.calls, 3)

    def test_gives_up_after_configured_retries(self):
        with patch.object(model_pacing, "RATE_LIMIT_RETRIES", 1):
            inner = ScriptedTransport([429, 429, 200])
            response = PacedTransport(inner).handle_request(chat_request())

        self.assertEqual(response.status_code, 429)
        self.assertEqual(inner.calls, 2)

    def test_queue_full_is_a_local_non_retryable_429(self):
        inner = ScriptedTransport([200])
        with patch.object(self.pacer, "reserve", side_effect=ModelQueueFull("glm-5.3")):
            response = PacedTransport(inner).handle_request(chat_request())

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["x-should-retry"], "false")
        self.assertEqual(response.json()["error"]["code"], model_pacing.QUEUE_FULL_CODE)
        self.assertEqual(inner.calls, 0)

    def test_other_requests_are_not_paced(self):
        inner = ScriptedTransport([429])
        with patch.object(self.pacer, "reserve", side_effect=AssertionError("must not pace")):
            response = PacedTransport(inner).handle_request(httpx.Request("GET", "https://maas.example/openai/v1/models"))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(inner.calls, 1)

    def test_async_transport_retries_provider_rate_limits(self):
        inner = AsyncScriptedTransport([429, 200])
        with patch.object(model_pacing, "_retry_delay", return_value=0):
            response = asyncio.run(AsyncPacedTransport(inner).handle_async_request(chat_request()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(inner.calls, 2)


class ChatClientWiringTests(unittest.TestCase):
    def test_chat_models_share_the_paced_clients(self):
        sync_client, async_client = model_pacing.model_http_clients()
        llm = graph.build_chat_llm("glm-5.3", temperature=0.2, streaming=True)
        title_llm = graph.build_chat_llm(graph.TITLE_SUMMARY_MODEL, temperature=0.1, streaming=False)

        for model in (llm, title_llm):
            self.assertIs(model.http_client, sync_client)
            self.assertIs(model.http_async_client, async_client)
        self.assertIsInstance(sync_client._transport, PacedTransport)
        self.assertIsInstance(async_client._transport, AsyncPacedTransport)


class FailingGraph:
    def __init__(self, exc):
        self.exc = exc

    async def astream(self, *args, **kwargs):
        raise self.exc
        yield  # pragma: no cover


class BusyStreamTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (("_sessions", {}), ("_edu_sessions", {}), ("USERS_DIR", Path(directory.name))):
            self.enterContext(patch.object(auth, name, value))
        for name in ("get_redis_client", "redis_get_json", "redis_set_json", "redis_delete"):
            self.enterContext(patch.object(auth, name, return_value=None if name != "redis_delete" else False))
        self.enterContext(patch.object(auth, "redis_configured", return_value=False))
        self.store = ChatStore(Path(directory.name) / "chat.sqlite")
        self.enterContext(patch.object(server, "chat_store", self.store))
        for name in ("warm_teaching_week_cache_async", "schedule_signal_snapshot_refresh"):
            self.enterContext(patch.object(server, name))
        self.enterContext(patch.object(server, "build_dynamic_campus_context", return_value=""))
        self.enterContext(patch.object(server, "build_runtime_system_context", return_value=""))
        self.enterContext(patch.object(server, "refresh_edu_session_status", side_effect=auth.get_session))
        self.user_id = f"visitor_test_{uuid4().hex}"
        token = auth.create_session(self.user_id, student_type="visitor")
        self.client = TestClient(server.app)
        self.client.cookies.set("fzu_session", token, domain="testserver.local", path="/")
        now = datetime.now(timezone.utc).isoformat()
        self.cid = str(uuid4())
        self.store.create_conversation(self.user_id, {
            "id": self.cid, "title": "新对话", "model": "glm-5.3", "thread_id": str(uuid4()),
            "created_at": now, "updated_at": now,
        })

    def send(self, exc):
        with patch.object(server, "build_graph", return_value=FailingGraph(exc)):
            response = self.client.post(f"/api/conversations/{self.cid}/messages", json={"content": "图书馆几点开门？"})
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_rate_limit_shows_busy_message(self):
        response = httpx.Response(429, request=httpx.Request("POST", URL))
        body = self.send(openai.RateLimitError("Too many requests", response=response, body=None))

        self.assertIn("event: error", body)
        self.assertIn("当前使用人数较多", body)

    def test_other_failures_keep_generic_message(self):
        body = self.send(RuntimeError("boom"))

        self.assertIn("暂时无法生成回复", body)
        self.assertNotIn("当前使用人数较多", body)


class EduLoginSlotTests(unittest.TestCase):
    def test_waits_for_a_free_slot(self):
        lease = object()
        with patch.object(server, "acquire_slot", side_effect=[None, None, lease]) as acquire, \
                patch("app.server.time.sleep") as sleep:
            self.assertIs(server._acquire_edu_login_slot(), lease)

        self.assertEqual(acquire.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_gives_up_after_wait_window(self):
        with patch.object(server, "EDU_LOGIN_SLOT_WAIT_SECONDS", 0.0), \
                patch.object(server, "acquire_slot", return_value=None) as acquire:
            self.assertIsNone(server._acquire_edu_login_slot())

        acquire.assert_called_once()


class WorkerThreadTests(unittest.TestCase):
    def test_lifespan_enlarges_thread_pools(self):
        seen = {}

        async def probe():
            seen["workers"] = asyncio.get_running_loop()._default_executor._max_workers
            seen["tokens"] = anyio.to_thread.current_default_thread_limiter().total_tokens
            return {}

        # Ahead of the SPA catch-all route.
        server.app.add_api_route("/__test_executor", probe, methods=["GET"])
        route = server.app.router.routes.pop()
        server.app.router.routes.insert(0, route)
        self.addCleanup(server.app.router.routes.remove, route)
        with patch.object(server, "migrate_legacy_sessions"), patch.object(server, "warm_teaching_week_cache_async"):
            with TestClient(server.app) as client:
                client.get("/__test_executor")

        self.assertEqual(seen["workers"], server.WORKER_THREADS)
        self.assertEqual(seen["tokens"], server.SYNC_ENDPOINT_THREADS)


class DefaultModelSplitTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (("_sessions", {}), ("_edu_sessions", {}), ("USERS_DIR", Path(directory.name))):
            self.enterContext(patch.object(auth, name, value))
        for name in ("get_redis_client", "redis_get_json", "redis_set_json", "redis_delete"):
            self.enterContext(patch.object(auth, name, return_value=None if name != "redis_delete" else False))
        self.enterContext(patch.object(auth, "redis_configured", return_value=False))
        self.store = ChatStore(Path(directory.name) / "chat.sqlite")
        self.enterContext(patch.object(server, "chat_store", self.store))
        self.enterContext(patch.object(server, "DEFAULT_MODEL_ROTATION", ["glm-5.3", "deepseek-v4.1-flash"]))

    def client_for(self, user_id):
        client = TestClient(server.app)
        client.cookies.set("fzu_session", auth.create_session(user_id, student_type="visitor"), domain="testserver.local", path="/")
        return client

    def test_users_are_split_about_evenly_and_stably(self):
        counts = {}
        for index in range(400):
            model = server.default_model_for_user(f"visitor_{index}")
            counts[model] = counts.get(model, 0) + 1
            self.assertEqual(server.default_model_for_user(f"visitor_{index}"), model)

        self.assertEqual(set(counts), {"glm-5.3", "deepseek-v4.1-flash"})
        self.assertTrue(160 <= counts["deepseek-v4.1-flash"] <= 240, counts)

    def test_models_list_and_new_conversation_use_the_users_default(self):
        seen = set()
        for index in range(20):
            user_id = f"visitor_split_{index}"
            expected = server.default_model_for_user(user_id)
            client = self.client_for(user_id)
            models = client.get("/api/models").json()
            created = client.post("/api/conversations", json={}).json()

            self.assertEqual(models[0]["id"], expected)
            self.assertEqual(sorted(model["id"] for model in models), sorted(server.MODEL_OPTIONS))
            self.assertEqual(created["model"], expected)
            seen.add(expected)
        self.assertEqual(seen, {"glm-5.3", "deepseek-v4.1-flash"})

    def test_explicit_model_choice_is_kept(self):
        user_id = next(f"visitor_pick_{i}" for i in range(100) if server.default_model_for_user(f"visitor_pick_{i}") == "deepseek-v4.1-flash")
        created = self.client_for(user_id).post("/api/conversations", json={"model": "glm-5.3"}).json()

        self.assertEqual(created["model"], "glm-5.3")

    def test_empty_rotation_uses_the_default_model(self):
        with patch.object(server, "DEFAULT_MODEL_ROTATION", []):
            self.assertEqual(server.default_model_for_user("visitor_any"), server.DEFAULT_CHAT_MODEL)


if __name__ == "__main__":
    unittest.main()
