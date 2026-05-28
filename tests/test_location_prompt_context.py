from __future__ import annotations

import unittest

from app.graph import append_runtime_system_context, build_transient_location_system_context


class LocationPromptContextTests(unittest.TestCase):
    def test_transient_location_context_uses_text_not_coordinates(self):
        context = build_transient_location_system_context(
            "福建省福州市闽侯县福州大学旗山校区；附近地点：福州大学图书馆 119.195456,26.060123"
        )

        self.assertIn("高德地图逆地理编码文字", context)
        self.assertIn("用户当前位置文字", context)
        self.assertIn("福州大学图书馆", context)
        self.assertIn("不要写入长期记忆", context)
        self.assertNotIn("119.195456", context)
        self.assertNotIn("26.060123", context)

    def test_runtime_context_append_keeps_transient_location_separate(self):
        runtime = "运行时上下文（短生命周期信息；仅供本次回答参考，不要写入长期记忆）："
        location = build_transient_location_system_context("福建省福州市闽侯县福州大学旗山校区")

        combined = append_runtime_system_context(runtime, location)

        self.assertIn(runtime, combined)
        self.assertIn("福建省福州市闽侯县福州大学旗山校区", combined)
        self.assertIn("\n\n", combined)


if __name__ == "__main__":
    unittest.main()
