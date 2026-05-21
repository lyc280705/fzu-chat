from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest import mock

from app import server


class SummaryChainStub:
    def __init__(self, result: str):
        self.result = result
        self.calls = []

    async def ainvoke(self, payload, config=None):
        self.calls.append({"payload": payload, "config": config})
        return self.result


class TitleSummaryTracingTests(unittest.IsolatedAsyncioTestCase):
    async def test_title_summary_uses_explicit_langsmith_trace_config(self):
        chain = SummaryChainStub("晚餐安排")
        context_calls = []

        @contextmanager
        def fake_tracing_context(**kwargs):
            context_calls.append(kwargs)
            yield

        messages = [
            {"role": "user", "content": "晚上去哪吃饭"},
            {"role": "assistant", "content": "可以按当前位置推荐附近食堂。"},
        ]

        with (
            mock.patch.object(server, "summary_chain", chain),
            mock.patch.object(server, "LANGSMITH_TRACING_ENABLED", True),
            mock.patch.object(server, "tracing_context", fake_tracing_context),
        ):
            title = await server.summarize_title(
                messages,
                user_id="102304226",
                conversation_id="conversation-1",
            )

        self.assertEqual(title, "晚餐安排")
        self.assertEqual(len(chain.calls), 1)
        self.assertIn("晚上去哪吃饭", chain.calls[0]["payload"]["input"])
        config = chain.calls[0]["config"]
        self.assertEqual(config["run_name"], server.TITLE_SUMMARY_TRACE_RUN_NAME)
        self.assertEqual(config["tags"], server.TITLE_SUMMARY_TRACE_TAGS)
        self.assertEqual(config["metadata"]["component"], "conversation_title_update")
        self.assertEqual(config["metadata"]["model"], server.TITLE_SUMMARY_MODEL)
        self.assertEqual(config["metadata"]["conversation_id"], "conversation-1")
        self.assertEqual(config["metadata"]["user_id"], "10***26")
        self.assertEqual(context_calls[0]["enabled"], True)
        self.assertEqual(context_calls[0]["tags"], server.TITLE_SUMMARY_TRACE_TAGS)
        self.assertEqual(context_calls[0]["metadata"], config["metadata"])


if __name__ == "__main__":
    unittest.main()
