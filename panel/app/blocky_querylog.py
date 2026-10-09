"""Blocky CSV query log → upstream label for panel Query log.

Technitium sees only Blocky; which Forwarders entry answered is in Blocky
responseReason, e.g. RESOLVED (tcp-tls:1.1.1.1:853).
"""

from __future__ import annotations

import csv
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import settings

_REASON_UPSTREAM = re.compile(
    r"RESOLVED\s*\(([^)]+)\)|CACHED|BLOCKED|SPECIAL|FILTERED",
    re.IGNORECASE,
)


def _config_path() -> Path:
    return Path(settings.blocky_config_path)


def querylog_dir() -> Path:
    # panel: BLOCKY_QUERYLOG_DIR или рядом с config.yml
    env = (getattr(settings, "blocky_querylog_dir", None) or "").strip()
    if env:
        return Path(env)
    return _config_path().parent / "querylogs"


def ensure_querylog_in_config() -> bool:
    """Добавить queryLog csv в config.yml при отсутствии. True если файл изменён."""
    path = _config_path()
    if not path.is_file():
        return False
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ql = data.get("queryLog")
    want = {
        "type": "csv",
        "target": "/logs",
        "logRetentionDays": 14,
        "fields": ["clientIP", "question", "responseReason", "duration"],
    }
    if isinstance(ql, dict) and ql.get("type") == "csv" and ql.get("target") == "/logs":
        return False
    data["queryLog"] = want
    text = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    d = querylog_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o1777)  # blocky non-root пишет /logs
    except OSError:
        pass
    return True


def _parse_ts(raw: str) -> float | None:
    s = (raw or "").strip()
    if not s:
        return None
    # Blocky CSV: 2006-01-02 15:04:05 or RFC3339
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(s.replace("+00:00", "Z"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _norm_qname(q: str) -> str:
    return (q or "").strip().rstrip(".").lower()


def _extract_question(cell: str) -> tuple[str, str]:
    """'A (example.com.)' → (example.com, A) or bare name."""
    s = (cell or "").strip()
    m = re.match(r"^([A-Za-z0-9]+)\s+\(([^)]+)\)\s*$", s)
    if m:
        return _norm_qname(m.group(2)), m.group(1).upper()
    return _norm_qname(s), ""


def _upstream_from_reason(reason: str) -> str:
    s = (reason or "").strip()
    if not s:
        return ""
    m = re.search(r"RESOLVED\s*\(([^)]+)\)", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # CACHED / BLOCKED / …
    head = s.split()[0] if s.split() else s
    return head.strip()


def _row_from_cols(cols: list[str]) -> dict[str, str] | None:
    """Blocky v0.26 TSV (no header), observed:
    ts, clientIP, clientName, durationMs, responseReason, qname, ?, rcode, responseType, qtype, id
    """
    if len(cols) < 6:
        return None
    reason = ""
    qname = ""
    qtype = ""
    for c in cols:
        cs = c.strip()
        if not reason and (
            cs.upper().startswith("RESOLVED")
            or cs.upper().startswith("CACHED")
            or cs.upper().startswith("BLOCKED")
            or cs.upper().startswith("FILTERED")
        ):
            reason = cs
        if not qname and "." in cs and not cs.upper().startswith("RESOLVED") and "://" not in cs:
            # qname-ish (one.one.one.one. or example.com.)
            if re.match(r"^[A-Za-z0-9._*-]+\.?$", cs) and not re.match(r"^\d+\.\d+\.\d+\.\d+$", cs):
                qname = cs
        if not qtype and cs.upper() in (
            "A", "AAAA", "TXT", "MX", "CNAME", "NS", "SOA", "PTR", "SRV", "HTTPS", "SVCB", "ANY", "NULL"
        ):
            qtype = cs.upper()
    if not qname and len(cols) > 5:
        qname = cols[5].strip()
    if not reason and len(cols) > 4:
        reason = cols[4].strip()
    if not qtype and len(cols) > 9:
        qtype = cols[9].strip().upper()
    return {
        "timestamp": cols[0].strip(),
        "clientIP": cols[1].strip() if len(cols) > 1 else "",
        "question": qname,
        "qtype": qtype,
        "responseReason": reason,
    }


def _iter_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text.strip():
        return []
    lines = text.splitlines()
    sample = lines[0] if lines else ""
    delim = "\t" if "\t" in sample else ","
    has_header = "question" in sample.lower() or "clientip" in sample.lower()
    rows: list[dict[str, str]] = []
    try:
        if has_header:
            reader = csv.DictReader(lines, delimiter=delim)
            for r in reader:
                rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
        else:
            reader = csv.reader(lines, delimiter=delim)
            for cols in reader:
                mapped = _row_from_cols(list(cols))
                if mapped:
                    rows.append(mapped)
    except csv.Error:
        return []
    return rows


def load_recent(max_files: int = 3, max_rows: int = 5000) -> list[dict[str, Any]]:
    """Список {ts, qname, qtype, upstream} свежие сверху."""
    d = querylog_dir()
    if not d.is_dir():
        return []
    # blocky csv writer: 2026-10-09_ALL.log (не .csv)
    files = sorted(
        list(d.glob("*.log")) + list(d.glob("*.csv")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_files]
    out: list[dict[str, Any]] = []
    for path in reversed(files):  # older first then flip
        for r in _iter_csv_rows(path):
            q_raw = r.get("question") or r.get("Question") or ""
            qname, qtype = _extract_question(q_raw)
            if r.get("qtype") and not qtype:
                qtype = str(r.get("qtype") or "").upper()
            reason = r.get("responseReason") or r.get("response_reason") or r.get("ResponseReason") or ""
            if not reason:
                reason = r.get("responseType") or ""
            upstream = _upstream_from_reason(reason)
            ts_raw = r.get("timestamp") or r.get("Timestamp") or r.get("time") or ""
            ts = _parse_ts(ts_raw)
            if ts is None:
                # file mtime fallback — skip matching
                continue
            if not qname:
                continue
            out.append({"ts": ts, "qname": qname, "qtype": qtype, "upstream": upstream, "reason": reason})
            if len(out) >= max_rows:
                break
        if len(out) >= max_rows:
            break
    return out


def enrich_entries(entries: list[dict[str, Any]], *, window_sec: float = 5.0) -> list[dict[str, Any]]:
    """Добавить entry['upstream'] из Blocky CSV (лучшее совпадение qname ± window)."""
    if not entries:
        return entries
    try:
        ensure_querylog_in_config()
    except OSError:
        pass
    recent = load_recent()
    if not recent:
        for e in entries:
            e.setdefault("upstream", "")
        return entries

    # index by qname
    by_name: dict[str, list[dict[str, Any]]] = {}
    for r in recent:
        by_name.setdefault(r["qname"], []).append(r)

    for e in entries:
        qn = _norm_qname(str(e.get("qname") or ""))
        ts_raw = str(e.get("timestamp") or "")
        ts = _parse_ts(ts_raw)
        candidates = by_name.get(qn) or []
        best = ""
        best_dt = 1e18
        if ts is not None:
            qt = str(e.get("qtype") or "").upper()
            for c in candidates:
                dt = abs(c["ts"] - ts)
                if dt > window_sec:
                    continue
                if qt and c.get("qtype") and c["qtype"] != qt:
                    continue
                if dt < best_dt and c.get("upstream"):
                    best_dt = dt
                    best = c["upstream"]
        e["upstream"] = best
    return entries
