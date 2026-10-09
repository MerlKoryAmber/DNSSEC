from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .config import settings


def _config_path() -> Path:
    return Path(settings.blocky_config_path)


def encode_upstream(addr: str, kind: str) -> str:
    a = (addr or "").strip()
    k = kind if kind in ("classic", "dot", "doh") else "classic"
    if k == "doh":
        if not a.lower().startswith(("http://", "https://")):
            a = "https://" + a
        p = urlparse(a)
        if not p.path or p.path == "/":
            a = f"{p.scheme}://{p.netloc}/dns-query"
        return a
    if k == "dot":
        low = a.lower()
        if low.startswith("tls://"):
            a = a[6:]
        if low.startswith("tcp-tls:"):
            a = a[8:]
        if a.endswith(":853"):
            a = a[:-4]
        return f"tcp-tls:{a}:853"
    return a


def decode_upstream(raw: str) -> dict[str, str]:
    s = (raw or "").strip()
    low = s.lower()
    if low.startswith("https://") or low.startswith("http://"):
        return {"addr": s, "kind": "doh"}
    if low.startswith("tcp-tls:") or low.startswith("tls://"):
        a = s
        if low.startswith("tcp-tls:"):
            a = s[8:]
        elif low.startswith("tls://"):
            a = s[6:]
        if a.endswith(":853"):
            a = a[:-4]
        return {"addr": a, "kind": "dot"}
    return {"addr": s, "kind": "classic"}


def read_forwarders() -> list[dict[str, str]]:
    path = _config_path()
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    groups = (data.get("upstreams") or {}).get("groups") or {}
    raw_list = groups.get("default") or []
    if not isinstance(raw_list, list):
        return []
    return [decode_upstream(str(x)) for x in raw_list if str(x).strip()]


def write_forwarders(items: list[dict[str, str]]) -> list[str]:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {
            "upstreams": {"strategy": "strict", "timeout": "2s", "groups": {"default": []}},
            "ports": {"dns": 53, "http": 4000},
            "log": {"level": "info"},
        }
    upstreams = data.setdefault("upstreams", {})
    upstreams["strategy"] = "strict"
    groups = upstreams.setdefault("groups", {})
    encoded = [encode_upstream(i["addr"], i.get("kind") or "classic") for i in items]
    groups["default"] = encoded
    # Query log CSV → какой upstream ответил (панель колонка Upstream)
    ql = data.get("queryLog")
    if not isinstance(ql, dict) or ql.get("type") != "csv":
        data["queryLog"] = {
            "type": "csv",
            "target": "/logs",
            "logRetentionDays": 14,
            "fields": ["clientIP", "question", "responseReason", "duration"],
        }
    try:
        (path.parent / "querylogs").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    text = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp = path.with_suffix(".yml.tmp")
    tmp.write_text(text, encoding="utf-8")
    # in-place overwrite — same inode (docker file bind mount)
    path.write_text(text, encoding="utf-8")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    return encoded
