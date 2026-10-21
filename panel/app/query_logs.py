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
    # Overridden from ui_prefs on ensure/save (~2 GiB budget → 2.5M rows)
    "maxLogDays": 90,
    "maxLogRecords": 2_500_000,
    "enableVacuum": False,
    "useInMemoryDb": False,
    "sqliteDbPath": "querylogs.db",
    "connectionString": "Data Source='{sqliteDbPath}'; Cache=Shared;",
}

# Technitium DnsServerResponseType (README Query Logs Sqlite)
_BLOCKED_RESPONSE_TYPE_IDS = (4, 5, 6, 7)  # Blocked, UpstreamBlocked, UpstreamBlockedCached, Dropped
_TRIGGER_NAME = "dns_panel_blocked_only"  # legacy; removed — mode is blocked+risk via purge

# Common DnsType / RCODE ints → strings for suspicion scoring on raw rows
_DNS_QTYPE = {
    1: "A",
    2: "NS",
    5: "CNAME",
    6: "SOA",
    12: "PTR",
    15: "MX",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    64: "SVCB",
    65: "HTTPS",
    255: "ANY",
    10: "NULL",
    99: "SPF",
}
_DNS_RCODE = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
}


def querylogs_db_path() -> Path:
    cfg = Path(getattr(settings, "technitium_config_dir", None) or "/var/lib/dns-config")
    return cfg / "apps" / QUERY_LOGS_APP_NAME / "querylogs.db"


# Purge ok-allowed only when DB is this full vs maxLogRecords (Merl: не по таймеру).
PURGE_FILL_RATIO = 0.75


def querylogs_row_count() -> int | None:
    path = querylogs_db_path()
    if not path.is_file():
        return None
    import sqlite3

    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute("SELECT COUNT(*) FROM dns_logs").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def count_distinct_clients_since(since_utc: str) -> int | None:
    """Unique client_ip in querylogs since `YYYY-MM-DD HH:MM:SS` (UTC text).

    Technitium StatsManager truncates top-client maps (STATS_TOP_LIMIT) and can
    report totalClients stuck at the truncate cap (historically 100 / now 1000).
    Query logs keep full client_ip and are a better source when available.
    """
    path = querylogs_db_path()
    if not path.is_file():
        return None
    import sqlite3

    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                "SELECT COUNT(DISTINCT client_ip) FROM dns_logs WHERE timestamp >= ?",
                (since_utc,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def maybe_purge_allowed_low_risk(*, fill_ratio: float = PURGE_FILL_RATIO) -> dict[str, Any]:
    """Run blocked+risk purge only when row count ≥ fill_ratio × maxLogRecords."""
    from . import ui_prefs

    cap = max(1, int(ui_prefs.read_max_log_records()))
    n = querylogs_row_count()
    if n is None:
        return {"skipped": True, "reason": "db-missing", "rows": None, "cap": cap}
    fill = float(n) / float(cap)
    threshold = float(fill_ratio)
    if fill < threshold:
        return {
            "skipped": True,
            "reason": "below-threshold",
            "rows": n,
            "cap": cap,
            "fill": round(fill, 4),
            "threshold": threshold,
        }
    info = purge_allowed_low_risk()
    info["skipped"] = False
    info["rowsBefore"] = n
    info["cap"] = cap
    info["fillBefore"] = round(fill, 4)
    info["threshold"] = threshold
    return info


def purge_allowed_low_risk(
    *,
    batch: int = 2000,
    max_batches: int = 250,
) -> dict[str, Any]:
    """Delete allowed (non-blocked) rows with suspicion level=ok. Keep blocked + risk.

    Important: walk the table by dlid ASC with a cursor. A DESC+LIMIT-on-newest
    purge left old ok rows buried and made Query log look like a ~20min window
    (page1 = newest raw rows, mostly ok noise).
    """
    path = querylogs_db_path()
    if not path.is_file():
        return {"purged": 0, "scanned": 0, "reason": "db-missing"}

    import sqlite3

    from . import dns_suspicion

    cfg = dns_suspicion.read_prefs()
    keep = ",".join(str(x) for x in _BLOCKED_RESPONSE_TYPE_IDS)
    deleted = 0
    scanned = 0
    kept_risk = 0
    batches = 0
    cursor = 0
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            batch_n = max(100, int(batch))
            while batches < max(1, int(max_batches)):
                batches += 1
                rows = conn.execute(
                    f"""
                    SELECT dlid, qname, qtype, client_ip, rcode, response_type
                    FROM dns_logs
                    WHERE response_type NOT IN ({keep})
                      AND dlid > ?
                    ORDER BY dlid ASC
                    LIMIT ?
                    """,
                    (cursor, batch_n),
                ).fetchall()
                if not rows:
                    break
                drop_ids: list[int] = []
                for row in rows:
                    scanned += 1
                    cursor = max(cursor, int(row["dlid"]))
                    qtype = _DNS_QTYPE.get(int(row["qtype"] or 0), "")
                    rcode = _DNS_RCODE.get(int(row["rcode"] or 0), "")
                    sus = dns_suspicion.score_query(
                        qname=str(row["qname"] or ""),
                        qtype=qtype,
                        client_ip=str(row["client_ip"] or ""),
                        rcode=rcode,
                        response_type="",
                        track_burst=False,
                        cfg=cfg,
                    )
                    if (sus.get("level") or "ok") == "ok":
                        drop_ids.append(int(row["dlid"]))
                    else:
                        kept_risk += 1
                if drop_ids:
                    for i in range(0, len(drop_ids), 400):
                        chunk = drop_ids[i : i + 400]
                        placeholders = ",".join("?" * len(chunk))
                        cur = conn.execute(
                            f"DELETE FROM dns_logs WHERE dlid IN ({placeholders})",
                            chunk,
                        )
                        deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                if len(rows) < batch_n:
                    break
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "purged": deleted,
            "scanned": scanned,
            "keptRisk": kept_risk,
            "batches": batches,
            "reason": str(exc),
        }
    return {
        "purged": deleted,
        "scanned": scanned,
        "keptRisk": kept_risk,
        "batches": batches,
        "keptRiskCandidates": kept_risk,
    }


def apply_log_allowed_mode(*, log_allowed: bool) -> dict[str, Any]:
    """
    Stock Query Logs app logs ALL queries.

    log_allowed=True  → keep everything (drop legacy blocked-only trigger).
    log_allowed=False → keep blocked/dropped + elevated-risk allowed (purge ok allowed).
    """
    path = querylogs_db_path()
    if not path.is_file():
        return {"applied": False, "reason": "db-missing", "path": str(path), "logAllowedQueries": log_allowed}

    import sqlite3

    deleted = 0
    purge_info: dict[str, Any] = {}
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            # legacy trigger deleted all non-blocked — kills risk rows; never recreate
            conn.execute(f'DROP TRIGGER IF EXISTS "{_TRIGGER_NAME}"')
            conn.commit()
        finally:
            conn.close()
        if not log_allowed:
            purge_info = purge_allowed_low_risk()
            deleted = int(purge_info.get("purged") or 0)
    except sqlite3.Error as exc:
        return {
            "applied": False,
            "reason": str(exc),
            "path": str(path),
            "logAllowedQueries": log_allowed,
        }
    return {
        "applied": True,
        "path": str(path),
        "logAllowedQueries": log_allowed,
        "purgedNonBlocked": deleted,
        "purge": purge_info,
        "mode": "all" if log_allowed else "blocked+risk",
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
    from . import ui_prefs

    want_records = ui_prefs.read_max_log_records()
    want_days = ui_prefs.read_max_log_days()

    try:
        cfg_raw = await client.apps_config_get(name)
        cfg_text = (cfg_raw.get("response") or cfg_raw).get("config")
    except TechnitiumError:
        cfg_text = None

    need_set = False
    if not cfg_text:
        cfg = dict(DEFAULT_CONFIG)
        cfg["maxLogRecords"] = want_records
        cfg["maxLogDays"] = want_days
        need_set = True
    else:
        try:
            cfg = json.loads(cfg_text)
        except json.JSONDecodeError:
            cfg = dict(DEFAULT_CONFIG)
            cfg["maxLogRecords"] = want_records
            cfg["maxLogDays"] = want_days
            need_set = True
        else:
            if not cfg.get("enableLogging", True):
                cfg["enableLogging"] = True
                need_set = True
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                    need_set = True
            if int(cfg.get("maxLogRecords") or 0) != want_records:
                cfg["maxLogRecords"] = want_records
                need_set = True
            if int(cfg.get("maxLogDays") or -1) != want_days:
                cfg["maxLogDays"] = want_days
                need_set = True
    if need_set:
        await client.apps_config_set(name, json.dumps(cfg, indent=2))

    # Apply blocked-only DB filter (default) unless UI prefs allow all queries
    try:
        apply_log_allowed_mode(log_allowed=ui_prefs.read_log_allowed_queries())
    except Exception:
        pass


async def apply_retention(client: TechnitiumClient) -> dict[str, Any]:
    """Push maxLogRecords / maxLogDays from ui.yml into Query Logs app config."""
    listed = await client.apps_list()
    apps = (listed.get("response") or listed).get("apps") or []
    found = find_query_logger(apps)
    if not found:
        return {"applied": False, "reason": "app-missing"}
    name, _cp = found
    await _enable_logging(client, name)
    from . import ui_prefs

    return {
        "applied": True,
        "name": name,
        "maxLogRecords": ui_prefs.read_max_log_records(),
        "maxLogDays": ui_prefs.read_max_log_days(),
    }

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
        "logAllowedQueries": False,
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
