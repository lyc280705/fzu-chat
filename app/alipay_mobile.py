"""Short-lived, encrypted cross-browser Alipay login handoffs.

Launch tickets can start authorization, but cannot read or claim its result.
Claim needs both the original HttpOnly owner cookie and a one-time receipt
delivered only to the authorizing browser. Polling never releases that receipt.
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
DIRECT_STATE_PREFIX = "am_"
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


def prepare(redirect_uri, return_browser="system", *, direct=False):
    owner = secrets.token_hex(32)
    flow = digest(owner)
    record = {
        "flow": flow, "status": "waiting", "expires_at": time.time() + TTL,
        "redirect_uri": redirect_uri,
        "return_browser": return_browser,
    }
    if direct:
        state = DIRECT_STATE_PREFIX + secrets.token_hex(32)
        record.update(status="authorizing", direct_state=state, state_hash=digest(state))
        index_key = "alipay_mobile:state:" + digest(state)
    else:
        record["ticket"] = secrets.token_hex(32)
        index_key = "alipay_mobile:launch:" + digest(record["ticket"])
    if not _cas(_flow_key(flow), None, record):
        raise BridgeError()
    index = {"flow": flow, "expires_at": record["expires_at"]}
    if not _cas(index_key, None, index):
        raise BridgeError()
    return owner, record


def consume_direct_state(state):
    """Validate and consume the direct OAuth state before exchanging a code.

    No Alipay cookie exists when opening its official authorization URL directly.
    This callback ONLY creates an encrypted handoff; the original cookie and
    separate return receipt are still both required to create a website session.
    Normal/legacy OAuth callbacks retain their existing cookie validation.
    """
    if not state.startswith(DIRECT_STATE_PREFIX) or not _valid(state[len(DIRECT_STATE_PREFIX):]):
        raise BridgeError()
    _, index = _read("alipay_mobile:state:" + digest(state))
    key = _flow_key(index["flow"])
    raw, record = _read(key)
    if (record["status"] != "authorizing" or not record.get("direct_state")
            or not hmac.compare_digest(record.get("state_hash", ""), digest(state))):
        raise BridgeError()
    record["status"] = "exchanging"
    if not _cas(key, raw, record):
        raise BridgeError()
    return {"bridge_flow": record["flow"], "redirect_uri": record["redirect_uri"]}


def status(owner, flow):
    return _read(_owner(owner, flow))[1]


def check_launch(ticket):
    if not _valid(ticket):
        raise BridgeError()
    _, index = _read("alipay_mobile:launch:" + digest(ticket))
    _, record = _read(_flow_key(index["flow"]))
    if record["status"] != "waiting":
        raise BridgeError("授权已开始或已结束，请返回原浏览器查看。", 409)
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
    expected_status = "exchanging" if record.get("direct_state") else "authorizing"
    if record["status"] != expected_status or not hmac.compare_digest(record.get("state_hash", ""), digest(state)):
        raise BridgeError()
    record.update(status="ready" if profile else error)
    receipt = secrets.token_hex(32) if profile else ""
    if profile:
        record["profile"] = profile  # Encrypted before any storage, never a token.
        record["receipt_hash"] = digest(receipt)
    record.pop("ticket", None)
    record.pop("verification_code", None)
    record.pop("direct_state", None)
    if not _cas(key, raw, record):
        raise BridgeError()
    return {"flow": flow, "receipt": receipt, "browser": record.get("return_browser", "system")}


def claim(owner, flow, receipt):
    key = _owner(owner, flow)
    raw, record = _read(key)
    if record["status"] != "ready":
        raise BridgeError("尚未授权或结果已领取，请重新检查。", 409)
    if not _valid(receipt) or not hmac.compare_digest(record.get("receipt_hash", ""), digest(receipt)):
        raise BridgeError("请使用支付宝授权完成后的返回按钮继续登录。", 403)
    profile = record.pop("profile")
    record.pop("receipt_hash", None)
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
