from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .auth import router as auth_router
from .routes import router as dns_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        from . import panel_tls
        from .session_secret import ensure_session_secret

        ensure_session_secret()
        panel_tls.ensure_self_signed()
        panel_tls.ensure_http_conf()
    except Exception:
        pass
    yield


app = FastAPI(title="DNS Panel", version="0.1.0", lifespan=lifespan)

# UI и API на одном origin через nginx — CORS с * + credentials не нужен и вреден.
app.include_router(auth_router)
app.include_router(dns_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
