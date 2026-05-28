from __future__ import annotations

from datetime import datetime
import unittest
from unittest import mock

from app.campus_recommendations import (
    AMapClient,
    AMAP_BICYCLING_URL,
    AMAP_REVERSE_GEOCODE_URL,
    CAMPUS_POIS,
    _choose_scenario,
    _amap_error_message,
    _course_selection_signals,
    _grade_update_signal,
    _meal_period,
    _origin_from_course_event,
    _recent_and_next_class,
    _upcoming_exams,
    build_contextual_recommendation,
    build_campus_recommendation_tools,
    resolve_browser_location_text,
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

    def test_recommendation_tool_uses_message_location_context(self):
        tool = build_campus_recommendation_tools(
            {"message_location": {"lat": 26.0609, "lng": 119.1907, "accuracy": 40}}
        )[0]

        content = tool.invoke({"scenario": "dining"})

        self.assertIn("已使用你本次授权的浏览器定位", content)
        self.assertNotIn("未获得定位", content)

    def test_recommendation_tool_defaults_to_user_selected_travel_mode(self):
        tool = build_campus_recommendation_tools({"travel_mode": "bicycling"})[0]

        with mock.patch("app.campus_recommendations._read_amap_key", return_value=""):
            content = tool.invoke({"scenario": "dining", "manual_location_id": "qishan_center"})

        self.assertIn("| 地点 | 骑行 | 推荐理由 |", content)
        self.assertIn("估算骑行时间", content)

    def test_amap_client_without_key_does_not_call_network(self):
        client = AMapClient(key="")

        self.assertFalse(client.available)
        self.assertIsNone(client.walking_route({"lat": 26.0, "lng": 119.0}, {"lat": 26.1, "lng": 119.1}))
        self.assertEqual(client.around({"lat": 26.0, "lng": 119.0}, "福州大学 食堂", "dining"), [])
        self.assertEqual(client.reverse_geocode({"lat": 26.0, "lng": 119.0}), "")

    def test_amap_error_message_is_localized(self):
        message = _amap_error_message({"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT"})

        self.assertEqual(message, "高德服务访问过于频繁或额度暂时受限")

    def test_amap_client_reverse_geocode_returns_text_location(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "status": "1",
                    "regeocode": {
                        "formatted_address": "福建省福州市闽侯县福州大学旗山校区",
                        "aois": [{"name": "福州大学旗山校区"}],
                        "pois": [{"name": "福州大学图书馆"}],
                    },
                }

        with mock.patch("app.campus_recommendations.requests.get", return_value=FakeResponse()) as get_mock:
            client = AMapClient(key="valid-key", timeout=0.5)
            text = client.reverse_geocode({"lat": 26.060123, "lng": 119.195456})

        self.assertEqual(get_mock.call_args.args[0], AMAP_REVERSE_GEOCODE_URL)
        self.assertEqual(get_mock.call_args.kwargs["params"]["location"], "119.195456,26.060123")
        self.assertIn("福建省福州市闽侯县福州大学旗山校区", text)
        self.assertIn("附近地点：福州大学图书馆", text)
        self.assertNotIn("119.195456", text)
        self.assertNotIn("26.060123", text)

    def test_resolve_browser_location_text_uses_provided_amap_client(self):
        client = mock.Mock()
        client.reverse_geocode.return_value = "福建省福州市福州大学旗山校区"

        text = resolve_browser_location_text({"lat": 26.060123, "lng": 119.195456}, client=client)

        self.assertEqual(text, "福建省福州市福州大学旗山校区")
        client.reverse_geocode.assert_called_once_with({"lat": 26.060123, "lng": 119.195456})

    def test_amap_client_bicycling_route_uses_v4_payload_shape(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "errcode": 0,
                    "errmsg": "OK",
                    "data": {"paths": [{"distance": "480", "duration": "180"}]},
                }

        with mock.patch("app.campus_recommendations.requests.get", return_value=FakeResponse()) as get_mock:
            client = AMapClient(key="valid-key")
            result = client.route({"lat": 26.0, "lng": 119.0}, {"lat": 26.1, "lng": 119.1}, "bicycling")

        self.assertEqual(get_mock.call_args.args[0], AMAP_BICYCLING_URL)
        self.assertEqual(result["distance_m"], 480)
        self.assertEqual(result["duration_min"], 3)
        self.assertEqual(result["mode"], "bicycling")

    def test_recommendation_limits_route_requests(self):
        route_result = {"distance_m": 600, "duration_min": 8, "source": "amap", "mode": "walking", "mode_label": "步行"}
        with (
            mock.patch("app.campus_recommendations._read_amap_key", return_value="valid-key"),
            mock.patch.object(AMapClient, "around", return_value=[]),
            mock.patch.object(AMapClient, "route", return_value=route_result) as route_mock,
        ):
            data = build_contextual_recommendation(
                scenario="dining",
                manual_location_id="qishan_center",
                now=datetime(2026, 5, 17, 18, 10),
            )

        self.assertEqual(data["map_status"], "amap")
        self.assertLessEqual(route_mock.call_count, 4)
        self.assertEqual(data["route_mode"], "walking")

    def test_bicycling_mode_uses_bicycling_routes_and_labels(self):
        route_result = {"distance_m": 480, "duration_min": 3, "source": "amap", "mode": "bicycling", "mode_label": "骑行"}
        with (
            mock.patch("app.campus_recommendations._read_amap_key", return_value="valid-key"),
            mock.patch.object(AMapClient, "around", return_value=[]),
            mock.patch.object(AMapClient, "route", return_value=route_result) as route_mock,
        ):
            data = build_contextual_recommendation(
                scenario="dining",
                manual_location_id="qishan_center",
                travel_mode="bicycling",
                now=datetime(2026, 5, 17, 18, 10),
            )

        self.assertEqual(data["route_mode"], "bicycling")
        self.assertEqual(data["route_mode_label"], "骑行")
        self.assertEqual(route_mock.call_args.args[2], "bicycling")
        self.assertTrue(all(item["travel_mode_label"] == "骑行" for item in data["recommendations"]))
        self.assertTrue(any("骑行约" in item["reason"] for item in data["recommendations"]))

    def test_amap_duplicate_pois_are_replaced_by_unique_supplements(self):
        route_result = {"distance_m": 120, "duration_min": 2, "source": "amap", "mode": "walking", "mode_label": "步行"}
        amap_supplements = [
            {
                "id": "amap_duplicate_taoli",
                "name": "福州大学桃李园餐厅",
                "kind": "dining",
                "campus": "高德周边",
                "lat": 26.062976,
                "lng": 119.196459,
                "tags": ["高德补充"],
                "description": "重复地点",
                "source": "amap_poi",
            },
            {
                "id": "amap_unique_corner",
                "name": "福州大学西门轻食",
                "kind": "dining",
                "campus": "高德周边",
                "lat": 26.0639,
                "lng": 119.1955,
                "tags": ["高德补充"],
                "description": "高德补充地点",
                "source": "amap_poi",
            },
        ]
        with (
            mock.patch("app.campus_recommendations._read_amap_key", return_value="valid-key"),
            mock.patch.object(AMapClient, "around", return_value=amap_supplements),
            mock.patch.object(AMapClient, "route", return_value=route_result) as route_mock,
        ):
            data = build_contextual_recommendation(
                scenario="dining",
                manual_location_id="qishan_center",
                now=datetime(2026, 5, 17, 12, 10),
            )

        names = [item["name"] for item in data["recommendations"]]
        routed_names = [call.args[1]["name"] for call in route_mock.call_args_list]
        self.assertNotIn("福州大学桃李园餐厅", names)
        self.assertNotIn("福州大学桃李园餐厅", routed_names)
        self.assertIn("福州大学西门轻食", routed_names)

    def test_builtin_pois_include_corrected_places(self):
        names = {item["name"] for item in CAMPUS_POIS}

        self.assertIn("桃李园餐厅", names)
        self.assertIn("海棠园餐厅", names)
        self.assertIn("晋江楼学习中心", names)
        self.assertNotIn("教工活动中心公共学习区", names)
        self.assertNotIn("旗山校区创新楼公共学习区", names)

    def test_near_meal_time_counts_as_dining_period(self):
        self.assertEqual(_meal_period(datetime(2026, 5, 18, 8, 25)), "早餐")
        self.assertEqual(_meal_period(datetime(2026, 5, 18, 11, 25)), "午餐")
        self.assertEqual(_meal_period(datetime(2026, 5, 18, 17, 5)), "晚餐")
        self.assertEqual(_meal_period(datetime(2026, 5, 18, 20, 10)), "就餐")

    def test_course_selection_signals_detect_open_and_upcoming_windows(self):
        now = datetime(2026, 5, 17, 10, 0)
        signals = _course_selection_signals(
            {
                "needed_credit_types": [{"category": "人文社科", "missing": "2", "missing_value": 2}],
                "categories": [
                    {
                        "key": "general",
                        "label": "通识选修课",
                        "status": "open",
                        "time_window": {"start": "2026-05-17 08:00", "end": "2026-05-17 18:00"},
                        "candidate_count": 8,
                        "current_course_count": 1,
                        "selected_count": 1,
                    },
                    {
                        "key": "semester",
                        "label": "学期选课",
                        "status": "upcoming",
                        "time_window": {"start": "2026-05-20 12:00", "end": "2026-05-22 12:00"},
                        "candidate_count": 0,
                    },
                ],
            },
            now,
        )

        self.assertEqual(signals[0]["status"], "ending_soon")
        self.assertIn("通识缺口", signals[0]["summary"])
        self.assertTrue(any(signal["status"] == "upcoming" for signal in signals))

    def test_grade_update_signal_uses_digest_without_persisting_scores(self):
        marks = [
            {"semester_code": "202602", "semester": "2025-2026 学年第二学期", "name": "大学英语", "score": "92", "gpa": "4.0", "credits": "2"},
            {"semester_code": "202602", "semester": "2025-2026 学年第二学期", "name": "体育", "score": "成绩尚未录入", "gpa": "", "credits": "1"},
        ]
        baseline = _grade_update_signal(marks)
        changed = _grade_update_signal(marks, seen_grade_digest="old-digest")

        self.assertEqual(baseline["status"], "available")
        self.assertEqual(changed["status"], "changed")
        self.assertEqual(changed["recorded_count"], 1)
        self.assertIn("digest", changed)

    def test_course_location_can_seed_origin_without_browser_location(self):
        origin = _origin_from_course_event({"location": "晋江楼 402"})

        self.assertIsNotNone(origin)
        self.assertEqual(origin["source"], "course")
        self.assertIn("晋江楼", origin["name"])

    def test_study_signal_prefers_learning_center_contextually(self):
        class ClientStub:
            def get_courses(self):
                return []

            def get_exam_rooms(self, _term):
                return {"exams": []}

            def get_course_selection_overview(self):
                return {"categories": [], "needed_credit_types": []}

            def get_marks(self):
                return [
                    {"semester_code": "202602", "semester": "2025-2026 学年第二学期", "name": "大学英语", "score": "92", "gpa": "4.0", "credits": "2"}
                ]

        route_result = {"distance_m": 700, "duration_min": 8, "source": "amap", "mode": "walking", "mode_label": "步行"}
        with (
            mock.patch("app.campus_recommendations._build_client", return_value=ClientStub()),
            mock.patch("app.campus_recommendations._read_amap_key", return_value="valid-key"),
            mock.patch.object(AMapClient, "around", return_value=[]),
            mock.patch.object(AMapClient, "route", return_value=route_result),
        ):
            data = build_contextual_recommendation(
                scenario="auto",
                manual_location_id="qishan_center",
                seen_grade_digest="old-digest",
                edu_session={"edu_authenticated": True},
                now=datetime(2026, 5, 17, 10, 0),
            )

        names = [item["name"] for item in data["recommendations"]]
        self.assertTrue({"晋江楼学习中心", "旗山校区图书馆"}.intersection(names))


if __name__ == "__main__":
    unittest.main()
