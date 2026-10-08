"""Technitium admin password for host automation (sync-blocky-forwarder).

Пишется панелью при login / change-password — не править .env руками.
Файл: PANEL_DATA_DIR/technitium_admin.pass (chmod 600).
"""

from __future__ import annotations

import os
from pathlib import Path


def _path() -> Path:
    base = Path(os.environ.get("PANEL_DATA_DIR", "/var/lib/panel"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "technitium_admin.pass"


def store_admin_password(password: str) -> None:
    pwd = (password or "").strip()
    if not pwd:
        return
    path = _path()
    path.write_text(pwd + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def read_admin_password() -> str | None:
    path = _path()
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
