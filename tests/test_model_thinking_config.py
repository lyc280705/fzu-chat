from __future__ import annotations

import unittest
from inspect import signature
from unittest.mock import patch

from langchain_core.messages import SystemMessage

from app import graph


class ModelReasoningConfigTests(unittest.TestCase):
    def test_chat_llm_no_longer_accepts_stop_sequences(self):
        self.assertNotIn("stop", signature(graph.build_chat_llm).parameters)

    def test_model_menu_order(self):
        self.assertEqual(
            list(graph.CHAT_MODEL_OPTIONS),
            [graph.DEFAULT_CHAT_MODEL, graph.DEEPSEEK_CHAT_MODEL, graph.KIMI_CHAT_MODEL],
        )

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

    def test_glm_reasoning_effort_enables_thinking(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.DEFAULT_CHAT_MODEL,
                temperature=0.4,
                streaming=True,
                reasoning_effort="low",
            )

        extra_body = chat_openai.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body["thinking"], {"type": "enabled"})
        self.assertEqual(extra_body["reasoning_effort"], "low")

    def test_deepseek_only_uses_supported_reasoning_efforts(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.DEEPSEEK_CHAT_MODEL,
                temperature=0.4,
                streaming=True,
                reasoning_effort="low",
            )

        extra_body = chat_openai.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body, {"chat_template_kwargs": {"thinking": True, "reasoning_effort": "low"}})
        self.assertEqual(chat_openai.call_args.kwargs["base_url"], "https://api.modelarts-maas.com/v2")
        self.assertNotIn("temperature", chat_openai.call_args.kwargs)

    def test_deepseek_can_disable_thinking(self):
        self.assertEqual(
            graph.build_reasoning_config("disabled", graph.DEEPSEEK_CHAT_MODEL),
            {"chat_template_kwargs": {"thinking": False}},
        )

    def test_deepseek_does_not_advertise_a_separate_medium_level(self):
        for effort in ("medium", "invalid", None):
            with self.subTest(effort=effort):
                self.assertEqual(
                    graph.build_reasoning_config(effort, graph.DEEPSEEK_CHAT_MODEL),
                    {"chat_template_kwargs": {"thinking": True, "reasoning_effort": "high"}},
                )

    def test_kimi_slider_maps_to_thinking_control(self):
        with patch("app.graph.ChatOpenAI") as chat_openai:
            graph.build_chat_llm(
                graph.KIMI_CHAT_MODEL,
                temperature=0.4,
                streaming=True,
                reasoning_effort="disabled",
            )

        extra_body = chat_openai.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body, {"thinking": {"type": "disabled"}})

    def test_reasoning_controls_match_each_model_capability(self):
        self.assertEqual(
            [option["value"] for option in graph.MODEL_REASONING_CONTROLS[graph.DEFAULT_CHAT_MODEL]["options"]],
            ["low", "high", "max"],
        )
        self.assertEqual(
            [option["value"] for option in graph.MODEL_REASONING_CONTROLS[graph.KIMI_CHAT_MODEL]["options"]],
            ["disabled", "enabled"],
        )
        self.assertEqual(
            [option["value"] for option in graph.MODEL_REASONING_CONTROLS[graph.DEEPSEEK_CHAT_MODEL]["options"]],
            ["disabled", "low", "high", "max"],
        )

    def test_title_summary_prompt_keeps_title_rules_in_one_system_message(self):
        messages = graph.summary_prompt.format_messages(input="user: 今天晚饭去哪吃")

        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], SystemMessage)
        content = messages[0].content
        self.assertIn("聊天会话标题生成器", content)
        self.assertIn("核心意图 + 核心对象", content)
        self.assertIn("记录、比较、修改、创建、排查、推荐、总结", content)
        self.assertIn("文件名、数字、错误码和缩写", content)
        self.assertIn("中文标题通常 4～12 个汉字", content)
        self.assertIn("最多 18 个汉字", content)
        self.assertIn("简单问候", content)
        self.assertIn("请求：", content)
        self.assertIn("标题：", content)
        self.assertIn("user: 今天晚饭去哪吃", content)
        self.assertNotIn("{input}", content)
        self.assertIn("只输出最终标题", content)


if __name__ == "__main__":
    unittest.main()
