"""Panel → stack-watch signals (no docker.sock in panel)."""

from __future__ import annotations

import os
import time
from pathlib import Path

SIGNAL_HUP = "nginx.hup"
SIGNAL_RECREATE = "nginx.recreate"


def _signals_dir() -> Path:
    path = Path(os.environ.get("PANEL_DATA_DIR", "/var/lib/panel")) / "signals"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _touch(name: str) -> Path:
    path = _signals_dir() / name
    path.write_text(f"{time.time():.3f}\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def request_nginx_hup() -> dict:
    p = _touch(SIGNAL_HUP)
    return {"signaled": True, "signal": SIGNAL_HUP, "path": str(p)}


def request_nginx_recreate() -> dict:
    p = _touch(SIGNAL_RECREATE)
    return {"signaled": True, "signal": SIGNAL_RECREATE, "path": str(p)}
