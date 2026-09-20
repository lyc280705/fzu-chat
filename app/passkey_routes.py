"""HTTP boundaries for anonymous passkey signup/login and signed-in key management."""
import json
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import passkeys
from .auth import create_session, update_session, invalidate_session
from .runtime_state import fixed_window_rate_limit


class Begin(BaseModel):
    accepted_legal: bool = False
    enroll: bool = False


class Verify(BaseModel):
    credential: dict
    name: str = Field(default="我的通行密钥", min_length=1, max_length=40)


class Remove(BaseModel):
    credential_id: str = Field(min_length=1, max_length=2048)


def install_passkey_routes(app, require_auth, request_origin, secure_cookie, set_auth_cookie, auth_cookie_name, client_ip):
    def integrity(request):
        if request_origin(request) != passkeys.ORIGIN or request.headers.get("x-fzu-passkey") != "1":
            raise HTTPException(403, "请从本站正式域名使用通行密钥。")
        if request.method != "GET" and (request.headers.get("origin") != passkeys.ORIGIN
                or request.headers.get("content-type", "").split(";")[0] != "application/json"):
            raise HTTPException(403, "请求来源无效。")

    def limited(request, suffix=""):
        integrity(request)
        if not fixed_window_rate_limit("passkey:" + client_ip(request) + suffix, 20, 300):
            raise HTTPException(429, "尝试过于频繁，请稍后再试。")

    def ceremony_response(cookie, options, request):
        response = JSONResponse(options)
        response.set_cookie(passkeys.COOKIE, cookie, max_age=passkeys.TTL, path=passkeys.COOKIE_PATH,
                            httponly=True, secure=secure_cookie(request), samesite="strict")
        return response

    @app.post("/api/auth/passkey/register/options")
    def register_options(body: Begin, request: Request):
        limited(request, ":register")
        if not body.accepted_legal:
            raise HTTPException(400, "请先阅读并同意用户协议与隐私政策。")
        token = request.cookies.get(auth_cookie_name, "") if body.enroll else ""
        if body.enroll and not token:
            raise HTTPException(401, "请先登录。")
        try:
            cookie, options = passkeys.store.register_options(token=token, old_cookie=request.cookies.get(passkeys.COOKIE, ""))
        except passkeys.PasskeyError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return ceremony_response(cookie, options, request)

    @app.post("/api/auth/passkey/login/options")
    def login_options(body: Begin, request: Request):
        limited(request, ":login")
        if not body.accepted_legal:
            raise HTTPException(400, "请先阅读并同意用户协议与隐私政策。")
        cookie, options = passkeys.store.login_options(request.cookies.get(passkeys.COOKIE, ""))
        return ceremony_response(cookie, options, request)

    def verify(body, request, registering):
        limited(request, ":verify")
        if len(json.dumps(body.credential)) > 65536:
            raise HTTPException(413, "通行密钥响应过大。")
        created = []
        def session_for(profile):
            token = create_session(profile["user_id"], profile["student_type"], profile["display_name"], edu_authenticated=False)
            created.append(token)
            update_session(token, {k: profile.get(k, "") for k in ("auth_provider", "provider_subject_hash", "avatar_url")})
            return token
        try:
            cookie = request.cookies.get(passkeys.COOKIE, "")
            if registering:
                token = passkeys.store.register(cookie, body.credential, request.cookies.get(auth_cookie_name, ""), body.name.strip() or "通行密钥", session_for)
            else:
                token = passkeys.store.login(cookie, body.credential, session_for)
            response = JSONResponse({"ok": True})
            if token:
                old = request.cookies.get(auth_cookie_name)
                if old:
                    invalidate_session(old)
                set_auth_cookie(response, token, request)
        except Exception as exc:
            for token in created:
                invalidate_session(token)
            # Never log client data, biometric assertions, credential IDs or keys.
            response = JSONResponse({"detail": str(exc) if isinstance(exc, passkeys.PasskeyError)
                                     else "通行密钥验证失败，请重新尝试。"},
                                    status_code=exc.status if isinstance(exc, passkeys.PasskeyError) else 400)
        response.delete_cookie(passkeys.COOKIE, path=passkeys.COOKIE_PATH, httponly=True,
                               secure=secure_cookie(request), samesite="strict")
        return response

    @app.post("/api/auth/passkey/register/verify")
    def register_verify(body: Verify, request: Request):
        return verify(body, request, True)

    @app.post("/api/auth/passkey/login/verify")
    def login_verify(body: Verify, request: Request):
        return verify(body, request, False)

    @app.get("/api/auth/passkey/credentials")
    def list_credentials(request: Request, user=Depends(require_auth)):
        integrity(request)
        return passkeys.store.list_keys(user.user_id)

    @app.delete("/api/auth/passkey/credentials")
    def delete_credential(body: Remove, request: Request, user=Depends(require_auth)):
        limited(request, ":delete")
        try:
            passkeys.store.remove_key(user.user_id, body.credential_id, user.token)
        except passkeys.PasskeyError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {"ok": True}
