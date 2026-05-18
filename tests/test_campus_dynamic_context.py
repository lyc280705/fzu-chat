from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from app import campus_dynamic_context as dynamic


class CampusDynamicContextTests(unittest.TestCase):
    def make_store(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "dynamic.sqlite"
        store = dynamic.CampusDynamicContextStore(db_path)
        self.addCleanup(temp_dir.cleanup)
        return store

    def test_no_snapshot_returns_quick_empty_context(self):
        store = self.make_store()
        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            started = time.monotonic()
            context = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="你好",
                is_first_user_turn=True,
            )

        self.assertEqual(context, "")
        self.assertLess((time.monotonic() - started) * 1000, 100)

    def test_exam_event_is_suppressed_after_first_injection(self):
        store = self.make_store()
        store.upsert_snapshot(
            "102304226",
            "exam",
            {
                "digest": "exam-digest",
                "count": 1,
                "upcoming": [
                    {
                        "course_name": "线性代数",
                        "date": "2026-05-20",
                        "time": "09:00-11:00",
                        "days_until": 1,
                    }
                ],
            },
            timedelta(days=2),
        )

        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            first = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="你好",
                is_first_user_turn=True,
                now=datetime(2026, 5, 19, 10, 0),
            )
            second = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="你好",
                is_first_user_turn=True,
                now=datetime(2026, 5, 19, 10, 1),
            )

        self.assertIn("线性代数", first)
        self.assertEqual(second, "")

    def test_exam_event_can_reinject_next_day(self):
        store = self.make_store()
        store.upsert_snapshot(
            "102304226",
            "exam",
            {
                "digest": "exam-digest",
                "count": 1,
                "upcoming": [
                    {
                        "course_name": "线性代数",
                        "date": "2026-05-21",
                        "time": "09:00-11:00",
                        "days_until": 3,
                    }
                ],
            },
            timedelta(days=2),
        )

        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            first = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="你好",
                is_first_user_turn=True,
                now=datetime(2026, 5, 18, 10, 0),
            )
            next_day = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="今天有什么需要注意的吗？",
                is_first_user_turn=False,
                now=datetime(2026, 5, 19, 10, 1),
            )

        self.assertIn("线性代数", first)
        self.assertIn("线性代数", next_day)

    def test_non_first_unrelated_message_does_not_inject(self):
        store = self.make_store()
        store.upsert_snapshot(
            "102304226",
            "selection",
            {
                "digest": "selection-digest",
                "signals": [
                    {
                        "title": "通识选修课正在进行",
                        "summary": "通识选修课已开放。",
                        "priority": 88,
                        "status": "open",
                        "category": "general",
                        "time_window": {"end": "2026-05-20 18:00"},
                    }
                ],
            },
            timedelta(minutes=15),
        )

        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            context = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="福州大学校训是什么",
                is_first_user_turn=False,
            )

        self.assertEqual(context, "")

    def test_non_first_attention_request_can_inject_cached_event(self):
        store = self.make_store()
        store.upsert_snapshot(
            "102304226",
            "exam",
            {
                "digest": "exam-digest",
                "count": 1,
                "upcoming": [
                    {
                        "course_name": "可穿戴传感器",
                        "date": "2026-05-21",
                        "time": "09:00-11:00",
                        "days_until": 3,
                    }
                ],
            },
            timedelta(minutes=30),
        )

        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            started = time.monotonic()
            context = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="今天有什么我需要注意的吗？",
                is_first_user_turn=False,
                now=datetime(2026, 5, 18, 12, 0),
            )

        self.assertIn("可穿戴传感器", context)
        self.assertLess((time.monotonic() - started) * 1000, 100)

    def test_meal_period_snapshot_can_inject_dining_hint(self):
        store = self.make_store()
        store.upsert_snapshot(
            "102304226",
            "course",
            {"digest": "no-class", "recent_class": None, "next_class": None},
            timedelta(minutes=30),
        )

        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            context = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="你好",
                is_first_user_turn=True,
                now=datetime(2026, 5, 18, 10, 25),
            )

        self.assertIn("饭点食堂提醒", context)
        self.assertIn("开启定位权限", context)

    def test_grade_snapshot_keeps_digest_without_scores(self):
        class ClientStub:
            def get_courses(self):
                return []

            def get_exam_rooms(self, _term):
                return {"exams": []}

            def get_course_selection_overview(self):
                return {"categories": [], "needed_credit_types": []}

            def get_marks(self):
                return [
                    {
                        "semester_code": "202602",
                        "semester": "2025-2026 学年第二学期",
                        "name": "大学英语",
                        "score": "95",
                        "gpa": "4.0",
                    }
                ]

        store = self.make_store()
        with (
            mock.patch.object(dynamic, "campus_dynamic_context_store", store),
            mock.patch.object(dynamic, "_build_client", return_value=ClientStub()),
        ):
            dynamic.refresh_signal_snapshots("102304226", {"edu_authenticated": True})

        grade_snapshot = store.get_snapshot("102304226", "grade", include_expired=True)
        payload = grade_snapshot["payload"]
        self.assertIn("digest", payload)
        self.assertIn("recorded_count", payload)
        self.assertNotIn("latest_courses", payload)
        self.assertNotIn("95", str(payload))

    def test_transient_location_does_not_persist_coordinates(self):
        store = self.make_store()
        with mock.patch.object(dynamic, "campus_dynamic_context_store", store):
            context = dynamic.build_dynamic_campus_context(
                "102304226",
                message_content="你好",
                is_first_user_turn=True,
                location={"lat": 26.060123, "lng": 119.195456, "accuracy": 20},
                now=datetime(2026, 5, 18, 12, 0),
            )

        self.assertIn("本次定位可用", context)
        rows = store.conn.execute("SELECT event_type, digest, last_injected_at, cooldown_until, expires_at FROM reminder_state").fetchall()
        persisted_text = " ".join(" ".join(str(value) for value in row) for row in rows)
        self.assertNotIn("26.060123", persisted_text)
        self.assertNotIn("119.195456", persisted_text)

    def test_user_purge_removes_snapshots_and_reminders(self):
        store = self.make_store()
        store.upsert_snapshot("102304226", "exam", {"digest": "d", "upcoming": []}, timedelta(minutes=30))
        store.event_allowed_and_marked(
            "102304226",
            {
                "type": "exam",
                "digest": "exam:d",
                "repeat": "cooldown",
                "cooldown_seconds": 3600,
            },
        )

        result = store.purge_user("102304226")

        self.assertEqual(result["signal_snapshot_count"], 1)
        self.assertEqual(result["reminder_state_count"], 1)
        self.assertEqual(store.get_fresh_snapshots("102304226"), {})


if __name__ == "__main__":
    unittest.main()
