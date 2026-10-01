"""Technitium Query Logs (Sqlite) — ensure + resolve logger app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import settings
from .technitium import TechnitiumClient, TechnitiumError

QUERY_LOGS_APP_NAME = "Query Logs (Sqlite)"
QUERY_LOGS_APP_URL_FALLBACK = (
    "https://download.technitium.com/dns/apps/QueryLogsSqliteApp-v9.1.2.zip"
)

DEFAULT_CONFIG = {
    "enableLogging": True,
    "maxQueueSize": 200000,
    "maxLogDays": 14,
    "maxLogRecords": 200000,
    "enableVacuum": False,
    "useInMemoryDb": False,
    "sqliteDbPath": "querylogs.db",
    "connectionString": "Data Source='{sqliteDbPath}'; Cache=Shared;",
}


def find_query_logger(apps: list[dict[str, Any]]) -> tuple[str, str] | None:
    for app in apps:
        name = str(app.get("name") or "")
        for dns_app in app.get("dnsApps") or []:
            if dns_app.get("isQueryLogger"):
                cp = str(dns_app.get("classPath") or "")
                if name and cp:
                    return name, cp
    # name fallback
    for app in apps:
        if str(app.get("name") or "") == QUERY_LOGS_APP_NAME:
            dns_apps = app.get("dnsApps") or []
            cp = str((dns_apps[0] or {}).get("classPath") or "") if dns_apps else ""
            if cp:
                return QUERY_LOGS_APP_NAME, cp
    return None


def vendor_zip_candidates() -> list[Path]:
    roots = []
    data = getattr(settings, "panel_data_dir", None)
    if data:
        roots.append(Path(data) / "vendor")
    # repo /opt/dns/vendor mounted or sibling of panel
    roots.append(Path("/opt/dns/vendor"))
    roots.append(Path("/var/lib/panel/vendor"))
    roots.append(Path(__file__).resolve().parents[2] / "vendor")
    names = [
        "QueryLogsSqliteApp-v9.1.2.zip",
        "QueryLogsSqliteApp.zip",
        "QueryLogsSqlite.zip",
    ]
    out: list[Path] = []
    for root in roots:
        for name in names:
            p = root / name
            if p.is_file() and p not in out:
                out.append(p)
    return out


async def _enable_logging(client: TechnitiumClient, name: str) -> None:
    try:
        cfg_raw = await client.apps_config_get(name)
        cfg_text = (cfg_raw.get("response") or cfg_raw).get("config")
    except TechnitiumError:
        cfg_text = None

    need_set = False
    if not cfg_text:
        cfg = dict(DEFAULT_CONFIG)
        need_set = True
    else:
        try:
            cfg = json.loads(cfg_text)
        except json.JSONDecodeError:
            cfg = dict(DEFAULT_CONFIG)
            need_set = True
        else:
            if not cfg.get("enableLogging", True):
                cfg["enableLogging"] = True
                need_set = True
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                    need_set = True
    if need_set:
        await client.apps_config_set(name, json.dumps(cfg, indent=2))


async def install_from_zip(client: TechnitiumClient, zip_bytes: bytes, filename: str = "app.zip") -> dict[str, Any]:
    await client.apps_install_zip(QUERY_LOGS_APP_NAME, zip_bytes, filename=filename)
    listed = await client.apps_list()
    apps = (listed.get("response") or listed).get("apps") or []
    found = find_query_logger(apps)
    if not found:
        raise TechnitiumError("Query Logs app installed but logger not found")
    name, class_path = found
    await _enable_logging(client, name)
    return {
        "name": name,
        "classPath": class_path,
        "installedNow": True,
        "enableLogging": True,
        "source": "upload",
    }


async def ensure_query_logger(client: TechnitiumClient, *, allow_download: bool = True) -> dict[str, Any]:
    """Install Query Logs (Sqlite) if missing; enable logging."""
    listed = await client.apps_list()
    apps = (listed.get("response") or listed).get("apps") or []
    found = find_query_logger(apps)
    if found:
        name, class_path = found
        await _enable_logging(client, name)
        return {
            "name": name,
            "classPath": class_path,
            "installedNow": False,
            "enableLogging": True,
            "source": "existing",
        }

    # 1) local vendor zip (offline lab)
    for path in vendor_zip_candidates():
        try:
            data = path.read_bytes()
            if len(data) < 1000:
                continue
            result = await install_from_zip(client, data, filename=path.name)
            result["source"] = f"vendor:{path}"
            return result
        except OSError:
            continue
        except TechnitiumError:
            continue

    # 2) optional download (often blocked on lab)
    if allow_download:
        try:
            await client.apps_download_and_install(QUERY_LOGS_APP_NAME, QUERY_LOGS_APP_URL_FALLBACK)
            listed = await client.apps_list()
            apps = (listed.get("response") or listed).get("apps") or []
            found = find_query_logger(apps)
            if found:
                name, class_path = found
                await _enable_logging(client, name)
                return {
                    "name": name,
                    "classPath": class_path,
                    "installedNow": True,
                    "enableLogging": True,
                    "source": "download",
                }
        except TechnitiumError:
            pass

    raise TechnitiumError(
        "Query Logs (Sqlite) не установлен. Скачай QueryLogsSqliteApp-v9.1.2.zip "
        "и загрузи во вкладке Blocking → Log (или положи в /opt/dns/vendor/).",
        status="missing-app",
    )
