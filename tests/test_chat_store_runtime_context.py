from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.chat_store import ChatStore


class ChatStoreRuntimeContextTests(unittest.TestCase):
    def make_store(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "chat.sqlite"
        store = ChatStore(db_path)
        self.addCleanup(temp_dir.cleanup)
        return store

    def test_runtime_context_is_set_once_without_touching_messages(self):
        store = self.make_store()
        conversation = {
            "id": "conversation-1",
            "title": "新对话",
            "model": "glm-5.1",
            "thread_id": "thread-1",
            "created_at": "2026-05-18T00:00:00+00:00",
            "updated_at": "2026-05-18T00:00:00+00:00",
            "messages": [],
        }
        store.create_conversation("102304226", conversation)
        store.append_message(
            "102304226",
            "conversation-1",
            {
                "id": "message-1",
                "role": "user",
                "content": "你好",
                "timestamp": "2026-05-18T00:01:00+00:00",
                "parts": [{"type": "text", "content": "你好"}],
            },
        )

        first = store.set_runtime_context("102304226", "conversation-1", "runtime-v1")
        second = store.set_runtime_context("102304226", "conversation-1", "runtime-v2")

        self.assertEqual(first["runtime_context"], "runtime-v1")
        self.assertEqual(second["runtime_context"], "runtime-v1")
        self.assertEqual(second["messages"][0]["content"], "你好")

    def test_conversation_page_uses_aggregate_preview_and_cursor(self):
        store = self.make_store()
        for index in range(3):
            conversation_id = f"conversation-{index}"
            timestamp = f"2026-05-18T00:0{index}:00+00:00"
            store.create_conversation(
                "102304226",
                {
                    "id": conversation_id,
                    "title": f"对话{index}",
                    "model": "glm-5.1",
                    "thread_id": f"thread-{index}",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                },
            )
            store.append_message(
                "102304226",
                conversation_id,
                {
                    "id": f"user-{index}",
                    "role": "user",
                    "content": f"问题{index}",
                    "timestamp": timestamp,
                    "parts": [{"type": "text", "content": f"问题{index}"}],
                },
            )
            store.append_message(
                "102304226",
                conversation_id,
                {
                    "id": f"assistant-{index}",
                    "role": "assistant",
                    "content": f"回答{index}",
                    "timestamp": timestamp,
                    "parts": [{"type": "text", "content": f"回答{index}"}],
                },
            )

        first = store.list_conversations_page("102304226", limit=2)
        second = store.list_conversations_page("102304226", limit=2, cursor=first["next_cursor"])

        self.assertEqual([item["id"] for item in first["items"]], ["conversation-2", "conversation-1"])
        self.assertEqual(first["items"][0]["preview"], "回答2")
        self.assertEqual(first["items"][0]["message_count"], 2)
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual([item["id"] for item in second["items"]], ["conversation-0"])
        self.assertIsNone(second["next_cursor"])

    def test_healthcheck_writes_marker(self):
        store = self.make_store()

        result = store.healthcheck()

        self.assertTrue(result["ok"])
        self.assertIn("checked_at", result)


if __name__ == "__main__":
    unittest.main()
