from __future__ import annotations

from datetime import datetime
import unittest
from unittest import mock

from app.campus_recommendations import (
    AMapClient,
    _choose_scenario,
    _amap_error_message,
    _recent_and_next_class,
    _upcoming_exams,
    build_contextual_recommendation,
)


class CampusRecommendationTests(unittest.TestCase):
    def test_recent_class_detection(self):
        now = datetime(2026, 5, 18, 12, 20)
        courses = [
            {
                "name": "高等数学",
                "time": "周一 第3-4节",
                "location": "旗山教学楼",
            }
        ]

        recent, next_class = _recent_and_next_class(courses, now)

        self.assertIsNotNone(recent)
        self.assertEqual(recent["name"], "高等数学")
        self.assertEqual(recent["location"], "旗山教学楼")
        self.assertIsNone(next_class)

    def test_upcoming_exam_within_seven_days(self):
        now = datetime(2026, 5, 17, 10, 0)
        exams = _upcoming_exams(
            {
                "exams": [
                    {"course_name": "线性代数", "date": "2026-05-20", "time": "09:00", "location": "西三"},
                    {"course_name": "大学物理", "date": "2026-05-30", "time": "14:00", "location": "西二"},
                ]
            },
            now,
        )

        self.assertEqual(len(exams), 1)
        self.assertEqual(exams[0]["course_name"], "线性代数")
        self.assertEqual(exams[0]["days_until"], 3)
        self.assertEqual(_choose_scenario("auto", None, None, exams, now), "study")

    def test_missing_amap_key_uses_builtin_estimates(self):
        with mock.patch("app.campus_recommendations._read_amap_key", return_value=""):
            data = build_contextual_recommendation(
                scenario="dining",
                manual_location_id="qishan_center",
                now=datetime(2026, 5, 17, 12, 10),
            )

        self.assertEqual(data["resolved_scenario"], "dining")
        self.assertEqual(data["location_source"], "manual")
        self.assertEqual(data["map_status"], "estimated")
        self.assertGreaterEqual(len(data["recommendations"]), 1)
        self.assertIn("未配置高德地图 Key", data["map_note"])
        self.assertNotIn("lat", data)
        self.assertNotIn("lng", data)

    def test_amap_client_without_key_does_not_call_network(self):
        client = AMapClient(key="")

        self.assertFalse(client.available)
        self.assertIsNone(client.walking_route({"lat": 26.0, "lng": 119.0}, {"lat": 26.1, "lng": 119.1}))
        self.assertEqual(client.around({"lat": 26.0, "lng": 119.0}, "福州大学 食堂", "dining"), [])

    def test_amap_error_message_is_localized(self):
        message = _amap_error_message({"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT"})

        self.assertEqual(message, "高德服务访问过于频繁或额度暂时受限")

    def test_recommendation_limits_walking_route_requests(self):
        route_result = {"distance_m": 600, "duration_min": 8, "source": "amap"}
        with (
            mock.patch("app.campus_recommendations._read_amap_key", return_value="valid-key"),
            mock.patch.object(AMapClient, "around", return_value=[]),
            mock.patch.object(AMapClient, "walking_route", return_value=route_result) as route_mock,
        ):
            data = build_contextual_recommendation(
                scenario="dining",
                manual_location_id="qishan_center",
                now=datetime(2026, 5, 17, 18, 10),
            )

        self.assertEqual(data["map_status"], "amap")
        self.assertLessEqual(route_mock.call_count, 4)


if __name__ == "__main__":
    unittest.main()
