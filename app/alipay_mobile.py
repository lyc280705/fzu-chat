"""Short-lived, encrypted cross-browser Alipay login handoffs.

Launch tickets can start authorization, but cannot read or claim its result.
Only the originating browser's separate HttpOnly owner cookie can do that.
All transitions use compare-and-set; cancellation/consumption cannot be undone.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import time
from threading import Lock

from .runtime_state import get_redis_client, redis_configured
from .session_crypto import open_session, seal_session

TTL = 300
OWNER_COOKIE = "fzu_alipay_mobile_owner"
COOKIE_PATH = "/api/auth/oauth/alipay"
_memory: dict[str, str] = {}
_lock = Lock()
_CAS = """
local old = redis.call('GET', KEYS[1])
if (ARGV[1] == '' and old) or (ARGV[1] ~= '' and old ~= ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


class BridgeError(RuntimeError):
    def __init__(self, message="本次登录已失效，请返回原浏览器重新发起。", status_code=410):
        super().__init__(message)
        self.status_code = status_code


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _valid(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _client():
    client = get_redis_client()
    if client is None and redis_configured():
        raise BridgeError("登录中转暂不可用，请稍后重试。", 503)
    return client


def _decode(raw):
    value = open_session(json.loads(raw)) if raw else None
    if not value or value.get("expires_at", 0) <= time.time():
        raise BridgeError()
    return value


def _read(key):
    client = _client()
    try:
        if client is not None:
            raw = client.get(key)
        else:
            with _lock:
                raw = _memory.get(key)
        return raw, _decode(raw)
    except BridgeError:
        raise
    except Exception as exc:
        raise BridgeError("登录中转暂不可用，请稍后重试。", 503) from exc


def _cas(key, old, value):
    ttl = math.ceil(value["expires_at"] - time.time())
    if ttl <= 0:
        raise BridgeError()
    encoded = json.dumps(seal_session(value), separators=(",", ":"))
    client = _client()
    try:
        if client is not None:
            return bool(client.eval(_CAS, 1, key, old or "", encoded, ttl))
        with _lock:
            for expired_key, raw in list(_memory.items()):
                try:
                    _decode(raw)
                except BridgeError:
                    _memory.pop(expired_key, None)
            if _memory.get(key) != old:
                return False
            _memory[key] = encoded
            return True
    except BridgeError:
        raise
    except Exception as exc:
        raise BridgeError("登录中转暂不可用，请稍后重试。", 503) from exc


def _flow_key(flow):
    if not _valid(flow):
        raise BridgeError()
    return "alipay_mobile:flow:" + flow


def _owner(owner, flow):
    if not _valid(owner) or not _valid(flow) or not hmac.compare_digest(digest(owner), flow):
        raise BridgeError("请在最初发起登录的浏览器中继续。", 403)
    return _flow_key(flow)


def prepare(redirect_uri):
    owner = secrets.token_hex(32)
    flow = digest(owner)
    ticket = secrets.token_hex(32)
    record = {
        "flow": flow, "status": "waiting", "expires_at": time.time() + TTL,
        "redirect_uri": redirect_uri, "ticket": ticket,
        "verification_code": f"{secrets.randbelow(1000000):06d}",
    }
    if not _cas(_flow_key(flow), None, record):
        raise BridgeError()
    index = {"flow": flow, "expires_at": record["expires_at"]}
    if not _cas("alipay_mobile:launch:" + digest(ticket), None, index):
        raise BridgeError()
    return owner, record


def status(owner, flow):
    return _read(_owner(owner, flow))[1]


def check_launch(ticket, code):
    if not _valid(ticket):
        raise BridgeError()
    _, index = _read("alipay_mobile:launch:" + digest(ticket))
    _, record = _read(_flow_key(index["flow"]))
    if record["status"] != "waiting":
        raise BridgeError("授权已开始或已结束，请返回原浏览器查看。", 409)
    if not hmac.compare_digest(record["verification_code"].encode(), code.encode()):
        raise BridgeError("确认码不正确，请输入原浏览器显示的六位数字。", 400)
    return record


def authorize(flow, state):
    key = _flow_key(flow)
    raw, record = _read(key)
    if record["status"] != "waiting":
        raise BridgeError()
    record.update(status="authorizing", state_hash=digest(state))
    if not _cas(key, raw, record):
        raise BridgeError()


def finish(flow, state, profile=None, error="failed"):
    key = _flow_key(flow)
    raw, record = _read(key)
    if record["status"] != "authorizing" or not hmac.compare_digest(record.get("state_hash", ""), digest(state)):
        raise BridgeError()
    record.update(status="ready" if profile else error)
    if profile:
        record["profile"] = profile  # Encrypted before any storage, never a token.
    record.pop("ticket", None)
    record.pop("verification_code", None)
    if not _cas(key, raw, record):
        raise BridgeError()


def claim(owner, flow):
    key = _owner(owner, flow)
    raw, record = _read(key)
    if record["status"] != "ready":
        raise BridgeError("尚未授权或结果已领取，请重新检查。", 409)
    profile = record.pop("profile")
    record["status"] = "consumed"
    if not _cas(key, raw, record):
        raise BridgeError("本次登录结果已领取。", 409)
    return profile


def cancel(owner, flow):
    key = _owner(owner, flow)
    for _ in range(3):
        raw, record = _read(key)
        record = {"flow": flow, "status": "cancelled", "expires_at": record["expires_at"]}
        if _cas(key, raw, record):
            return
    raise BridgeError("状态已更新，请重试取消。", 409)
