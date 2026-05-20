from __future__ import annotations

import unittest
from unittest.mock import patch

from app import graph


class ModelThinkingConfigTests(unittest.TestCase):
    def test_qwen_title_model_disables_thinking_at_request_layer(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.TITLE_SUMMARY_MODEL,
                temperature=0.1,
                streaming=False,
                thinking_type="disabled",
                max_tokens=40,
            )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["model"], graph.TITLE_SUMMARY_MODEL)
        self.assertEqual(kwargs["max_tokens"], 40)
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


if __name__ == "__main__":
    unittest.main()
