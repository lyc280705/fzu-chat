from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Any, Dict
from urllib.parse import urlencode, parse_qs
from uuid import uuid4

import requests

from .runtime_state import redis_delete, redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

OAUTH_STATE_TTL_SECONDS = max(60, int(os.getenv("FZU_CHAT_OAUTH_STATE_TTL_SECONDS", "600")))
OAUTH_TIMEOUT_SECONDS = float(os.getenv("FZU_CHAT_OAUTH_TIMEOUT_SECONDS", "6"))

_memory_states: Dict[str, tuple[float, Dict[str, Any]]] = {}
_memory_states_lock = Lock()


@dataclass(frozen=True)
class OAuthProviderConfig:
    key: str
    label: str
    client_id: str
    client_secret: str
    redirect_uri: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


class OAuthError(RuntimeError):
    pass


class OAuthConfigError(OAuthError):
    pass


def provider_display_name(provider: str) -> str:
    if provider == "wechat":
        return "微信"
    if provider == "qq":
        return "QQ"
    return provider


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def get_provider_config(provider: str, default_redirect_uri: str) -> OAuthProviderConfig:
    provider = provider.lower().strip()
    if provider == "wechat":
        return OAuthProviderConfig(
            key="wechat",
            label="微信",
            client_id=_env_first("FZU_CHAT_WECHAT_CLIENT_ID", "WECHAT_APP_ID"),
            client_secret=_env_first("FZU_CHAT_WECHAT_CLIENT_SECRET", "WECHAT_APP_SECRET"),
            redirect_uri=_env_first("FZU_CHAT_WECHAT_REDIRECT_URI", "WECHAT_REDIRECT_URI") or default_redirect_uri,
        )
    if provider == "qq":
        return OAuthProviderConfig(
            key="qq",
            label="QQ",
            client_id=_env_first("FZU_CHAT_QQ_CLIENT_ID", "QQ_APP_ID"),
            client_secret=_env_first("FZU_CHAT_QQ_CLIENT_SECRET", "QQ_APP_KEY", "QQ_APP_SECRET"),
            redirect_uri=_env_first("FZU_CHAT_QQ_REDIRECT_URI", "QQ_REDIRECT_URI") or default_redirect_uri,
        )
    raise OAuthConfigError("不支持的登录方式。")


def list_provider_status(default_redirect_base: str) -> list[Dict[str, Any]]:
    providers = []
    for key in ("wechat", "qq"):
        redirect_uri = f"{default_redirect_base.rstrip('/')}/{key}/callback"
        config = get_provider_config(key, redirect_uri)
        providers.append({"provider": key, "label": config.label, "configured": config.configured})
    return providers


def create_oauth_state(provider: str, redirect_uri: str) -> str:
    token = uuid4().hex + uuid4().hex
    payload = {"provider": provider, "redirect_uri": redirect_uri, "created_at": time()}
    if not redis_set_json(f"oauth_state:{token}", payload, OAUTH_STATE_TTL_SECONDS):
        with _memory_states_lock:
            _memory_states[token] = (time() + OAUTH_STATE_TTL_SECONDS, payload)
    return token


def consume_oauth_state(token: str, expected_provider: str) -> Dict[str, Any]:
    token = (token or "").strip()
    if not token:
        raise OAuthError("登录状态已失效，请重新发起登录。")

    key = f"oauth_state:{token}"
    payload = redis_get_json(key)
    if payload is not None:
        redis_delete(key)
    else:
        now = time()
        with _memory_states_lock:
            expired = [state for state, (expires_at, _) in _memory_states.items() if expires_at <= now]
            for state in expired:
                _memory_states.pop(state, None)
            entry = _memory_states.pop(token, None)
        if entry:
            payload = entry[1]

    if not payload or payload.get("provider") != expected_provider:
        raise OAuthError("登录状态已失效，请重新发起登录。")
    return payload


def build_authorization_url(config: OAuthProviderConfig, state: str) -> str:
    if not config.configured:
        raise OAuthConfigError(f"{config.label}登录尚未配置。")
    if config.key == "wechat":
        query = urlencode(
            {
                "appid": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": state,
            }
        )
        return f"https://open.weixin.qq.com/connect/qrconnect?{query}#wechat_redirect"
    if config.key == "qq":
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "scope": "get_user_info",
                "state": state,
            }
        )
        return f"https://graph.qq.com/oauth2.0/authorize?{query}"
    raise OAuthConfigError("不支持的登录方式。")


def _parse_json_or_query_response(response: requests.Response) -> Dict[str, Any]:
    text = response.text.strip()
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except ValueError:
        pass
    if text.startswith("callback(") and text.endswith(");"):
        text = text[len("callback("):-2].strip()
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            return {}
    parsed = parse_qs(text, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _provider_subject(provider: str, profile: Dict[str, Any]) -> str:
    if provider == "wechat":
        return str(profile.get("unionid") or profile.get("openid") or "").strip()
    if provider == "qq":
        return str(profile.get("openid") or "").strip()
    return ""


def _visitor_user_id(provider: str, subject: str) -> str:
    digest = hashlib.sha256(f"{provider}:{subject}".encode("utf-8")).hexdigest()[:24]
    return f"visitor_{provider}_{digest}"


def _safe_profile(provider: str, subject: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    nickname = str(profile.get("nickname") or provider_display_name(provider) + "访客").strip()
    avatar = ""
    if provider == "wechat":
        avatar = str(profile.get("headimgurl") or "").strip()
    elif provider == "qq":
        avatar = str(profile.get("figureurl_qq_2") or profile.get("figureurl_qq_1") or profile.get("figureurl_2") or "").strip()
    return {
        "user_id": _visitor_user_id(provider, subject),
        "display_name": nickname[:40] or provider_display_name(provider) + "访客",
        "avatar_url": avatar[:500],
        "provider_subject_hash": hashlib.sha256(subject.encode("utf-8")).hexdigest(),
    }


def fetch_visitor_profile(config: OAuthProviderConfig, code: str) -> Dict[str, Any]:
    code = (code or "").strip()
    if not code:
        raise OAuthError("缺少授权 code，请重新登录。")
    if config.key == "wechat":
        token_response = requests.get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            params={
                "appid": config.client_id,
                "secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        token_response.raise_for_status()
        token_payload = _parse_json_or_query_response(token_response)
        if token_payload.get("errcode"):
            raise OAuthError(str(token_payload.get("errmsg") or "微信授权失败。"))
        access_token = str(token_payload.get("access_token") or "").strip()
        openid = str(token_payload.get("openid") or "").strip()
        if not access_token or not openid:
            raise OAuthError("微信授权响应不完整。")
        profile_response = requests.get(
            "https://api.weixin.qq.com/sns/userinfo",
            params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        profile_response.raise_for_status()
        profile = _parse_json_or_query_response(profile_response)
        if profile.get("errcode"):
            raise OAuthError(str(profile.get("errmsg") or "微信用户信息获取失败。"))
        merged_profile = {**token_payload, **profile}
        subject = _provider_subject("wechat", merged_profile)
        if not subject:
            raise OAuthError("微信用户标识为空。")
        return _safe_profile("wechat", subject, merged_profile)

    if config.key == "qq":
        token_response = requests.get(
            "https://graph.qq.com/oauth2.0/token",
            params={
                "grant_type": "authorization_code",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
                "fmt": "json",
            },
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        token_response.raise_for_status()
        token_payload = _parse_json_or_query_response(token_response)
        if token_payload.get("error"):
            raise OAuthError(str(token_payload.get("error_description") or "QQ授权失败。"))
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            raise OAuthError("QQ授权响应不完整。")

        me_response = requests.get(
            "https://graph.qq.com/oauth2.0/me",
            params={"access_token": access_token, "fmt": "json"},
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        me_response.raise_for_status()
        me_payload = _parse_json_or_query_response(me_response)
        openid = str(me_payload.get("openid") or "").strip()
        if not openid:
            raise OAuthError("QQ用户标识为空。")
        profile_response = requests.get(
            "https://graph.qq.com/user/get_user_info",
            params={
                "access_token": access_token,
                "oauth_consumer_key": config.client_id,
                "openid": openid,
                "format": "json",
            },
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        profile_response.raise_for_status()
        profile = _parse_json_or_query_response(profile_response)
        if str(profile.get("ret", "0")) != "0":
            raise OAuthError(str(profile.get("msg") or "QQ用户信息获取失败。"))
        return _safe_profile("qq", openid, {**me_payload, **profile})

    raise OAuthConfigError("不支持的登录方式。")
