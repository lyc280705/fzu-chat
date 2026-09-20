"""Minimal Alipay OAuth transport: RSA2 requests and fail-closed response verification.

Only the two identity APIs are supported. Tokens and complete gateway responses
must never be logged or persisted. Keys are read from server-only secret files.
"""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

GATEWAY_URL = "https://openapi.alipay.com/gateway.do"
ALLOWED_METHODS = {"alipay.system.oauth.token", "alipay.user.info.share"}


class AlipayError(RuntimeError):
    pass


class AlipayConfigError(AlipayError):
    pass


def load_keys(private_key_file: str, public_key_file: str) -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    try:
        private_data = Path(private_key_file).read_bytes()
        public_data = Path(public_key_file).read_bytes().strip()
        private_key = serialization.load_pem_private_key(private_data, password=None)
        if public_data.startswith(b"-----BEGIN PUBLIC KEY-----"):
            public_key = serialization.load_pem_public_key(public_data)
        else:
            public_key = serialization.load_der_public_key(base64.b64decode(b"".join(public_data.split()), validate=True))
        if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(public_key, rsa.RSAPublicKey):
            raise ValueError("RSA keys required")
        if min(private_key.key_size, public_key.key_size) < 2048:
            raise ValueError("RSA2 keys must be at least 2048 bits")
        return private_key, public_key
    except (OSError, ValueError, TypeError, binascii.Error) as exc:
        raise AlipayConfigError("支付宝密钥配置不可用。") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _response_members(raw: str) -> dict[str, tuple[Any, str]]:
    """Decode top-level values while retaining their exact signed JSON bytes.

    Re-serializing JSON changes escaping, whitespace and potentially key order.
    Decode with strict duplicate rejection, then scan only top-level members.
    """
    decoder = json.JSONDecoder(object_pairs_hook=_unique_object)
    parsed = decoder.decode(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    members = {}
    pos = raw.index("{") + 1
    while True:
        while raw[pos].isspace():
            pos += 1
        if raw[pos] == "}":
            break
        key, pos = decoder.raw_decode(raw, pos)
        while raw[pos].isspace():
            pos += 1
        pos += 1  # Colon, already validated by decoder.decode above.
        while raw[pos].isspace():
            pos += 1
        start = pos
        value, pos = decoder.raw_decode(raw, pos)
        members[key] = (value, raw[start:pos])
        while raw[pos].isspace():
            pos += 1
        if raw[pos] == "}":
            break
        pos += 1  # Comma.
    return members


def verify_response(raw: str, method: str, public_key: rsa.RSAPublicKey) -> dict[str, Any]:
    try:
        members = _response_members(raw)
        response_key = method.replace(".", "_") + "_response"
        # Gateway errors (including unsigned ones) are never identity evidence.
        if "error_response" in members:
            raise AlipayError("支付宝授权请求未成功，请确认应用已上线后重试。")
        payload, signed_text = members[response_key]
        signature = base64.b64decode(members["sign"][0], validate=True)
        public_key.verify(signature, signed_text.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        if not isinstance(payload, dict):
            raise ValueError("Expected response object")
        if str(payload.get("code", "10000")) != "10000":
            raise AlipayError("支付宝授权失败，请重新发起登录。")
        return payload
    except (InvalidSignature, ValueError, TypeError, KeyError, IndexError, binascii.Error) as exc:
        raise AlipayError("支付宝响应验签失败，请重新登录。") from exc


def gateway_request(
    app_id: str,
    method: str,
    params: dict[str, str],
    private_key: rsa.RSAPrivateKey,
    public_key: rsa.RSAPublicKey,
    timeout: float,
) -> dict[str, Any]:
    if method not in ALLOWED_METHODS:
        raise AlipayError("不支持的支付宝接口。")
    data = {
        **params,
        "app_id": app_id,
        "method": method,
        "format": "json",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
    }
    content = "&".join(f"{key}={value}" for key, value in sorted(data.items()) if value and key != "sign")
    data["sign"] = base64.b64encode(private_key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    response = requests.post(
        GATEWAY_URL, data=data, timeout=timeout, allow_redirects=False,
        headers={"Accept": "application/json", "User-Agent": "fzu-chat"},
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise AlipayError("支付宝返回了非预期响应。")
    # Alipay is explicitly requested to sign UTF-8, not requests' default charset.
    try:
        raw = response.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AlipayError("支付宝响应编码不正确。") from exc
    return verify_response(raw, method, public_key)


def fetch_identity(app_id: str, code: str, private_key_file: str, public_key_file: str, timeout: float) -> dict[str, str]:
    private_key, public_key = load_keys(private_key_file, public_key_file)
    token = gateway_request(app_id, "alipay.system.oauth.token", {
        "grant_type": "authorization_code", "code": code,
    }, private_key, public_key, timeout)
    access_token = str(token.get("access_token") or "").strip()
    # New applications use open_id. Do not use deprecated alipay_user_id or
    # callback query identifiers as identity evidence.
    id_field = "open_id" if token.get("open_id") else "user_id"
    subject = str(token.get(id_field) or "").strip()
    if not access_token or not subject:
        raise AlipayError("支付宝授权响应不完整。")
    profile = gateway_request(app_id, "alipay.user.info.share", {
        "auth_token": access_token,
    }, private_key, public_key, timeout)
    if str(profile.get(id_field) or "").strip() != subject:
        raise AlipayError("支付宝用户信息不一致，请重新登录。")
    avatar = str(profile.get("avatar") or "").strip()
    return {
        "subject": subject,
        "nickname": str(profile.get("nick_name") or "支付宝访客").strip()[:40],
        "avatar": avatar[:500] if avatar.startswith("https://") else "",
    }
