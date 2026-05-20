from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import logging
import math
import re
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterator, List

from .campus_recommendations import (
    _build_client,
    _course_selection_signals,
    _grade_digest,
    _meal_period,
    _origin_from_course_event,
    _recent_and_next_class,
    _upcoming_exams,
)
from .security_utils import ensure_private_dir, ensure_private_file

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
DYNAMIC_CONTEXT_DB_PATH = STORAGE_DIR / "campus_dynamic_context.sqlite"
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")

COURSE_SNAPSHOT_TTL = timedelta(minutes=30)
EXAM_SNAPSHOT_TTL = timedelta(minutes=30)
SELECTION_SNAPSHOT_TTL = timedelta(minutes=15)
GRADE_SNAPSHOT_TTL = timedelta(hours=6)
MAX_DYNAMIC_CONTEXT_CHARS = 1100

EXPLICIT_DYNAMIC_RE = re.compile(
    r"(成绩|绩点|排名|考试|考场|复习|自习|选课|课表|上课|下课|食堂|吃饭|去哪|哪里|附近|推荐|提醒|注意|待办|安排|计划|今天|明天|本周|最近)"
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_local() -> datetime:
    return datetime.now(LOCAL_TIMEZONE).replace(tzinfo=None)


def _coerce_local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)


def _as_utc(value: datetime | None = None) -> datetime:
    if value is None:
        return _now_utc()
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TIMEZONE)
    return value.astimezone(timezone.utc)


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_digest(value: Any, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _compact_text(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number


def _has_valid_location(location: Dict[str, Any] | None) -> bool:
    if not location:
        return False
    lat = location.get("lat")
    lng = location.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return False
    return math.isfinite(float(lat)) and math.isfinite(float(lng))


class CampusDynamicContextStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        ensure_private_dir(self.db_path.parent)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = RLock()
        self._setup()
        self._harden_storage_files()

    def _harden_storage_files(self) -> None:
        ensure_private_file(self.db_path)
        ensure_private_file(self.db_path.with_name(f"{self.db_path.name}-wal"))
        ensure_private_file(self.db_path.with_name(f"{self.db_path.name}-shm"))

    def _setup(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA secure_delete=ON;

                CREATE TABLE IF NOT EXISTS signal_snapshots (
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL DEFAULT '',
                    refreshed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, kind)
                );

                CREATE TABLE IF NOT EXISTS reminder_state (
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    last_injected_at TEXT NOT NULL,
                    cooldown_until TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, event_type, digest)
                );

                CREATE INDEX IF NOT EXISTS idx_signal_snapshots_user_expires
                ON signal_snapshots (user_id, expires_at);

                CREATE INDEX IF NOT EXISTS idx_reminder_state_user_expires
                ON reminder_state (user_id, expires_at);
                """
            )
            self.conn.commit()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self.lock:
            cur = self.conn.cursor()
            try:
                yield cur
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self._harden_storage_files()
                cur.close()

    def get_snapshot(self, user_id: str, kind: str, *, include_expired: bool = False) -> Dict[str, Any] | None:
        now = _now_utc()
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT kind, payload, digest, refreshed_at, expires_at
                FROM signal_snapshots
                WHERE user_id = ? AND kind = ?
                LIMIT 1
                """,
                (user_id, kind),
            )
            row = cur.fetchone()
        if row is None:
            return None
        expires_at = _from_iso(row["expires_at"])
        if not include_expired and expires_at is not None and expires_at <= now:
            return None
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        return {
            "kind": row["kind"],
            "payload": payload if isinstance(payload, dict) else {},
            "digest": row["digest"],
            "refreshed_at": row["refreshed_at"],
            "expires_at": row["expires_at"],
        }

    def get_fresh_snapshots(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        now = _now_utc()
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT kind, payload, digest, refreshed_at, expires_at
                FROM signal_snapshots
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, _to_iso(now)),
            )
            rows = cur.fetchall()
        snapshots: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                snapshots[row["kind"]] = {
                    "kind": row["kind"],
                    "payload": payload,
                    "digest": row["digest"],
                    "refreshed_at": row["refreshed_at"],
                    "expires_at": row["expires_at"],
                }
        return snapshots

    def upsert_snapshot(self, user_id: str, kind: str, payload: Dict[str, Any], ttl: timedelta) -> None:
        digest = str(payload.get("digest") or _stable_digest(payload))
        now = _now_utc()
        expires_at = now + ttl
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO signal_snapshots (user_id, kind, payload, digest, refreshed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, kind) DO UPDATE SET
                    payload = excluded.payload,
                    digest = excluded.digest,
                    refreshed_at = excluded.refreshed_at,
                    expires_at = excluded.expires_at
                """,
                (
                    user_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    digest,
                    _to_iso(now),
                    _to_iso(expires_at),
                ),
            )

    def event_allowed_and_marked(self, user_id: str, event: Dict[str, Any], now: datetime | None = None) -> bool:
        now_utc = _as_utc(now)
        event_type = str(event.get("type") or "").strip()
        digest = str(event.get("digest") or "").strip()
        if not user_id or not event_type or not digest:
            return False

        repeat_mode = str(event.get("repeat") or "cooldown")
        cooldown_seconds = max(0, _safe_int(event.get("cooldown_seconds"), 0))
        cooldown_until = now_utc + timedelta(seconds=cooldown_seconds)
        expires_at = event.get("expires_at")
        if isinstance(expires_at, datetime):
            event_expires = expires_at
            if event_expires.tzinfo is None:
                event_expires = event_expires.replace(tzinfo=timezone.utc)
        else:
            event_expires = now_utc + timedelta(days=7)

        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM reminder_state WHERE user_id = ? AND expires_at <= ?",
                (user_id, _to_iso(now_utc)),
            )
            cur.execute(
                """
                SELECT cooldown_until
                FROM reminder_state
                WHERE user_id = ? AND event_type = ? AND digest = ?
                LIMIT 1
                """,
                (user_id, event_type, digest),
            )
            row = cur.fetchone()
            if row is not None:
                existing_cooldown = _from_iso(row["cooldown_until"])
                if repeat_mode == "once":
                    return False
                if existing_cooldown is not None and existing_cooldown > now_utc:
                    return False

            cur.execute(
                """
                INSERT INTO reminder_state (
                    user_id, event_type, digest, last_injected_at, cooldown_until, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, event_type, digest) DO UPDATE SET
                    last_injected_at = excluded.last_injected_at,
                    cooldown_until = excluded.cooldown_until,
                    expires_at = excluded.expires_at
                """,
                (
                    user_id,
                    event_type,
                    digest,
                    _to_iso(now_utc),
                    _to_iso(cooldown_until),
                    _to_iso(event_expires),
                ),
            )
            return True

    def purge_user(self, user_id: str) -> Dict[str, int]:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM signal_snapshots WHERE user_id = ?", (user_id,))
            snapshot_count = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM reminder_state WHERE user_id = ?", (user_id,))
            reminder_count = int(cur.fetchone()[0])
            cur.execute("DELETE FROM signal_snapshots WHERE user_id = ?", (user_id,))
            cur.execute("DELETE FROM reminder_state WHERE user_id = ?", (user_id,))
        return {"signal_snapshot_count": snapshot_count, "reminder_state_count": reminder_count}


campus_dynamic_context_store = CampusDynamicContextStore(DYNAMIC_CONTEXT_DB_PATH)


def is_dynamic_context_request(message_content: str) -> bool:
    return bool(EXPLICIT_DYNAMIC_RE.search(message_content or ""))


def _compact_class_event(event: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not event:
        return None
    start_at = event.get("start_at")
    end_at = event.get("end_at")
    return {
        "name": _compact_text(event.get("name"), 40),
        "location": _compact_text(event.get("location"), 40),
        "start": start_at.strftime("%H:%M") if isinstance(start_at, datetime) else "",
        "end": end_at.strftime("%H:%M") if isinstance(end_at, datetime) else "",
        "origin_hint": (_origin_from_course_event(event) or {}).get("name", ""),
    }


def _refresh_course_snapshot(user_id: str, client: Any, now: datetime) -> None:
    courses = client.get_courses()
    recent_class, next_class = _recent_and_next_class(courses, now)
    payload = {
        "recent_class": _compact_class_event(recent_class),
        "next_class": _compact_class_event(next_class),
    }
    payload["digest"] = _stable_digest(payload)
    campus_dynamic_context_store.upsert_snapshot(user_id, "course", payload, COURSE_SNAPSHOT_TTL)


def _refresh_exam_snapshot(user_id: str, client: Any, now: datetime) -> None:
    exam_rooms = client.get_exam_rooms(None)
    upcoming = _upcoming_exams(exam_rooms, now)
    items = [
        {
            "course_name": _compact_text(exam.get("course_name"), 48),
            "date": _compact_text(exam.get("date"), 24),
            "time": _compact_text(exam.get("time"), 32),
            "days_until": exam.get("days_until"),
        }
        for exam in upcoming[:5]
    ]
    payload = {"upcoming": items, "count": len(upcoming), "digest": _stable_digest(items)}
    campus_dynamic_context_store.upsert_snapshot(user_id, "exam", payload, EXAM_SNAPSHOT_TTL)


def _refresh_selection_snapshot(user_id: str, client: Any, now: datetime) -> None:
    overview = client.get_course_selection_overview()
    signals = _course_selection_signals(overview, now)
    public_signals = [
        {
            "type": "course_selection",
            "title": _compact_text(signal.get("title"), 40),
            "summary": _compact_text(signal.get("summary"), 140),
            "priority": _safe_int(signal.get("priority"), 0),
            "status": _compact_text(signal.get("status"), 24),
            "category": _compact_text(signal.get("category"), 40),
            "category_label": _compact_text(signal.get("category_label"), 40),
            "time_window": signal.get("time_window") if isinstance(signal.get("time_window"), dict) else {},
        }
        for signal in signals[:5]
    ]
    payload = {"signals": public_signals, "digest": _stable_digest(public_signals)}
    campus_dynamic_context_store.upsert_snapshot(user_id, "selection", payload, SELECTION_SNAPSHOT_TTL)


def _refresh_grade_snapshot(user_id: str, client: Any) -> None:
    marks = client.get_marks()
    recorded = [
        mark for mark in marks
        if str(mark.get("score") or "").strip() not in {"", "成绩尚未录入"}
    ]
    digest = _grade_digest(recorded)
    if not digest:
        return
    previous = campus_dynamic_context_store.get_snapshot(user_id, "grade", include_expired=True)
    previous_digest = str((previous or {}).get("digest") or "")
    latest_semester_code = max((str(mark.get("semester_code") or "") for mark in recorded), default="")
    latest = [mark for mark in recorded if str(mark.get("semester_code") or "") == latest_semester_code]
    latest_semester = str(latest[0].get("semester") or "") if latest else ""
    payload = {
        "digest": digest,
        "changed": bool(previous_digest and previous_digest != digest),
        "recorded_count": len(recorded),
        "latest_semester": _compact_text(latest_semester, 60),
        "latest_semester_count": len(latest),
    }
    campus_dynamic_context_store.upsert_snapshot(user_id, "grade", payload, GRADE_SNAPSHOT_TTL)


def refresh_signal_snapshots(user_id: str, edu_session: Dict[str, Any] | None, now: datetime | None = None) -> Dict[str, str]:
    if not user_id:
        return {}
    client = _build_client(edu_session)
    if client is None:
        return {"status": "skipped"}
    now = now or _now_local()
    results: Dict[str, str] = {}
    refreshers = {
        "course": lambda: _refresh_course_snapshot(user_id, client, now),
        "exam": lambda: _refresh_exam_snapshot(user_id, client, now),
        "selection": lambda: _refresh_selection_snapshot(user_id, client, now),
        "grade": lambda: _refresh_grade_snapshot(user_id, client),
    }
    for name, refresh in refreshers.items():
        try:
            refresh()
            results[name] = "ok"
        except Exception as exc:
            results[name] = type(exc).__name__
            logger.info("Campus dynamic snapshot refresh failed for %s/%s: %s", user_id[:4], name, type(exc).__name__)
    return results


def _parse_event_date(value: Any) -> date | None:
    text = str(value or "").strip()
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _build_exam_event(snapshot: Dict[str, Any], now: datetime) -> Dict[str, Any] | None:
    upcoming = snapshot.get("payload", {}).get("upcoming") or []
    if not isinstance(upcoming, list) or not upcoming:
        return None
    first = upcoming[0]
    days = _safe_int(first.get("days_until"), 99)
    day_text = "今天" if days == 0 else f"{days} 天后"
    count = _safe_int(snapshot.get("payload", {}).get("count"), len(upcoming))
    course_name = _compact_text(first.get("course_name") or "考试", 40)
    exam_date = _parse_event_date(first.get("date"))
    expires_at = datetime.combine(exam_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) if exam_date else _now_utc() + timedelta(days=8)
    return {
        "type": "exam",
        "title": "考试复习提醒",
        "summary": f"未来 7 天内有 {count} 场考试，最近一场《{course_name}》在{day_text}。",
        "priority": 95 if days <= 1 else 86,
        "digest": f"exam:{snapshot.get('digest')}",
        "repeat": "cooldown",
        "cooldown_seconds": 24 * 60 * 60,
        "expires_at": expires_at,
    }


def _build_grade_event(snapshot: Dict[str, Any]) -> Dict[str, Any] | None:
    payload = snapshot.get("payload", {})
    if not payload.get("changed"):
        return None
    semester = payload.get("latest_semester") or "最新学期"
    count = _safe_int(payload.get("latest_semester_count"), 0)
    return {
        "type": "grade_update",
        "title": "成绩摘要有变化",
        "summary": f"检测到成绩摘要较上次刷新有变化，{semester}已有 {count} 门成绩录入；需要详情时应调用成绩工具实时查询。",
        "priority": 90,
        "digest": f"grade:{payload.get('digest')}",
        "repeat": "once",
        "cooldown_seconds": 0,
        "expires_at": _now_utc() + timedelta(days=14),
    }


def _selection_expiry(signal: Dict[str, Any]) -> datetime:
    window = signal.get("time_window") if isinstance(signal.get("time_window"), dict) else {}
    end_text = str(window.get("end") or "").replace("：", ":").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            parsed = datetime.strptime(end_text, fmt)
            return parsed.replace(tzinfo=timezone.utc) + timedelta(hours=6)
        except ValueError:
            continue
    return _now_utc() + timedelta(days=7)


def _build_selection_events(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    signals = snapshot.get("payload", {}).get("signals") or []
    if not isinstance(signals, list):
        return []
    events: List[Dict[str, Any]] = []
    for signal in signals[:3]:
        if not isinstance(signal, dict):
            continue
        digest_payload = {
            "category": signal.get("category"),
            "status": signal.get("status"),
            "time_window": signal.get("time_window"),
        }
        events.append(
            {
                "type": "course_selection",
                "title": signal.get("title") or "选课提醒",
                "summary": signal.get("summary") or "选课窗口状态有变化，必要时可提醒用户查看。",
                "priority": _safe_int(signal.get("priority"), 75),
                "digest": f"selection:{_stable_digest(digest_payload)}",
                "repeat": "once",
                "cooldown_seconds": 0,
                "expires_at": _selection_expiry(signal),
            }
        )
    return events


def _build_course_event(snapshot: Dict[str, Any], now: datetime) -> Dict[str, Any] | None:
    payload = snapshot.get("payload", {})
    recent = payload.get("recent_class") if isinstance(payload.get("recent_class"), dict) else None
    next_class = payload.get("next_class") if isinstance(payload.get("next_class"), dict) else None
    meal = _meal_period(now)
    if recent and meal != "就餐":
        name = recent.get("name") or "课程"
        location = f"（{recent.get('location')}）" if recent.get("location") else ""
        return {
            "type": "recent_class",
            "title": "刚下课顺路提醒",
            "summary": f"用户近期刚结束《{name}》{location}，当前接近{meal}时段；若回答自然，可在末尾轻声提醒可追问附近食堂。",
            "priority": 72,
            "digest": f"recent:{now.date().isoformat()}:{payload.get('digest')}",
            "repeat": "cooldown",
            "cooldown_seconds": 2 * 60 * 60,
            "expires_at": _now_utc() + timedelta(hours=3),
        }
    if meal != "就餐":
        return _build_meal_time_event(now, meal)
    if next_class:
        name = next_class.get("name") or "课程"
        return {
            "type": "next_class",
            "title": "下一节课衔接提醒",
            "summary": f"用户今天接下来有《{name}》；若用户在规划时间或地点，可优先提醒不要绕远。",
            "priority": 58,
            "digest": f"next:{now.date().isoformat()}:{payload.get('digest')}",
            "repeat": "cooldown",
            "cooldown_seconds": 2 * 60 * 60,
            "expires_at": _now_utc() + timedelta(hours=6),
        }
    return None


def _build_meal_time_event(now: datetime, meal: str | None = None) -> Dict[str, Any] | None:
    meal = meal or _meal_period(now)
    if meal == "就餐":
        return None
    return {
        "type": "meal_time",
        "title": "饭点食堂提醒",
        "summary": f"当前接近{meal}时段；若用户在问候、安排今天或校园生活，可在末尾轻声提醒可开启定位权限或说明所在校区/教学楼，再继续追问附近食堂。",
        "priority": 64,
        "digest": f"meal:{now.date().isoformat()}:{meal}",
        "repeat": "cooldown",
        "cooldown_seconds": 2 * 60 * 60,
        "expires_at": _now_utc() + timedelta(hours=3),
    }


def _build_location_event(location: Dict[str, Any] | None, now: datetime) -> Dict[str, Any] | None:
    if not _has_valid_location(location):
        return None
    meal = _meal_period(now)
    if meal == "就餐":
        return None
    return {
        "type": "transient_location",
        "title": "本次定位可用",
        "summary": f"本次消息携带浏览器临时定位，可在用户需要校园去处时提醒能按当前位置给出{meal}或自习建议；不要复述经纬度。",
        "priority": 54,
        "digest": f"location:{now.date().isoformat()}:{now.hour}:{meal}",
        "repeat": "cooldown",
        "cooldown_seconds": 2 * 60 * 60,
        "expires_at": _now_utc() + timedelta(hours=2),
    }


def build_dynamic_campus_context(
    user_id: str,
    *,
    message_content: str,
    is_first_user_turn: bool,
    location: Dict[str, Any] | None = None,
    budget_ms: int = 250,
    max_chars: int = MAX_DYNAMIC_CONTEXT_CHARS,
    now: datetime | None = None,
) -> str:
    started = time.monotonic()
    now = _coerce_local_datetime(now or _now_local())
    if not user_id:
        return ""
    if not is_first_user_turn and not is_dynamic_context_request(message_content):
        return ""

    snapshots = campus_dynamic_context_store.get_fresh_snapshots(user_id)
    if (time.monotonic() - started) * 1000 > budget_ms:
        return ""

    events: List[Dict[str, Any]] = []
    if "exam" in snapshots:
        exam_event = _build_exam_event(snapshots["exam"], now)
        if exam_event:
            events.append(exam_event)
    if "grade" in snapshots:
        grade_event = _build_grade_event(snapshots["grade"])
        if grade_event:
            events.append(grade_event)
    if "selection" in snapshots:
        events.extend(_build_selection_events(snapshots["selection"]))
    location_event = _build_location_event(location, now)
    course_event = _build_course_event(snapshots.get("course", {}), now)
    if course_event and not (location_event and course_event.get("type") == "meal_time"):
        events.append(course_event)
    if location_event:
        events.append(location_event)

    events.sort(key=lambda item: _safe_int(item.get("priority"), 0), reverse=True)
    selected: List[Dict[str, Any]] = []
    for event in events:
        if (time.monotonic() - started) * 1000 > budget_ms:
            break
        if campus_dynamic_context_store.event_allowed_and_marked(user_id, event, now=now):
            selected.append(event)
        if len(selected) >= 3:
            break

    if not selected:
        return ""

    lines = [
        "校园动态事件（隐藏上下文，仅供判断是否在本次回答末尾自然提醒；不要说出本段来源）：",
    ]
    for index, event in enumerate(selected, start=1):
        lines.append(f"{index}. {event['title']}：{event['summary']}")
    lines.append("提醒约束：先完整回答用户当前问题；考试、成绩、选课这类高优先级事件，在问候、泛问或学习安排场景可优先于末尾轻声提醒一句；专业知识问答等无关场景可忽略。最多提醒 1-2 条；不要保存这些易变事实到长期记忆。")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def purge_dynamic_context_user_data(user_id: str) -> Dict[str, int]:
    return campus_dynamic_context_store.purge_user(user_id)
