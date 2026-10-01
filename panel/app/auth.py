from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field

from .config import settings
from .technitium import TechnitiumClient, TechnitiumError

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.panel_session_secret, salt="dns-panel")


def set_token_cookie(response: Response, token: str) -> None:
    signed = _serializer().dumps(token)
    response.set_cookie(
        settings.session_cookie,
        signed,
        httponly=True,
        samesite="lax",
        max_age=settings.session_max_age,
        path="/",
    )


def clear_token_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


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
async def login(body: LoginBody, response: Response):
    client = TechnitiumClient()
    try:
        data = await client.login(body.user, body.password)
    except TechnitiumError as exc:
        raise HTTPException(status_code=401, detail=exc.message) from exc
    token = data.get("token")
    if not token:
        raise HTTPException(status_code=502, detail="Technitium не вернул token")
    set_token_cookie(response, token)
    return {
        "username": data.get("username"),
        "displayName": data.get("displayName"),
        "info": data.get("info"),
    }


@router.post("/logout")
async def logout(response: Response, token: str = Depends(get_token)):
    client = TechnitiumClient(token=token)
    try:
        await client.logout()
    except TechnitiumError:
        pass
    clear_token_cookie(response)
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
