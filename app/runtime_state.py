from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("FZU_CHAT_REDIS_URL", "").strip()
DEFAULT_SLOT_TTL_SECONDS = max(10, int(os.getenv("FZU_CHAT_SLOT_TTL_SECONDS", "600")))

_redis_client: Any | None = None
_redis_checked = False
_redis_last_failure_at = 0.0
_redis_lock = Lock()

_metrics_lock = Lock()
_counters: Dict[str, float] = {}
_request_counts: Dict[tuple[str, str, str], int] = {}
_request_duration_sum: Dict[tuple[str, str, str], float] = {}
_request_duration_count: Dict[tuple[str, str, str], int] = {}
_gauges: Dict[str, float] = {}

_memory_rate_buckets: Dict[str, tuple[int, float]] = {}
_memory_rate_lock = Lock()
_memory_locks: Dict[str, float] = {}
_memory_slots: Dict[str, int] = {}
_memory_state_lock = Lock()


@dataclass(frozen=True)
class SlotLease:
    name: str
    keys: tuple[str, ...]
    redis_backed: bool


def redis_configured() -> bool:
    return bool(REDIS_URL)


def get_redis_client() -> Any | None:
    global _redis_checked, _redis_client, _redis_last_failure_at
    if not REDIS_URL:
        return None
    with _redis_lock:
        if _redis_checked and _redis_client is not None:
            return _redis_client
        if _redis_checked and time.time() - _redis_last_failure_at < 5:
            return None
        _redis_checked = True
        try:
            import redis  # type: ignore

            client = redis.Redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
            )
            client.ping()
            _redis_client = client
        except Exception as exc:
            _redis_client = None
            _redis_last_failure_at = time.time()
            increment_counter("fzu_chat_redis_errors_total")
            logger.warning("Redis unavailable, falling back to process memory: %s", type(exc).__name__)
        return _redis_client


def redis_health() -> Dict[str, Any]:
    if not REDIS_URL:
        return {"configured": False, "ok": True, "detail": "disabled"}
    client = get_redis_client()
    if client is None:
        return {"configured": True, "ok": False, "detail": "unavailable"}
    try:
        client.ping()
    except Exception as exc:
        increment_counter("fzu_chat_redis_errors_total")
        return {"configured": True, "ok": False, "detail": type(exc).__name__}
    return {"configured": True, "ok": True, "detail": "ok"}


def redis_get_json(key: str) -> Dict[str, Any] | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        increment_counter("fzu_chat_redis_errors_total")
        logger.warning("Redis JSON get failed for %s: %s", key, type(exc).__name__)
        return None


def redis_set_json(key: str, value: Dict[str, Any], ttl_seconds: int) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
        return True
    except Exception as exc:
        increment_counter("fzu_chat_redis_errors_total")
        logger.warning("Redis JSON set failed for %s: %s", key, type(exc).__name__)
        return False


def redis_delete(key: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.delete(key)
        return True
    except Exception as exc:
        increment_counter("fzu_chat_redis_errors_total")
        logger.warning("Redis delete failed for %s: %s", key, type(exc).__name__)
        return False


def fixed_window_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    client = get_redis_client()
    redis_key = f"rate:{key}"
    if client is not None:
        try:
            count = int(client.incr(redis_key))
            if count == 1:
                client.expire(redis_key, window_seconds)
            return count <= limit
        except Exception as exc:
            increment_counter("fzu_chat_redis_errors_total")
            logger.warning("Redis rate limit failed for %s: %s", key, type(exc).__name__)

    now = time.time()
    with _memory_rate_lock:
        count, reset_at = _memory_rate_buckets.get(key, (0, now + window_seconds))
        if now >= reset_at:
            count = 0
            reset_at = now + window_seconds
        count += 1
        _memory_rate_buckets[key] = (count, reset_at)
        return count <= limit


def acquire_dedupe_lock(name: str, ttl_seconds: int) -> bool:
    client = get_redis_client()
    key = f"lock:{name}"
    if client is not None:
        try:
            return bool(client.set(key, "1", nx=True, ex=ttl_seconds))
        except Exception as exc:
            increment_counter("fzu_chat_redis_errors_total")
            logger.warning("Redis lock failed for %s: %s", name, type(exc).__name__)

    now = time.time()
    with _memory_state_lock:
        expired = [lock_name for lock_name, expires_at in _memory_locks.items() if expires_at <= now]
        for lock_name in expired:
            _memory_locks.pop(lock_name, None)
        if name in _memory_locks:
            return False
        _memory_locks[name] = now + ttl_seconds
        return True


def acquire_slot(name: str, limit: int, ttl_seconds: int = DEFAULT_SLOT_TTL_SECONDS) -> SlotLease | None:
    limit = max(1, int(limit))
    key = f"slot:{name}"
    client = get_redis_client()
    if client is not None:
        script = """
        local current = tonumber(redis.call('GET', KEYS[1]) or '0')
        if current >= tonumber(ARGV[1]) then
            return 0
        end
        redis.call('INCR', KEYS[1])
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        return 1
        """
        try:
            if int(client.eval(script, 1, key, limit, ttl_seconds)) == 1:
                return SlotLease(name=name, keys=(key,), redis_backed=True)
            return None
        except Exception as exc:
            increment_counter("fzu_chat_redis_errors_total")
            logger.warning("Redis slot acquire failed for %s: %s", name, type(exc).__name__)

    with _memory_state_lock:
        current = _memory_slots.get(key, 0)
        if current >= limit:
            return None
        _memory_slots[key] = current + 1
    return SlotLease(name=name, keys=(key,), redis_backed=False)


def acquire_pair_slot(
    name: str,
    first_name: str,
    first_limit: int,
    second_name: str,
    second_limit: int,
    ttl_seconds: int = DEFAULT_SLOT_TTL_SECONDS,
) -> SlotLease | None:
    first_limit = max(1, int(first_limit))
    second_limit = max(1, int(second_limit))
    first_key = f"slot:{first_name}"
    second_key = f"slot:{second_name}"
    client = get_redis_client()
    if client is not None:
        script = """
        local first_current = tonumber(redis.call('GET', KEYS[1]) or '0')
        local second_current = tonumber(redis.call('GET', KEYS[2]) or '0')
        if first_current >= tonumber(ARGV[1]) or second_current >= tonumber(ARGV[2]) then
            return 0
        end
        redis.call('INCR', KEYS[1])
        redis.call('INCR', KEYS[2])
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
        redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3]))
        return 1
        """
        try:
            acquired = int(client.eval(script, 2, first_key, second_key, first_limit, second_limit, ttl_seconds))
            if acquired == 1:
                return SlotLease(name=name, keys=(first_key, second_key), redis_backed=True)
            return None
        except Exception as exc:
            increment_counter("fzu_chat_redis_errors_total")
            logger.warning("Redis pair slot acquire failed for %s: %s", name, type(exc).__name__)

    with _memory_state_lock:
        first_current = _memory_slots.get(first_key, 0)
        second_current = _memory_slots.get(second_key, 0)
        if first_current >= first_limit or second_current >= second_limit:
            return None
        _memory_slots[first_key] = first_current + 1
        _memory_slots[second_key] = second_current + 1
    return SlotLease(name=name, keys=(first_key, second_key), redis_backed=False)


def release_slot(lease: SlotLease | None) -> None:
    if lease is None:
        return
    if lease.redis_backed:
        client = get_redis_client()
        if client is not None:
            script = """
            for i, key in ipairs(KEYS) do
                local current = tonumber(redis.call('GET', key) or '0')
                if current <= 1 then
                    redis.call('DEL', key)
                else
                    redis.call('DECR', key)
                end
            end
            return 1
            """
            try:
                client.eval(script, len(lease.keys), *lease.keys)
                return
            except Exception as exc:
                increment_counter("fzu_chat_redis_errors_total")
                logger.warning("Redis slot release failed for %s: %s", lease.name, type(exc).__name__)

    with _memory_state_lock:
        for key in lease.keys:
            current = _memory_slots.get(key, 0)
            if current <= 1:
                _memory_slots.pop(key, None)
            else:
                _memory_slots[key] = current - 1


def increment_counter(name: str, amount: float = 1.0) -> None:
    with _metrics_lock:
        _counters[name] = _counters.get(name, 0.0) + amount


def set_gauge(name: str, value: float) -> None:
    with _metrics_lock:
        _gauges[name] = float(value)


def record_http_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    key = (method.upper(), route, str(status_code))
    with _metrics_lock:
        _request_counts[key] = _request_counts.get(key, 0) + 1
        _request_duration_sum[key] = _request_duration_sum.get(key, 0.0) + max(0.0, duration_seconds)
        _request_duration_count[key] = _request_duration_count.get(key, 0) + 1


def metrics_snapshot() -> Dict[str, Any]:
    with _metrics_lock:
        return {
            "counters": dict(_counters),
            "gauges": dict(_gauges),
            "request_counts": dict(_request_counts),
            "request_duration_sum": dict(_request_duration_sum),
            "request_duration_count": dict(_request_duration_count),
        }


def render_prometheus_metrics() -> str:
    snapshot = metrics_snapshot()
    lines: list[str] = []
    for name, value in sorted(snapshot["counters"].items()):
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value:.0f}")
    for name, value in sorted(snapshot["gauges"].items()):
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")
    lines.append("# TYPE fzu_chat_http_requests_total counter")
    for (method, route, status), value in sorted(snapshot["request_counts"].items()):
        lines.append(
            'fzu_chat_http_requests_total{method="%s",route="%s",status="%s"} %d'
            % (method, route, status, value)
        )
    lines.append("# TYPE fzu_chat_http_request_duration_seconds_sum counter")
    for (method, route, status), value in sorted(snapshot["request_duration_sum"].items()):
        lines.append(
            'fzu_chat_http_request_duration_seconds_sum{method="%s",route="%s",status="%s"} %.6f'
            % (method, route, status, value)
        )
    lines.append("# TYPE fzu_chat_http_request_duration_seconds_count counter")
    for (method, route, status), value in sorted(snapshot["request_duration_count"].items()):
        lines.append(
            'fzu_chat_http_request_duration_seconds_count{method="%s",route="%s",status="%s"} %d'
            % (method, route, status, value)
        )
    return "\n".join(lines) + "\n"
