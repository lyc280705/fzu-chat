from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.server import build_graph_input_messages


class ToolHistoryContextTests(unittest.TestCase):
    def test_completed_tool_parts_are_replayed_to_model_history(self):
        history = build_graph_input_messages(
            [
                {
                    "id": "user-1",
                    "role": "user",
                    "content": "现在去哪吃饭",
                    "parts": [{"type": "text", "content": "现在去哪吃饭"}],
                },
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": "推荐桃李园，离你当前位置更近。",
                    "parts": [
                        {
                            "type": "tool",
                            "tool_id": "tool-1",
                            "tool_name": "recommend_campus_context",
                            "query": "场景：食堂推荐；位置：教工活动中心 / 桃李园",
                            "args": {
                                "scenario": "dining",
                                "manual_location_id": "qishan_staff_center",
                            },
                            "status": "complete",
                            "status_label": "校园推荐已生成",
                            "raw_content": "推荐候选：桃李园。理由：靠近教工活动中心。",
                            "urls": [],
                            "data": {
                                "recommendations": [
                                    {"name": "桃李园", "reason": "靠近教工活动中心"}
                                ]
                            },
                        },
                        {"type": "text", "content": "推荐桃李园，离你当前位置更近。"},
                    ],
                },
            ],
            "glm-5.1",
        )

        self.assertIsInstance(history[0], HumanMessage)
        self.assertIsInstance(history[1], AIMessage)
        self.assertEqual(history[1].tool_calls[0]["name"], "recommend_campus_context")
        self.assertEqual(history[1].tool_calls[0]["args"]["scenario"], "dining")
        self.assertEqual(history[1].tool_calls[0]["args"]["manual_location_id"], "qishan_staff_center")
        self.assertIsInstance(history[2], ToolMessage)
        self.assertEqual(history[2].name, "recommend_campus_context")
        self.assertEqual(history[2].content, "推荐候选：桃李园。理由：靠近教工活动中心。")
        self.assertIsInstance(history[3], AIMessage)
        self.assertEqual(history[3].content, "推荐桃李园，离你当前位置更近。")

    def test_tool_only_assistant_message_is_not_dropped(self):
        history = build_graph_input_messages(
            [
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": "",
                    "parts": [
                        {
                            "type": "tool",
                            "tool_id": "tool-1",
                            "tool_name": "query_courses",
                            "query": "今日课表",
                            "args": {"category": "today"},
                            "status": "complete",
                            "status_label": "课表查询完成",
                            "raw_content": "今日课表：软件工程。",
                            "data": [{"course_name": "软件工程"}],
                        }
                    ],
                }
            ],
            "glm-5.1",
        )

        self.assertEqual(len(history), 2)
        self.assertIsInstance(history[0], AIMessage)
        self.assertEqual(history[0].tool_calls[0]["args"], {"category": "today"})
        self.assertIsInstance(history[1], ToolMessage)
        self.assertEqual(history[1].content, "今日课表：软件工程。")

    def test_legacy_tool_parts_fall_back_to_stable_structured_context(self):
        history = build_graph_input_messages(
            [
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": "",
                    "parts": [
                        {
                            "type": "tool",
                            "tool_id": "tool-1",
                            "tool_name": "query_courses",
                            "query": "今日课表",
                            "status": "complete",
                            "status_label": "课表查询完成",
                            "data": [{"course_name": "软件工程"}],
                        }
                    ],
                }
            ],
            "glm-5.1",
        )

        self.assertEqual(history[0].tool_calls[0]["args"], {"query": "今日课表"})
        self.assertIn("软件工程", history[1].content)


if __name__ == "__main__":
    unittest.main()
