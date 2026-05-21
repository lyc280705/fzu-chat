from __future__ import annotations

import unittest
from unittest.mock import patch

from langchain_core.messages import SystemMessage

from app import graph


class ModelThinkingConfigTests(unittest.TestCase):
    def test_qwen_title_model_disables_thinking_at_request_layer(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.TITLE_SUMMARY_MODEL,
                temperature=0.1,
                streaming=False,
                thinking_type="disabled",
                max_tokens=24,
            )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["model"], graph.TITLE_SUMMARY_MODEL)
        self.assertEqual(kwargs["max_tokens"], 24)
        self.assertEqual(kwargs["extra_body"]["thinking"], {"type": "disabled"})
        self.assertEqual(kwargs["extra_body"]["chat_template_kwargs"], {"enable_thinking": False})

    def test_qwen_thinking_toggle_uses_huawei_chat_template_kwargs(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.TITLE_SUMMARY_MODEL,
                temperature=0.4,
                streaming=True,
                thinking_enabled=False,
            )

        extra_body = chat_openai.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body["thinking"], {"type": "disabled"})
        self.assertEqual(extra_body["chat_template_kwargs"], {"enable_thinking": False})

    def test_non_qwen_models_keep_existing_thinking_contract(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.DEFAULT_CHAT_MODEL,
                temperature=0.4,
                streaming=True,
                thinking_enabled=False,
            )

        extra_body = chat_openai.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body, {"thinking": {"type": "disabled"}})

    def test_title_summary_prompt_is_short_and_system_only(self):
        messages = graph.summary_prompt.format_messages(input="user: 今天晚饭去哪吃")

        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], SystemMessage)
        content = messages[0].content
        self.assertIn("聊天标题生成专家", content)
        self.assertIn("晚餐食堂", content)
        self.assertIn("学期成绩", content)
        self.assertIn("无明确任务时输出“问候”", content)
        self.assertIn("user: 今天晚饭去哪吃", content)
        self.assertNotIn("{input}", content)
        self.assertLess(len(content), 320)


if __name__ == "__main__":
    unittest.main()
