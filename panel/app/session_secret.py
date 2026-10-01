"""Bootstrap session signing secret if compose still has the default."""

from __future__ import annotations

import secrets
from pathlib import Path

from .config import settings

_WEAK_DEFAULTS = frozenset({"", "change-me-lab-secret", "change-me"})


def ensure_session_secret() -> str:
    current = (settings.panel_session_secret or "").strip()
    if current not in _WEAK_DEFAULTS:
        return current

    path = Path(settings.panel_data_dir) / "session_secret"
    if path.is_file():
        stored = path.read_text(encoding="utf-8").strip()
        if stored and stored not in _WEAK_DEFAULTS:
            settings.panel_session_secret = stored
            return stored

    value = secrets.token_hex(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    settings.panel_session_secret = value
    return value
