from __future__ import annotations

import unittest

from app.server import build_title_summary_transcript


class TitleSummaryContextTests(unittest.TestCase):
    def test_title_transcript_keeps_user_requests_only(self):
        transcript = build_title_summary_transcript(
            [
                {"role": "user", "content": "你好"},
                {
                    "role": "assistant",
                    "content": "你好呀！我是福大灵犀，很高兴能和你聊天呢！",
                },
                {"role": "user", "content": "今天晚饭去哪吃"},
            ]
        )

        self.assertEqual(transcript, "user: 你好\nuser: 今天晚饭去哪吃")
        self.assertNotIn("你好呀", transcript)
        self.assertNotIn("福大灵犀", transcript)

    def test_empty_title_transcript_stays_empty(self):
        transcript = build_title_summary_transcript(
            [
                {"role": "assistant", "content": "可以帮你查课表。"},
                {"role": "user", "content": "   "},
            ]
        )

        self.assertEqual(transcript, "")


if __name__ == "__main__":
    unittest.main()
