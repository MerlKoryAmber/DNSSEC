from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import router as auth_router
from .routes import router as dns_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        from . import panel_tls

        panel_tls.ensure_self_signed()
        panel_tls.ensure_http_conf()
    except Exception:
        pass
    yield


app = FastAPI(title="DNS Panel", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(dns_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
