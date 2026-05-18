from __future__ import annotations

from collections import deque
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import os
from pathlib import Path
import re
from threading import Lock
import time as time_module
from typing import Any, Dict, List, Tuple

import requests
from langchain_core.tools import tool

from .jwch_client import JwchClient, JwchError

AMAP_AROUND_URL = "https://restapi.amap.com/v3/place/around"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_TIMEOUT_SECONDS = float(os.getenv("AMAP_TIMEOUT_SECONDS", "4"))
AMAP_MAX_QPS = max(1, min(5, int(os.getenv("AMAP_MAX_QPS", "5") or "5")))
AMAP_ROUTE_CANDIDATE_LIMIT = max(1, int(os.getenv("AMAP_ROUTE_CANDIDATE_LIMIT", "4") or "4"))
BASE_DIR = Path(__file__).resolve().parent
_AMAP_RATE_LOCK = Lock()
_AMAP_REQUEST_TIMES = deque()

AMAP_ERROR_MESSAGES = {
    "10001": "高德 Key 不正确或已失效",
    "10003": "高德服务访问已超出日配额",
    "10004": "高德服务访问过于频繁",
    "10009": "高德 Key 的 IP 白名单限制不允许当前服务访问",
    "10010": "高德服务请求路径或参数无效",
    "10011": "高德服务权限不足",
    "10012": "高德服务权限不足",
    "10013": "高德 Key 被删除或不可用",
    "CUQPS_HAS_EXCEEDED_THE_LIMIT": "高德服务访问过于频繁或额度暂时受限",
    "DAILY_QUERY_OVER_LIMIT": "高德服务访问已超出日配额",
    "INVALID_USER_KEY": "高德 Key 不正确或已失效",
    "INSUFFICIENT_PRIVILEGES": "高德服务权限不足",
}


def _read_amap_key(explicit_key: str | None = None) -> str:
    if explicit_key is not None:
        return explicit_key.strip()

    key_file = os.getenv("AMAP_WEB_SERVICE_KEY_FILE")
    candidate_paths = [
        Path("/run/secrets/amap_web_service_key"),
        Path(key_file) if key_file else None,
        BASE_DIR.parent / "amap_web_service_key.txt",
        BASE_DIR.parent / "amap_api_key.txt",
    ]

    env_value = os.getenv("AMAP_WEB_SERVICE_KEY")
    if env_value:
        return env_value.strip()

    for path in candidate_paths:
        if not path:
            continue
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def _amap_error_message(payload: Dict[str, Any] | None) -> str:
    if not payload:
        return "地图服务暂不可用"
    code = str(payload.get("infocode") or "").strip()
    info = str(payload.get("info") or "").strip()
    if code in AMAP_ERROR_MESSAGES:
        return AMAP_ERROR_MESSAGES[code]
    if info in AMAP_ERROR_MESSAGES:
        return AMAP_ERROR_MESSAGES[info]
    if info and info.upper() != "OK":
        return f"地图服务返回异常：{info}"
    return "地图服务暂不可用"


def _wait_for_amap_slot() -> None:
    """Process-local rolling-window limiter for AMap Web Service QPS."""
    while True:
        now = time_module.monotonic()
        with _AMAP_RATE_LOCK:
            while _AMAP_REQUEST_TIMES and now - _AMAP_REQUEST_TIMES[0] >= 1:
                _AMAP_REQUEST_TIMES.popleft()
            if len(_AMAP_REQUEST_TIMES) < AMAP_MAX_QPS:
                _AMAP_REQUEST_TIMES.append(now)
                return
            sleep_for = max(0.02, 1 - (now - _AMAP_REQUEST_TIMES[0]) + 0.01)
        time_module.sleep(sleep_for)


def _beijing_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        return datetime.now()

DAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

SECTION_TIMES = {
    1: (time(8, 20), time(9, 5)),
    2: (time(9, 15), time(10, 0)),
    3: (time(10, 20), time(11, 5)),
    4: (time(11, 15), time(12, 0)),
    5: (time(14, 0), time(14, 45)),
    6: (time(14, 55), time(15, 40)),
    7: (time(15, 50), time(16, 35)),
    8: (time(16, 45), time(17, 30)),
    9: (time(19, 0), time(19, 45)),
    10: (time(19, 55), time(20, 40)),
    11: (time(20, 50), time(21, 35)),
}

MANUAL_LOCATIONS: List[Dict[str, Any]] = [
    {"id": "qishan_center", "name": "旗山校区中心区", "campus": "旗山校区", "lat": 26.0639, "lng": 119.1954},
    {"id": "qishan_teaching", "name": "旗山校区教学区", "campus": "旗山校区", "lat": 26.0624, "lng": 119.1972},
    {"id": "qishan_dorm", "name": "旗山校区生活区", "campus": "旗山校区", "lat": 26.0660, "lng": 119.1921},
    {"id": "qishan_library", "name": "旗山校区图书馆", "campus": "旗山校区", "lat": 26.0633, "lng": 119.1960},
    {"id": "qishan_jinjiang", "name": "晋江楼学习中心", "campus": "旗山校区", "lat": 26.061237, "lng": 119.201205},
    {"id": "qishan_staff_center", "name": "教工活动中心 / 桃李园", "campus": "旗山校区", "lat": 26.062976, "lng": 119.196459},
    {"id": "qishan_life_zone_1", "name": "旗山校区生活一区", "campus": "旗山校区", "lat": 26.0567, "lng": 119.1924},
    {"id": "qishan_life_zone_3", "name": "旗山校区生活三区", "campus": "旗山校区", "lat": 26.0529, "lng": 119.1927},
    {"id": "yishan_center", "name": "怡山校区", "campus": "怡山校区", "lat": 26.0831, "lng": 119.2768},
    {"id": "tongpan_center", "name": "铜盘校区", "campus": "铜盘校区", "lat": 26.1158, "lng": 119.2767},
]

CAMPUS_POIS: List[Dict[str, Any]] = [
    {
        "id": "qishan_rose_canteen",
        "name": "玫瑰园餐厅",
        "kind": "dining",
        "campus": "旗山校区",
        "lat": 26.052871,
        "lng": 119.192741,
        "tags": ["食堂", "生活三区", "午餐", "晚餐"],
        "description": "位于旗山校区生活三区一带，档口选择较多，适合从南侧生活区或教学区南侧前往。",
    },
    {
        "id": "qishan_lilac_canteen",
        "name": "丁香园餐厅",
        "kind": "dining",
        "campus": "旗山校区",
        "lat": 26.056667,
        "lng": 119.192164,
        "tags": ["食堂", "生活一区", "早餐", "午餐"],
        "description": "靠近旗山校区生活一区，适合宿舍区附近快速用餐。",
    },
    {
        "id": "qishan_zijing_canteen",
        "name": "紫荆园餐厅",
        "kind": "dining",
        "campus": "旗山校区",
        "lat": 26.052725,
        "lng": 119.192125,
        "tags": ["食堂", "宿舍区", "早餐"],
        "description": "靠近学生生活区，适合回宿舍路上顺路用餐，也常作为晚间备选。",
    },
    {
        "id": "qishan_haitang_canteen",
        "name": "海棠园餐厅",
        "kind": "dining",
        "campus": "旗山校区",
        "lat": 26.056780,
        "lng": 119.192574,
        "tags": ["食堂", "生活一区", "早餐", "午餐"],
        "description": "靠近生活一区，与丁香园相邻，适合在宿舍区附近就餐。",
    },
    {
        "id": "qishan_taoliyuan_canteen",
        "name": "桃李园餐厅",
        "kind": "dining",
        "campus": "旗山校区",
        "lat": 26.062976,
        "lng": 119.196459,
        "tags": ["食堂", "教工活动中心", "教学区", "午餐"],
        "description": "位于教工活动中心位置，靠近旗山校区中心与教学区，适合从图书馆、公共教学楼附近前往。",
    },
    {
        "id": "yishan_canteen",
        "name": "怡山校区学生餐厅",
        "kind": "dining",
        "campus": "怡山校区",
        "lat": 26.0834,
        "lng": 119.2760,
        "tags": ["食堂", "怡山"],
        "description": "适合怡山校区附近就餐。",
    },
    {
        "id": "tongpan_canteen",
        "name": "铜盘校区学生餐厅",
        "kind": "dining",
        "campus": "铜盘校区",
        "lat": 26.1160,
        "lng": 119.2760,
        "tags": ["食堂", "铜盘"],
        "description": "适合铜盘校区附近就餐。",
    },
    {
        "id": "qishan_library",
        "name": "旗山校区图书馆",
        "kind": "study",
        "campus": "旗山校区",
        "lat": 26.0633,
        "lng": 119.1960,
        "tags": ["自习", "安静", "复习", "资料"],
        "description": "空间稳定、资料获取方便，适合考试周系统复习。",
    },
    {
        "id": "qishan_teaching_buildings",
        "name": "旗山校区公共教学楼自习区",
        "kind": "study",
        "campus": "旗山校区",
        "lat": 26.0620,
        "lng": 119.1980,
        "tags": ["自习", "课间", "近教学楼"],
        "description": "靠近教学区，适合课前课后短时复习。",
    },
    {
        "id": "qishan_jinjiang_learning_center",
        "name": "晋江楼学习中心",
        "kind": "study",
        "campus": "旗山校区",
        "lat": 26.061237,
        "lng": 119.201205,
        "tags": ["自习", "讨论", "学习中心", "晋江楼4层"],
        "description": "位于旗山校区晋江楼 4-5 层，适合自习、研讨和较长时间复习。",
    },
    {
        "id": "yishan_library",
        "name": "怡山校区图书馆",
        "kind": "study",
        "campus": "怡山校区",
        "lat": 26.0830,
        "lng": 119.2776,
        "tags": ["自习", "怡山"],
        "description": "适合怡山校区附近复习与查阅资料。",
    },
]

COURSE_LOCATION_HINTS: Tuple[Dict[str, Any], ...] = (
    {"tokens": ("晋江楼", "晋江"), "name": "晋江楼", "campus": "旗山校区", "lat": 26.061237, "lng": 119.201205},
    {"tokens": ("图书馆",), "name": "旗山校区图书馆", "campus": "旗山校区", "lat": 26.0633, "lng": 119.1960},
    {"tokens": ("教工活动中心", "桃李园"), "name": "教工活动中心 / 桃李园", "campus": "旗山校区", "lat": 26.062976, "lng": 119.196459},
    {"tokens": ("生活一区", "丁香园", "海棠园"), "name": "旗山校区生活一区", "campus": "旗山校区", "lat": 26.0567, "lng": 119.1924},
    {"tokens": ("生活三区", "玫瑰园", "紫荆园"), "name": "旗山校区生活三区", "campus": "旗山校区", "lat": 26.0529, "lng": 119.1927},
    {"tokens": ("公共教学楼", "教学楼", "西一", "西1", "西二", "西2", "西三", "西3", "东一", "东1", "东二", "东2", "东三", "东3"), "name": "旗山校区教学区", "campus": "旗山校区", "lat": 26.0624, "lng": 119.1972},
    {"tokens": ("怡山",), "name": "怡山校区", "campus": "怡山校区", "lat": 26.0831, "lng": 119.2768},
    {"tokens": ("铜盘",), "name": "铜盘校区", "campus": "铜盘校区", "lat": 26.1158, "lng": 119.2767},
)


class RecommendationError(Exception):
    pass


def manual_location_options() -> List[Dict[str, Any]]:
    return [
        {"id": item["id"], "name": item["name"], "campus": item["campus"]}
        for item in MANUAL_LOCATIONS
    ]


def _build_client(edu_session: Dict[str, Any] | None = None) -> JwchClient | None:
    if not edu_session or not edu_session.get("edu_authenticated"):
        return None
    return JwchClient.from_cookies(
        edu_session.get("user_id", ""),
        edu_session.get("edu_cookies") or [],
        edu_session.get("edu_identifier", ""),
    )


def _haversine_meters(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> int:
    radius = 6371000
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    d_phi = math.radians(b_lat - a_lat)
    d_lambda = math.radians(b_lng - a_lng)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return int(round(radius * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))))


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _resolve_origin(location: Dict[str, Any] | None, manual_location_id: str = "") -> Dict[str, Any]:
    lat = _safe_float((location or {}).get("lat"))
    lng = _safe_float((location or {}).get("lng"))
    accuracy = _safe_float((location or {}).get("accuracy"))
    if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
        return {
            "lat": lat,
            "lng": lng,
            "accuracy": accuracy,
            "source": "browser",
            "name": "当前位置",
            "privacy": "已使用你本次授权的浏览器定位，服务端不会保存经纬度。",
        }

    manual = next((item for item in MANUAL_LOCATIONS if item["id"] == manual_location_id), None)
    if manual:
        return {
            "lat": float(manual["lat"]),
            "lng": float(manual["lng"]),
            "accuracy": None,
            "source": "manual",
            "name": manual["name"],
            "privacy": "已使用你选择的校内位置，本次请求不会保存精确位置。",
        }

    fallback = MANUAL_LOCATIONS[0]
    return {
        "lat": float(fallback["lat"]),
        "lng": float(fallback["lng"]),
        "accuracy": None,
        "source": "default",
        "name": fallback["name"],
        "privacy": "未获得定位，已按旗山校区中心位置估算。",
    }


def _origin_from_course_event(event: Dict[str, Any] | None) -> Dict[str, Any] | None:
    location_text = str((event or {}).get("location") or "")
    if not location_text:
        return None
    normalized = re.sub(r"\s+", "", location_text)
    for hint in COURSE_LOCATION_HINTS:
        if any(token in normalized for token in hint["tokens"]):
            return {
                "lat": float(hint["lat"]),
                "lng": float(hint["lng"]),
                "accuracy": None,
                "source": "course",
                "name": f"{hint['name']}（由课程地点推断）",
                "privacy": "未获得浏览器定位，已根据课表地点做本次推荐估算，不保存课程地点或经纬度。",
            }
    return None


def _parse_section_numbers(text: str) -> List[int]:
    numbers: List[int] = []
    for match in re.finditer(r"第\s*(\d{1,2})(?:\s*[-,，、]\s*(\d{1,2}))?\s*节", text):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end < start:
            start, end = end, start
        numbers.extend(number for number in range(start, end + 1) if number in SECTION_TIMES)
    if not numbers:
        for raw in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", text):
            number = int(raw)
            if number in SECTION_TIMES:
                numbers.append(number)
    return sorted(set(numbers))


def _course_events_for_today(courses: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    weekday = now.weekday()
    for course in courses:
        raw_time = str(course.get("time") or "")
        if not raw_time:
            continue
        blocks = [line.strip() for line in raw_time.splitlines() if line.strip()] or [raw_time]
        for block in blocks:
            day_match = re.search(r"周([一二三四五六日天])", block)
            if not day_match or DAY_INDEX.get(day_match.group(1)) != weekday:
                continue
            sections = _parse_section_numbers(block)
            if not sections:
                continue
            start_time = SECTION_TIMES[min(sections)][0]
            end_time = SECTION_TIMES[max(sections)][1]
            location = str(course.get("location") or "").strip()
            if not location:
                parts = block.split()
                location = parts[-1] if len(parts) >= 3 else ""
            events.append(
                {
                    "name": course.get("name") or "课程",
                    "teacher": course.get("teacher") or "",
                    "location": location,
                    "start_at": datetime.combine(now.date(), start_time),
                    "end_at": datetime.combine(now.date(), end_time),
                    "raw": block,
                }
            )
    return sorted(events, key=lambda item: item["start_at"])


def _recent_and_next_class(courses: List[Dict[str, Any]], now: datetime) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    recent_class = None
    next_class = None
    for event in _course_events_for_today(courses, now):
        if timedelta(0) <= now - event["end_at"] <= timedelta(minutes=90):
            recent_class = event
        if event["start_at"] >= now and next_class is None:
            next_class = event
    return recent_class, next_class


def _parse_exam_date(value: Any) -> date | None:
    text = str(value or "").strip()
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _upcoming_exams(exam_rooms: Dict[str, Any] | None, now: datetime) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    today = now.date()
    for exam in (exam_rooms or {}).get("exams") or []:
        exam_date = _parse_exam_date(exam.get("date"))
        if not exam_date:
            continue
        days = (exam_date - today).days
        if 0 <= days <= 7:
            result.append({**exam, "days_until": days})
    return sorted(result, key=lambda item: (item.get("date") or "", item.get("time") or ""))


def _parse_selection_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("：", ":")
    if not text:
        return None
    try:
        if text.endswith("24:00"):
            return datetime.strptime(text[:-5] + "00:00", "%Y-%m-%d %H:%M") + timedelta(days=1)
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _format_time_delta(delta: timedelta) -> str:
    total_minutes = max(0, int(delta.total_seconds() // 60))
    days, minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days > 0:
        return f"{days} 天后"
    if hours > 0:
        return f"{hours} 小时后"
    return f"{max(1, minutes)} 分钟后"


def _grade_digest(marks: List[Dict[str, Any]]) -> str:
    recorded = [
        {
            "semester_code": str(mark.get("semester_code") or ""),
            "name": str(mark.get("name") or ""),
            "score": str(mark.get("score") or ""),
            "gpa": str(mark.get("gpa") or ""),
        }
        for mark in marks
        if str(mark.get("score") or "").strip() not in {"", "成绩尚未录入"}
    ]
    payload = json.dumps(sorted(recorded, key=lambda item: (item["semester_code"], item["name"])), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16] if recorded else ""


def _grade_update_signal(marks: List[Dict[str, Any]], seen_grade_digest: str = "") -> Dict[str, Any] | None:
    recorded = [
        mark for mark in marks
        if str(mark.get("score") or "").strip() not in {"", "成绩尚未录入"}
    ]
    if not recorded:
        return None
    digest = _grade_digest(recorded)
    latest_semester_code = max(str(mark.get("semester_code") or "") for mark in recorded)
    latest = [mark for mark in recorded if str(mark.get("semester_code") or "") == latest_semester_code]
    latest_semester = latest[0].get("semester") if latest else ""
    has_update = bool(seen_grade_digest and digest and seen_grade_digest != digest)
    title = "成绩有更新" if has_update else "查看最新成绩"
    summary = (
        f"检测到成绩记录较上次查看有变化，{latest_semester or '最新学期'}已有 {len(latest)} 门成绩录入。"
        if has_update else
        f"{latest_semester or '最新学期'}已有 {len(latest)} 门成绩录入，可以查看成绩和绩点变化。"
    )
    return {
        "type": "grade_update",
        "title": title,
        "summary": summary,
        "priority": 95 if has_update else 45,
        "status": "changed" if has_update else "available",
        "digest": digest,
        "recorded_count": len(recorded),
        "latest_semester": latest_semester,
        "latest_courses": [
            {
                "name": mark.get("name") or "",
                "score": mark.get("score") or "",
                "credits": mark.get("credits") or "",
                "gpa": mark.get("gpa") or "",
            }
            for mark in latest[:5]
        ],
        "prompt": "帮我查询最新成绩，并总结本学期成绩、绩点变化和需要注意的课程。",
    }


def _exam_signals(upcoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not upcoming:
        return []
    first = upcoming[0]
    days = first.get("days_until")
    day_text = "今天" if days == 0 else f"{days} 天后"
    return [
        {
            "type": "exam",
            "title": "考试复习提醒",
            "summary": f"未来 7 天内有 {len(upcoming)} 场考试，最近一场《{first.get('course_name') or '考试'}》在{day_text}。",
            "priority": 88 if days == 0 else 82,
            "status": "upcoming",
            "items": [
                {
                    "course_name": exam.get("course_name") or "",
                    "date": exam.get("date") or "",
                    "time": exam.get("time") or "",
                    "location": exam.get("location") or "",
                    "days_until": exam.get("days_until"),
                }
                for exam in upcoming[:3]
            ],
            "prompt": f"我{day_text}有《{first.get('course_name') or '考试'}》考试，请结合我的课表安排今天的复习计划，并推荐合适的自习地点。",
        }
    ]


def _course_selection_signals(selection_overview: Dict[str, Any] | None, now: datetime) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    if not selection_overview:
        return signals

    needed_credit_types = selection_overview.get("needed_credit_types") or []
    missing_text = "、".join(
        f"{item.get('category')}还差{item.get('missing')}学分"
        for item in needed_credit_types[:3]
        if item.get("missing")
    )

    for category in selection_overview.get("categories") or []:
        label = category.get("label") or "选课"
        status = category.get("status") or "unknown"
        window = category.get("time_window") or {}
        start_at = _parse_selection_datetime(window.get("start"))
        end_at = _parse_selection_datetime(window.get("end"))
        candidate_count = int(category.get("candidate_count") or 0)
        selected_count = int(category.get("selected_count") or 0)
        course_count = int(category.get("current_course_count") or 0)
        summary_bits = []
        if candidate_count:
            summary_bits.append(f"当前候选课程 {candidate_count} 门")
        if course_count:
            selected_text = f"，其中已中选 {selected_count} 门" if selected_count and selected_count != course_count else ""
            summary_bits.append(f"结果页课程 {course_count} 门{selected_text}")
        if label == "通识选修课" and missing_text:
            summary_bits.append(f"通识缺口：{missing_text}")
        summary_tail = "；".join(summary_bits)

        if status == "open":
            ending_soon = end_at is not None and timedelta(0) <= end_at - now <= timedelta(hours=24)
            title = f"{label}即将截止" if ending_soon else f"{label}正在进行"
            end_text = f"，截止时间 {window.get('end')}" if window.get("end") else ""
            signals.append(
                {
                    "type": "course_selection",
                    "title": title,
                    "summary": f"{label}已开放{end_text}。{summary_tail or '建议及时确认是否需要调整。'}",
                    "priority": 92 if ending_soon else 86,
                    "status": "ending_soon" if ending_soon else "open",
                    "category": category.get("key") or "",
                    "category_label": label,
                    "candidate_count": candidate_count,
                    "time_window": window,
                    "prompt": f"帮我查看{label}现在能选什么课，结合我的已选课程和通识缺口给出推荐。",
                }
            )
            continue

        if status == "upcoming" and start_at is not None:
            until_start = start_at - now
            if timedelta(0) <= until_start <= timedelta(days=7):
                signals.append(
                    {
                        "type": "course_selection",
                        "title": f"{label}即将开始",
                        "summary": f"{label}将在{_format_time_delta(until_start)}开始，时间为 {window.get('start')} 至 {window.get('end')}。{summary_tail}",
                        "priority": 76,
                        "status": "upcoming",
                        "category": category.get("key") or "",
                        "category_label": label,
                        "candidate_count": candidate_count,
                        "time_window": window,
                        "prompt": f"{label}即将开始，请帮我先整理选课策略、注意事项和优先考虑的课程类型。",
                    }
                )

    return signals


def _rank_academic_signals(
    *,
    upcoming: List[Dict[str, Any]],
    selection_overview: Dict[str, Any] | None,
    marks: List[Dict[str, Any]],
    seen_grade_digest: str,
    now: datetime,
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    signals.extend(_course_selection_signals(selection_overview, now))
    grade_signal = _grade_update_signal(marks, seen_grade_digest)
    if grade_signal:
        signals.append(grade_signal)
    signals.extend(_exam_signals(upcoming))
    return sorted(signals, key=lambda item: int(item.get("priority") or 0), reverse=True)


class AMapClient:
    def __init__(self, key: str | None = None, timeout: float = AMAP_TIMEOUT_SECONDS):
        self.key = _read_amap_key(key)
        self.timeout = timeout
        self.last_error = ""

    @property
    def available(self) -> bool:
        return bool(self.key)

    def walking_route(self, origin: Dict[str, Any], dest: Dict[str, Any]) -> Dict[str, Any] | None:
        if not self.available:
            return None
        params = {
            "key": self.key,
            "origin": f"{origin['lng']},{origin['lat']}",
            "destination": f"{dest['lng']},{dest['lat']}",
        }
        try:
            _wait_for_amap_slot()
            response = requests.get(AMAP_WALKING_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self.last_error = "地图服务请求失败"
            return None
        if str(payload.get("status")) != "1":
            self.last_error = _amap_error_message(payload)
            return None
        paths = ((payload.get("route") or {}).get("paths") or [])
        if not paths:
            return None
        path = paths[0]
        distance = _safe_float(path.get("distance"))
        duration = _safe_float(path.get("duration"))
        if distance is None and duration is None:
            return None
        return {
            "distance_m": int(round(distance)) if distance is not None else None,
            "duration_min": int(math.ceil(duration / 60)) if duration is not None else None,
            "source": "amap",
        }

    def around(self, origin: Dict[str, Any], keywords: str, kind: str) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        params = {
            "key": self.key,
            "location": f"{origin['lng']},{origin['lat']}",
            "keywords": keywords,
            "radius": "1800",
            "offset": "6",
            "page": "1",
            "extensions": "base",
        }
        try:
            _wait_for_amap_slot()
            response = requests.get(AMAP_AROUND_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self.last_error = "地图服务请求失败"
            return []
        if str(payload.get("status")) != "1":
            self.last_error = _amap_error_message(payload)
            return []
        pois: List[Dict[str, Any]] = []
        for item in payload.get("pois") or []:
            location = str(item.get("location") or "")
            try:
                lng_text, lat_text = location.split(",", 1)
                lng = float(lng_text)
                lat = float(lat_text)
            except (ValueError, TypeError):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            pois.append(
                {
                    "id": f"amap_{item.get('id') or re.sub(r'\\W+', '_', name)}",
                    "name": name,
                    "kind": kind,
                    "campus": "高德周边",
                    "lat": lat,
                    "lng": lng,
                    "tags": ["高德补充"],
                    "description": str(item.get("address") or "来自高德周边搜索的补充地点。"),
                    "source": "amap_poi",
                }
            )
        return pois


def _meal_period(now: datetime) -> str:
    current = now.time()
    if time(6, 15) <= current <= time(9, 45):
        return "早餐"
    if time(11, 20) <= current <= time(13, 45):
        return "午餐"
    if time(17, 00) <= current <= time(19, 45):
        return "晚餐"
    return "就餐"


def _choose_scenario(
    requested: str,
    recent_class: Dict[str, Any] | None,
    next_class: Dict[str, Any] | None,
    upcoming: List[Dict[str, Any]],
    now: datetime,
    primary_signal: Dict[str, Any] | None = None,
) -> str:
    if requested in {"dining", "study"}:
        return requested
    if primary_signal and primary_signal.get("type") in {"course_selection", "grade_update", "exam"}:
        return "study"
    if upcoming:
        return "study"
    if recent_class:
        return "dining"
    if next_class and (next_class["start_at"] - now) <= timedelta(hours=2):
        return "study"
    return "dining" if _meal_period(now) != "就餐" else "study"


def _trigger_reason(
    scenario: str,
    recent_class: Dict[str, Any] | None,
    next_class: Dict[str, Any] | None,
    upcoming: List[Dict[str, Any]],
    origin: Dict[str, Any],
    now: datetime,
    primary_signal: Dict[str, Any] | None = None,
) -> str:
    if primary_signal and primary_signal.get("summary"):
        return str(primary_signal["summary"])
    if scenario == "study" and upcoming:
        first = upcoming[0]
        return f"你未来 7 天内有 {len(upcoming)} 场考试，最近一场是《{first.get('course_name') or '考试'}》，建议安排复习。"
    if scenario == "dining" and recent_class:
        location = f"（{recent_class.get('location')}）" if recent_class.get("location") else ""
        return f"你刚结束《{recent_class.get('name')}》{location}，适合优先找步行更近的食堂。"
    if next_class:
        return f"你今天接下来还有《{next_class.get('name')}》，推荐选择不绕路、方便衔接下一节课的位置。"
    if scenario == "dining":
        return f"当前接近{_meal_period(now)}时段，已按{origin['name']}附近的位置排序。"
    return f"已按{origin['name']}附近的自习场所排序，适合安排一段专注学习时间。"


def _candidate_reason(kind: str, poi: Dict[str, Any], distance_m: int, route: Dict[str, Any] | None, upcoming: List[Dict[str, Any]]) -> str:
    walk_text = f"步行约 {route['duration_min']} 分钟" if route and route.get("duration_min") else f"直线距离约 {distance_m} 米"
    if kind == "study" and upcoming:
        return f"{walk_text}，环境更适合考前复习。{poi.get('description') or ''}".strip()
    if kind == "study":
        return f"{walk_text}，适合短时自习或整理课程笔记。{poi.get('description') or ''}".strip()
    return f"{walk_text}，适合当前时段就餐。{poi.get('description') or ''}".strip()


def _candidate_context_bonus(kind: str, poi: Dict[str, Any], now: datetime, primary_signal: Dict[str, Any] | None) -> int:
    tags = {str(tag) for tag in (poi.get("tags") or [])}
    name = str(poi.get("name") or "")
    bonus = 0
    if kind == "dining":
        meal = _meal_period(now)
        if meal in tags:
            bonus += 3
        if meal in {"午餐", "晚餐"} and tags.intersection({"教学区", "生活一区", "生活三区"}):
            bonus += 1
    else:
        signal_type = (primary_signal or {}).get("type")
        if signal_type in {"exam", "grade_update", "course_selection"} and tags.intersection({"安静", "复习", "学习中心", "资料"}):
            bonus += 4
        if signal_type == "course_selection" and name == "旗山校区公共教学楼自习区":
            bonus += 1
        if signal_type == "exam" and name == "晋江楼学习中心":
            bonus += 2
    return bonus


def build_contextual_recommendation(
    *,
    scenario: str = "auto",
    location: Dict[str, Any] | None = None,
    manual_location_id: str = "",
    seen_grade_digest: str = "",
    edu_session: Dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    now = now or _beijing_now().replace(tzinfo=None)
    requested = scenario if scenario in {"auto", "dining", "study"} else "auto"
    origin = _resolve_origin(location, manual_location_id)

    courses: List[Dict[str, Any]] = []
    exam_rooms: Dict[str, Any] | None = None
    selection_overview: Dict[str, Any] | None = None
    marks: List[Dict[str, Any]] = []
    edu_status = "available"
    client = _build_client(edu_session)
    if client is None:
        edu_status = "unavailable"
    else:
        try:
            courses = client.get_courses()
        except JwchError as exc:
            edu_status = str(exc) or "unavailable"
        except Exception:
            edu_status = "课表暂时不可用"
        try:
            exam_rooms = client.get_exam_rooms(None)
        except Exception:
            exam_rooms = None
        if requested == "auto":
            try:
                selection_overview = client.get_course_selection_overview()
            except Exception:
                selection_overview = None
            try:
                marks = client.get_marks()
            except Exception:
                marks = []

    recent_class, next_class = _recent_and_next_class(courses, now)
    upcoming = _upcoming_exams(exam_rooms, now)
    if origin["source"] == "default":
        inferred_origin = _origin_from_course_event(recent_class) or _origin_from_course_event(next_class)
        if inferred_origin:
            origin = inferred_origin
    academic_signals = _rank_academic_signals(
        upcoming=upcoming,
        selection_overview=selection_overview,
        marks=marks,
        seen_grade_digest=seen_grade_digest,
        now=now,
    ) if requested == "auto" else []
    primary_signal = academic_signals[0] if academic_signals else None
    resolved = _choose_scenario(requested, recent_class, next_class, upcoming, now, primary_signal)
    kind = "dining" if resolved == "dining" else "study"

    amap = AMapClient()
    candidates = [item for item in CAMPUS_POIS if item["kind"] == kind]
    used_poi_search = False
    if amap.available and len(candidates) < 8:
        keyword = "福州大学 食堂" if kind == "dining" else "福州大学 图书馆 自习室"
        seen_names = {item["name"] for item in candidates}
        used_poi_search = True
        for item in amap.around(origin, keyword, kind):
            if item["name"] not in seen_names:
                candidates.append(item)
                seen_names.add(item["name"])

    candidate_distances = [
        (poi, _haversine_meters(origin["lat"], origin["lng"], float(poi["lat"]), float(poi["lng"])))
        for poi in candidates
    ]
    candidate_distances.sort(key=lambda item: item[1])
    route_limit = AMAP_ROUTE_CANDIDATE_LIMIT
    if used_poi_search:
        route_limit = min(route_limit, max(1, AMAP_MAX_QPS - 1))

    ranked: List[Dict[str, Any]] = []
    route_failures = 0
    for index, (poi, distance_m) in enumerate(candidate_distances):
        should_route = amap.available and index < route_limit
        route = amap.walking_route(origin, poi) if should_route else None
        if should_route and route is None:
            route_failures += 1
        walk_distance_m = route.get("distance_m") if route else None
        walk_minutes = route.get("duration_min") if route else max(3, int(math.ceil(distance_m / 80)))
        context_bonus = _candidate_context_bonus(kind, poi, now, primary_signal)
        ranked.append(
            {
                "id": poi["id"],
                "name": poi["name"],
                "kind": kind,
                "campus": poi.get("campus") or "",
                "description": poi.get("description") or "",
                "tags": poi.get("tags") or [],
                "distance_m": distance_m,
                "walk_distance_m": walk_distance_m or distance_m,
                "walk_minutes": walk_minutes,
                "route_source": route.get("source") if route else "estimated",
                "ranking_score": max(1, walk_minutes - context_bonus) * 100 + int(distance_m / 100),
                "reason": _candidate_reason(kind, poi, distance_m, route, upcoming),
                "source": poi.get("source") or "built_in",
            }
        )

    ranked.sort(key=lambda item: (item["ranking_score"], item["walk_minutes"], item["distance_m"]))
    limited = ranked[:3]
    map_status = "amap" if any(item["route_source"] == "amap" for item in limited) else "estimated"
    map_note = ""
    if not amap.available:
        map_note = "未配置高德地图 Key，已按校内地点库和直线距离估算。"
    elif route_failures:
        map_note = f"{amap.last_error or '地图路线服务暂不可用'}，部分结果已按直线距离估算。"

    title = str(primary_signal.get("title")) if primary_signal else ("附近食堂推荐" if kind == "dining" else "复习与自习建议")
    reason = _trigger_reason(kind, recent_class, next_class, upcoming, origin, now, primary_signal)

    return {
        "scenario": requested,
        "resolved_scenario": kind,
        "title": title,
        "trigger_reason": reason,
        "generated_at": now.isoformat(),
        "location_source": origin["source"],
        "location_name": origin["name"],
        "privacy_note": origin["privacy"],
        "map_status": map_status,
        "map_note": map_note,
        "edu_status": edu_status,
        "academic_context": {
            "recent_class": _compact_class_context(recent_class),
            "next_class": _compact_class_context(next_class),
            "signals": [_public_signal(signal) for signal in academic_signals[:5]],
            "grade_update": _public_grade_context(next((signal for signal in academic_signals if signal.get("type") == "grade_update"), None)),
            "course_selection": [
                _public_signal(signal)
                for signal in academic_signals
                if signal.get("type") == "course_selection"
            ][:3],
            "upcoming_exams": [
                {
                    "course_name": exam.get("course_name") or "",
                    "date": exam.get("date") or "",
                    "time": exam.get("time") or "",
                    "location": exam.get("location") or "",
                    "days_until": exam.get("days_until"),
                }
                for exam in upcoming[:3]
            ],
        },
        "recommendations": limited,
    }


def _public_signal(signal: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not signal:
        return None
    public = {
        "type": signal.get("type") or "",
        "title": signal.get("title") or "",
        "summary": signal.get("summary") or "",
        "status": signal.get("status") or "",
        "priority": signal.get("priority") or 0,
        "prompt": signal.get("prompt") or "",
    }
    for key in (
        "category",
        "category_label",
        "candidate_count",
        "time_window",
        "items",
        "recorded_count",
        "latest_semester",
        "latest_courses",
        "digest",
    ):
        if key in signal:
            public[key] = signal[key]
    return public


def _public_grade_context(signal: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not signal:
        return None
    return {
        "status": signal.get("status") or "",
        "digest": signal.get("digest") or "",
        "recorded_count": signal.get("recorded_count") or 0,
        "latest_semester": signal.get("latest_semester") or "",
        "latest_courses": signal.get("latest_courses") or [],
    }


def _compact_class_context(value: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not value:
        return None
    return {
        "name": value.get("name") or "",
        "location": value.get("location") or "",
        "start_at": value.get("start_at").isoformat() if value.get("start_at") else "",
        "end_at": value.get("end_at").isoformat() if value.get("end_at") else "",
    }


def _format_recommendation_markdown(data: Dict[str, Any]) -> str:
    lines = [f"## {data.get('title') or '校园推荐'}", "", data.get("trigger_reason") or ""]
    signals = ((data.get("academic_context") or {}).get("signals") or [])
    if signals:
        lines.extend(["", "### 今日提醒"])
        for signal in signals[:3]:
            lines.append(f"- {signal.get('title')}: {signal.get('summary')}")
    if data.get("map_note"):
        lines.extend(["", f"> {data['map_note']}"])
    lines.extend(["", "| 地点 | 步行 | 推荐理由 |", "| --- | --- | --- |"])
    for item in data.get("recommendations") or []:
        lines.append(f"| {item.get('name')} | 约 {item.get('walk_minutes')} 分钟 | {item.get('reason')} |")
    lines.extend(["", f"> {data.get('privacy_note') or '定位只用于本次推荐。'}"])
    return "\n".join(line for line in lines if line is not None)


def build_campus_recommendation_tools(request_context: Dict[str, Any] | None = None):
    request_context = request_context or {}

    @tool(response_format="content_and_artifact")
    def recommend_campus_context(
        scenario: str = "auto",
        manual_location_id: str = "",
        latitude: str = "",
        longitude: str = "",
    ) -> Tuple[str, Any]:
        """根据课表、考试、选课、成绩和当前位置生成校园情境推荐。

        如果用户没有提供明确位置，可建议用户在“隐私与数据”里开启定位与智能提醒，或让用户说明所在校区/教学楼。

        参数:
        - scenario: auto、dining 或 study
        - manual_location_id: 可选，qishan_center/qishan_teaching/qishan_dorm/yishan_center/tongpan_center
        - latitude/longitude: 可选，经用户明确提供或前端授权后才传入
        """
        lat = _safe_float(latitude)
        lng = _safe_float(longitude)
        location = {"lat": lat, "lng": lng} if lat is not None and lng is not None else None
        data = build_contextual_recommendation(
            scenario=scenario,
            location=location,
            manual_location_id=manual_location_id,
            edu_session=request_context,
        )
        return _format_recommendation_markdown(data), data

    return [recommend_campus_context]
