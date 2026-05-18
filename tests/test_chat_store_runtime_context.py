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


if __name__ == "__main__":
    unittest.main()
