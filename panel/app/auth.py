from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field

from .config import settings
from .technitium import TechnitiumClient, TechnitiumError

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Failed logins per client IP (in-memory; resets on panel restart).
_LOGIN_FAILS: dict[str, list[float]] = defaultdict(list)
_LOGIN_WINDOW_SEC = 300.0
_LOGIN_MAX_FAILS = 20


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.panel_session_secret, salt="dns-panel")


def _request_is_https(request: Request) -> bool:
    # nginx → panel по HTTP; схема смотрим в X-Forwarded-Proto
    xf = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if xf:
        return xf == "https"
    return request.url.scheme == "https"


def _client_ip(request: Request) -> str:
    xf = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xf:
        return xf
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _prune_fails(ip: str, now: float) -> list[float]:
    hits = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
    _LOGIN_FAILS[ip] = hits
    return hits


def _check_login_rate(ip: str) -> None:
    now = time.time()
    if len(_prune_fails(ip, now)) >= _LOGIN_MAX_FAILS:
        raise HTTPException(status_code=429, detail="Too many login attempts — try later")


def _record_login_fail(ip: str) -> None:
    now = time.time()
    hits = _prune_fails(ip, now)
    hits.append(now)
    _LOGIN_FAILS[ip] = hits


def _clear_login_fails(ip: str) -> None:
    _LOGIN_FAILS.pop(ip, None)


def set_token_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    signed = _serializer().dumps(token)
    response.set_cookie(
        settings.session_cookie,
        signed,
        httponly=True,
        samesite="strict",
        secure=secure,
        max_age=settings.session_max_age,
        path="/",
    )


def clear_token_cookie(response: Response, *, secure: bool = False) -> None:
    response.delete_cookie(
        settings.session_cookie,
        path="/",
        httponly=True,
        samesite="strict",
        secure=secure,
    )


def get_token(request: Request) -> str:
    raw = request.cookies.get(settings.session_cookie)
    if not raw:
        raise HTTPException(status_code=401, detail="Требуется вход")
    try:
        token = _serializer().loads(raw)
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="Сессия повреждена") from exc
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return token


def get_client(token: str = Depends(get_token)) -> TechnitiumClient:
    return TechnitiumClient(token=token)


class LoginBody(BaseModel):
    user: str = Field(min_length=1)
    password: str = Field(min_length=1)


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = _client_ip(request)
    _check_login_rate(ip)
    client = TechnitiumClient()
    try:
        data = await client.login(body.user, body.password)
    except TechnitiumError as exc:
        _record_login_fail(ip)
        raise HTTPException(status_code=401, detail=exc.message) from exc
    token = data.get("token")
    if not token:
        _record_login_fail(ip)
        raise HTTPException(status_code=502, detail="Auth backend did not return a token")
    _clear_login_fails(ip)
    set_token_cookie(response, token, secure=_request_is_https(request))
    return {
        "username": data.get("username"),
        "displayName": data.get("displayName"),
        "info": data.get("info"),
    }


@router.post("/logout")
async def logout(request: Request, response: Response, token: str = Depends(get_token)):
    client = TechnitiumClient(token=token)
    try:
        await client.logout()
    except TechnitiumError:
        pass
    clear_token_cookie(response, secure=_request_is_https(request))
    return {"ok": True}


@router.get("/me")
async def me(client: TechnitiumClient = Depends(get_client)):
    try:
        data = await client.session_info()
    except TechnitiumError as exc:
        if exc.status == "invalid-token":
            raise HTTPException(status_code=401, detail=exc.message) from exc
        raise HTTPException(status_code=502, detail=exc.message) from exc
    # не отдаём сырой token в браузер
    data = {k: v for k, v in data.items() if k != "token"}
    return data


class ChangePasswordBody(BaseModel):
    currentPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=1)
    totp: str | None = None


@router.post("/change-password")
async def change_password(body: ChangePasswordBody, client: TechnitiumClient = Depends(get_client)):
    if body.currentPassword == body.newPassword:
        raise HTTPException(status_code=400, detail="New password must differ from current")
    try:
        await client.change_password(body.currentPassword, body.newPassword, totp=body.totp)
    except TechnitiumError as exc:
        code = 401 if getattr(exc, "status", None) in ("invalid-password", "invalid-token", "2fa-required") else 400
        raise HTTPException(status_code=code, detail=exc.message) from exc
    return {"ok": True}
