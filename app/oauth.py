from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Any, Dict
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

import requests

from .runtime_state import redis_delete, redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

OAUTH_PROVIDER_KEYS = ("wechat", "qq", "microsoft", "apple", "github")
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
    labels = {
        "wechat": "微信",
        "qq": "QQ",
        "microsoft": "Microsoft",
        "apple": "Apple",
        "github": "GitHub",
    }
    return labels.get(provider, provider)


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _normalise_provider(provider: str) -> str:
    provider = (provider or "").lower().strip()
    aliases = {
        "ms": "microsoft",
        "azure": "microsoft",
        "azuread": "microsoft",
        "github.com": "github",
    }
    return aliases.get(provider, provider)


def visible_provider_keys() -> list[str]:
    configured = _env_first("FZU_CHAT_OAUTH_PROVIDERS", "FZU_CHAT_OAUTH_VISIBLE_PROVIDERS")
    if not configured:
        return list(OAUTH_PROVIDER_KEYS)
    providers: list[str] = []
    for raw in configured.replace(";", ",").split(","):
        provider = _normalise_provider(raw)
        if not provider:
            continue
        if provider not in OAUTH_PROVIDER_KEYS:
            logger.warning("Ignoring unsupported OAuth provider in FZU_CHAT_OAUTH_PROVIDERS: %s", raw)
            continue
        if provider not in providers:
            providers.append(provider)
    return providers


def get_provider_config(provider: str, default_redirect_uri: str) -> OAuthProviderConfig:
    provider = _normalise_provider(provider)
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
    if provider == "microsoft":
        return OAuthProviderConfig(
            key="microsoft",
            label="Microsoft",
            client_id=_env_first("FZU_CHAT_MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_ID"),
            client_secret=_env_first("FZU_CHAT_MICROSOFT_CLIENT_SECRET", "MICROSOFT_CLIENT_SECRET"),
            redirect_uri=_env_first("FZU_CHAT_MICROSOFT_REDIRECT_URI", "MICROSOFT_REDIRECT_URI") or default_redirect_uri,
        )
    if provider == "apple":
        return OAuthProviderConfig(
            key="apple",
            label="Apple",
            client_id=_env_first("FZU_CHAT_APPLE_CLIENT_ID", "APPLE_CLIENT_ID"),
            client_secret=_env_first("FZU_CHAT_APPLE_CLIENT_SECRET", "APPLE_CLIENT_SECRET"),
            redirect_uri=_env_first("FZU_CHAT_APPLE_REDIRECT_URI", "APPLE_REDIRECT_URI") or default_redirect_uri,
        )
    if provider == "github":
        return OAuthProviderConfig(
            key="github",
            label="GitHub",
            client_id=_env_first("FZU_CHAT_GITHUB_CLIENT_ID", "GITHUB_CLIENT_ID"),
            client_secret=_env_first("FZU_CHAT_GITHUB_CLIENT_SECRET", "GITHUB_CLIENT_SECRET"),
            redirect_uri=_env_first("FZU_CHAT_GITHUB_REDIRECT_URI", "GITHUB_REDIRECT_URI") or default_redirect_uri,
        )
    raise OAuthConfigError("不支持的登录方式。")


def list_provider_status(default_redirect_base: str) -> list[Dict[str, Any]]:
    providers = []
    for key in visible_provider_keys():
        redirect_uri = f"{default_redirect_base.rstrip('/')}/{key}/callback"
        config = get_provider_config(key, redirect_uri)
        providers.append({"provider": key, "label": config.label, "configured": config.configured})
    return providers


def create_oauth_state(provider: str, redirect_uri: str) -> str:
    token = uuid4().hex + uuid4().hex
    payload = {"provider": _normalise_provider(provider), "redirect_uri": redirect_uri, "created_at": time()}
    if not redis_set_json(f"oauth_state:{token}", payload, OAUTH_STATE_TTL_SECONDS):
        with _memory_states_lock:
            _memory_states[token] = (time() + OAUTH_STATE_TTL_SECONDS, payload)
    return token


def consume_oauth_state(token: str, expected_provider: str) -> Dict[str, Any]:
    token = (token or "").strip()
    expected_provider = _normalise_provider(expected_provider)
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
    if config.key == "microsoft":
        tenant = _env_first("FZU_CHAT_MICROSOFT_TENANT", "MICROSOFT_TENANT") or "common"
        query = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "response_mode": "query",
                "scope": "openid profile email",
                "state": state,
                "prompt": "select_account",
            }
        )
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{query}"
    if config.key == "apple":
        query = urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code id_token",
                "response_mode": "form_post",
                "scope": "name email",
                "state": state,
            }
        )
        return f"https://appleid.apple.com/auth/authorize?{query}"
    if config.key == "github":
        query = urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "scope": "read:user user:email",
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"
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


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = (token or "").split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (binascii.Error, ValueError, TypeError):
        return {}


def _provider_subject(provider: str, profile: Dict[str, Any]) -> str:
    if provider == "wechat":
        return str(profile.get("unionid") or profile.get("openid") or "").strip()
    if provider == "qq":
        return str(profile.get("openid") or "").strip()
    if provider == "microsoft":
        return str(profile.get("sub") or profile.get("oid") or profile.get("id") or "").strip()
    if provider == "apple":
        return str(profile.get("sub") or "").strip()
    if provider == "github":
        return str(profile.get("id") or "").strip()
    return ""


def _visitor_user_id(provider: str, subject: str) -> str:
    digest = hashlib.sha256(f"{provider}:{subject}".encode("utf-8")).hexdigest()[:24]
    return f"visitor_{provider}_{digest}"


def _display_name_from_apple_user(user_payload: Dict[str, Any]) -> str:
    name = user_payload.get("name")
    if not isinstance(name, dict):
        return ""
    parts = [
        str(name.get("firstName") or "").strip(),
        str(name.get("lastName") or "").strip(),
    ]
    return " ".join(part for part in parts if part).strip()


def _safe_profile(provider: str, subject: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    label = provider_display_name(provider)
    nickname = str(
        profile.get("nickname")
        or profile.get("name")
        or profile.get("login")
        or profile.get("email")
        or f"{label}访客"
    ).strip()
    avatar = ""
    if provider == "wechat":
        avatar = str(profile.get("headimgurl") or "").strip()
    elif provider == "qq":
        avatar = str(profile.get("figureurl_qq_2") or profile.get("figureurl_qq_1") or profile.get("figureurl_2") or "").strip()
    elif provider == "microsoft":
        avatar = str(profile.get("picture") or "").strip()
    elif provider == "github":
        avatar = str(profile.get("avatar_url") or "").strip()
    return {
        "user_id": _visitor_user_id(provider, subject),
        "display_name": nickname[:40] or f"{label}访客",
        "avatar_url": avatar[:500],
        "provider_subject_hash": hashlib.sha256(subject.encode("utf-8")).hexdigest(),
    }


def _token_post(url: str, data: Dict[str, str]) -> Dict[str, Any]:
    response = requests.post(
        url,
        data=data,
        headers={"Accept": "application/json", "User-Agent": "fzu-chat"},
        timeout=OAUTH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse_json_or_query_response(response)


def _find_github_primary_email(access_token: str) -> str:
    response = requests.get(
        "https://api.github.com/user/emails",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "fzu-chat",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=OAUTH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    emails = response.json()
    if not isinstance(emails, list):
        return ""
    primary = next((item for item in emails if isinstance(item, dict) and item.get("primary") and item.get("verified")), None)
    fallback = next((item for item in emails if isinstance(item, dict) and item.get("verified")), None)
    chosen = primary or fallback
    return str((chosen or {}).get("email") or "").strip()


def fetch_visitor_profile(
    config: OAuthProviderConfig,
    code: str,
    callback_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    code = (code or "").strip()
    callback_payload = callback_payload or {}
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

    if config.key == "microsoft":
        tenant = _env_first("FZU_CHAT_MICROSOFT_TENANT", "MICROSOFT_TENANT") or "common"
        token_payload = _token_post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_payload.get("error"):
            raise OAuthError(str(token_payload.get("error_description") or "Microsoft 授权失败。"))
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            raise OAuthError("Microsoft 授权响应不完整。")
        user_response = requests.get(
            "https://graph.microsoft.com/oidc/userinfo",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        user_response.raise_for_status()
        profile = _parse_json_or_query_response(user_response)
        id_token_claims = _decode_jwt_payload(str(token_payload.get("id_token") or ""))
        merged_profile = {**id_token_claims, **profile}
        subject = _provider_subject("microsoft", merged_profile)
        if not subject:
            raise OAuthError("Microsoft 用户标识为空。")
        return _safe_profile("microsoft", subject, merged_profile)

    if config.key == "apple":
        token_payload = _token_post(
            "https://appleid.apple.com/auth/token",
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_payload.get("error"):
            raise OAuthError(str(token_payload.get("error_description") or "Apple 授权失败。"))
        id_token_claims = _decode_jwt_payload(str(token_payload.get("id_token") or callback_payload.get("id_token") or ""))
        raw_user = callback_payload.get("user")
        user_payload: Dict[str, Any] = {}
        if isinstance(raw_user, str) and raw_user.strip():
            try:
                parsed_user = json.loads(raw_user)
                user_payload = parsed_user if isinstance(parsed_user, dict) else {}
            except ValueError:
                user_payload = {}
        apple_name = _display_name_from_apple_user(user_payload)
        merged_profile = {
            **id_token_claims,
            "name": apple_name or id_token_claims.get("email") or provider_display_name("apple") + "访客",
        }
        subject = _provider_subject("apple", merged_profile)
        if not subject:
            raise OAuthError("Apple 用户标识为空。")
        return _safe_profile("apple", subject, merged_profile)

    if config.key == "github":
        token_payload = _token_post(
            "https://github.com/login/oauth/access_token",
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
        if token_payload.get("error"):
            raise OAuthError(str(token_payload.get("error_description") or "GitHub 授权失败。"))
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            raise OAuthError("GitHub 授权响应不完整。")
        user_response = requests.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "fzu-chat",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=OAUTH_TIMEOUT_SECONDS,
        )
        user_response.raise_for_status()
        profile = _parse_json_or_query_response(user_response)
        if not profile.get("email"):
            email = _find_github_primary_email(access_token)
            if email:
                profile["email"] = email
        subject = _provider_subject("github", profile)
        if not subject:
            raise OAuthError("GitHub 用户标识为空。")
        return _safe_profile("github", subject, profile)

    raise OAuthConfigError("不支持的登录方式。")
