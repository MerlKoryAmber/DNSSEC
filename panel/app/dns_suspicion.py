"""DNS query suspicion heuristics (tunnel / DGA-ish) — no TI / SIEM.

Scores Technitium query-log rows in-process. Burst window is in-memory
(per panel process); resets on restart — acceptable for MVP.
Prefs (auto-block + thresholds) live in config/panel/ui.yml → suspicion: …
"""

from __future__ import annotations

import math
import os
import re
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import yaml

# --- default thresholds ---
DEFAULTS: dict[str, Any] = {
    "autoBlock": False,
    "minLevel": "high",  # suspicious | high
    "minScore": 6,
    "labelLenSoft": 25,
    "labelLenHard": 40,
    "entropySoft": 3.3,
    "entropyHard": 4.0,
    "entropyMinLen": 12,
    "depthSoft": 5,
    "scoreSuspicious": 3,
    "scoreHigh": 6,
    "burstWindowSec": 60,
    "burstUnique": 8,
    "burstScore": 3,
}

_RARE_QTYPES = frozenset({"TXT", "NULL", "ANY", "PRIVATE", "UNKNOWN"})
_SKIP_SUFFIXES = (
    ".arpa.",
    ".local.",
    ".localhost.",
    ".invalid.",
    ".test.",
    ".onion.",
)
_SKIP_EXACT = frozenset({"localhost", "localhost.", ".", ""})
_LEVEL_RANK = {"ok": 0, "suspicious": 1, "high": 2}

# client_ip -> deque[(monotonic_ts, qname_key)]
_burst: dict[str, deque[tuple[float, str]]] = defaultdict(deque)
# domains already auto-blocked this process (avoid API spam)
_autoblocked: set[str] = set()


def _data_dir() -> Path:
    path = Path(os.environ.get("PANEL_DATA_DIR", "/var/lib/panel"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ui_cfg_path() -> Path:
    return _data_dir() / "ui.yml"


def _load_ui() -> dict[str, Any]:
    cfg = _ui_cfg_path()
    if not cfg.is_file():
        return {}
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_ui(data: dict[str, Any]) -> None:
    _ui_cfg_path().write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def read_prefs() -> dict[str, Any]:
    raw = _load_ui().get("suspicion")
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in DEFAULTS and v is not None:
                out[k] = v
    # normalize types
    out["autoBlock"] = bool(out["autoBlock"])
    lvl = str(out.get("minLevel") or "high").lower()
    out["minLevel"] = lvl if lvl in ("suspicious", "high") else "high"
    for key in (
        "minScore",
        "labelLenSoft",
        "labelLenHard",
        "entropyMinLen",
        "depthSoft",
        "scoreSuspicious",
        "scoreHigh",
        "burstWindowSec",
        "burstUnique",
        "burstScore",
    ):
        try:
            out[key] = int(out[key])
        except (TypeError, ValueError):
            out[key] = int(DEFAULTS[key])
    for key in ("entropySoft", "entropyHard"):
        try:
            out[key] = float(out[key])
        except (TypeError, ValueError):
            out[key] = float(DEFAULTS[key])
    return out


def write_prefs(patch: dict[str, Any]) -> dict[str, Any]:
    cur = read_prefs()
    for k, v in patch.items():
        if k not in DEFAULTS or v is None:
            continue
        cur[k] = v
    # re-validate via read path after write
    data = _load_ui()
    data["suspicion"] = {k: cur[k] for k in DEFAULTS}
    _save_ui(data)
    return read_prefs()


def prefs_public() -> dict[str, Any]:
    """UI-facing prefs + defaults for form hints."""
    p = read_prefs()
    return {"status": "ok", "prefs": p, "defaults": dict(DEFAULTS)}


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    counts = Counter(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _norm_qname(raw: str) -> str:
    q = (raw or "").strip().lower()
    if q and not q.endswith("."):
        q = q + "."
    return q


def _labels(qname: str) -> list[str]:
    q = _norm_qname(qname).rstrip(".")
    if not q:
        return []
    return [p for p in q.split(".") if p]


def _skip_name(qname: str) -> bool:
    q = _norm_qname(qname)
    if q in _SKIP_EXACT or q.rstrip(".") in _SKIP_EXACT:
        return True
    return any(q.endswith(sfx) or q.rstrip(".").endswith(sfx.rstrip(".")) for sfx in _SKIP_SUFFIXES)


def _note_burst(client_ip: str, qname: str, window: float, unique_need: int, now: float | None = None) -> bool:
    ip = (client_ip or "").strip() or "?"
    key = _norm_qname(qname).rstrip(".")
    if not key or len(key) < 3:
        return False
    t = now if now is not None else time.monotonic()
    dq = _burst[ip]
    dq.append((t, key))
    cutoff = t - window
    while dq and dq[0][0] < cutoff:
        dq.popleft()
    while len(dq) > 500:
        dq.popleft()
    return len({k for _, k in dq}) >= unique_need


def score_query(
    *,
    qname: str,
    qtype: str = "",
    client_ip: str = "",
    rcode: str = "",
    response_type: str = "",
    track_burst: bool = True,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return {score, level, reasons, entropy, maxLabelLen, depth}."""
    c = cfg or read_prefs()
    label_soft = int(c["labelLenSoft"])
    label_hard = int(c["labelLenHard"])
    ent_soft = float(c["entropySoft"])
    ent_hard = float(c["entropyHard"])
    ent_min = int(c["entropyMinLen"])
    depth_soft = int(c["depthSoft"])
    score_sus = int(c["scoreSuspicious"])
    score_high = int(c["scoreHigh"])
    burst_win = float(c["burstWindowSec"])
    burst_n = int(c["burstUnique"])
    burst_pts = int(c["burstScore"])

    reasons: list[str] = []
    score = 0
    labels = _labels(qname)
    depth = len(labels)
    max_len = max((len(x) for x in labels), default=0)
    candidates = labels[:-1] if len(labels) > 1 else labels
    best_ent = 0.0
    best_lab = ""
    for lab in candidates:
        if len(lab) < ent_min:
            continue
        core = re.sub(r"[^a-z0-9]", "", lab.lower())
        if len(core) < ent_min:
            continue
        e = _shannon(core)
        if e > best_ent:
            best_ent = e
            best_lab = lab

    if _skip_name(qname):
        return {
            "score": 0,
            "level": "ok",
            "reasons": [],
            "entropy": round(best_ent, 2),
            "maxLabelLen": max_len,
            "depth": depth,
        }

    if max_len >= label_hard:
        score += 3
        reasons.append(f"label_len>={label_hard}")
    elif max_len >= label_soft:
        score += 2
        reasons.append(f"label_len>={label_soft}")

    if best_ent >= ent_hard and len(best_lab) >= ent_min:
        score += 3
        reasons.append(f"entropy>={ent_hard}")
    elif best_ent >= ent_soft and len(best_lab) >= ent_min:
        score += 2
        reasons.append(f"entropy>={ent_soft}")

    if depth >= depth_soft:
        score += 1
        reasons.append(f"depth>={depth_soft}")

    qt = (qtype or "").strip().upper()
    if qt in _RARE_QTYPES:
        score += 2
        reasons.append(f"qtype={qt or 'rare'}")

    rc = (rcode or "").strip().upper()
    if rc in ("NXDOMAIN", "NAMEERROR") and score >= 2:
        score += 1
        reasons.append("nxdomain")

    if track_burst:
        if score >= 2 or max_len >= 16 or best_ent >= ent_soft:
            if _note_burst(client_ip, qname, burst_win, burst_n):
                score += burst_pts
                reasons.append(f"burst>={burst_n}/{int(burst_win)}s")

    if score >= score_high:
        level = "high"
    elif score >= score_sus:
        level = "suspicious"
    else:
        level = "ok"

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "entropy": round(best_ent, 2),
        "maxLabelLen": max_len,
        "depth": depth,
    }


def meets_autoblock(sus: dict[str, Any], cfg: dict[str, Any] | None = None) -> bool:
    c = cfg or read_prefs()
    if not c.get("autoBlock"):
        return False
    level = str((sus or {}).get("level") or "ok")
    score = int((sus or {}).get("score") or 0)
    need = str(c.get("minLevel") or "high")
    if _LEVEL_RANK.get(level, 0) < _LEVEL_RANK.get(need, 2):
        return False
    return score >= int(c.get("minScore") or 0)


def enrich_entries(
    entries: list[dict[str, Any]],
    *,
    suspicious_only: bool = False,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    c = cfg or read_prefs()
    ordered = list(reversed(entries)) if entries else []
    scored_rev: list[dict[str, Any]] = []
    for e in ordered:
        sus = score_query(
            qname=str(e.get("qname") or ""),
            qtype=str(e.get("qtype") or e.get("questionType") or ""),
            client_ip=str(e.get("clientIpAddress") or e.get("clientIp") or ""),
            rcode=str(e.get("rcode") or ""),
            response_type=str(e.get("responseType") or ""),
            track_burst=True,
            cfg=c,
        )
        row = dict(e)
        row["suspicion"] = sus
        scored_rev.append(row)
    scored = list(reversed(scored_rev))
    if not suspicious_only:
        return scored
    return [
        row
        for row in scored
        if (row.get("suspicion") or {}).get("level") in ("suspicious", "high")
    ]


async def apply_auto_block(client: Any, entries: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> list[str]:
    """Add meeting domains to Technitium blocked list. Returns newly blocked names."""
    c = cfg or read_prefs()
    if not c.get("autoBlock"):
        return []
    added: list[str] = []
    for e in entries:
        sus = e.get("suspicion") or {}
        if not meets_autoblock(sus, c):
            continue
        domain = str(e.get("qname") or "").strip().rstrip(".").lower()
        if not domain or _skip_name(domain):
            continue
        if domain in _autoblocked:
            continue
        try:
            await client.blocked_add(domain)
            _autoblocked.add(domain)
            added.append(domain)
            e["suspicion"] = {**sus, "autoBlocked": True}
        except Exception:
            # already blocked / API noise — ignore
            _autoblocked.add(domain)
    return added
