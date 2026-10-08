"""DNS query suspicion heuristics (tunnel / DGA-ish) — no TI / SIEM.

Scores Technitium query-log rows in-process. Burst window is in-memory
(per panel process); resets on restart — acceptable for MVP.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict, deque
from typing import Any

# --- thresholds (tunable) ---
LABEL_LEN_SOFT = 25
LABEL_LEN_HARD = 40
ENTROPY_SOFT = 3.3
ENTROPY_HARD = 4.0
ENTROPY_MIN_LEN = 12
DEPTH_SOFT = 5
SCORE_SUSPICIOUS = 3
SCORE_HIGH = 6
BURST_WINDOW_SEC = 60.0
BURST_UNIQUE = 8
BURST_SCORE = 3

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

# client_ip -> deque[(monotonic_ts, qname_key)]
_burst: dict[str, deque[tuple[float, str]]] = defaultdict(deque)


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


def _note_burst(client_ip: str, qname: str, now: float | None = None) -> int:
    """Return burst score contribution; updates sliding window."""
    ip = (client_ip or "").strip() or "?"
    key = _norm_qname(qname).rstrip(".")
    if not key or len(key) < 3:
        return 0
    t = now if now is not None else time.monotonic()
    dq = _burst[ip]
    dq.append((t, key))
    cutoff = t - BURST_WINDOW_SEC
    while dq and dq[0][0] < cutoff:
        dq.popleft()
    # cap memory
    while len(dq) > 500:
        dq.popleft()
    unique = {k for _, k in dq}
    if len(unique) >= BURST_UNIQUE:
        return BURST_SCORE
    return 0


def score_query(
    *,
    qname: str,
    qtype: str = "",
    client_ip: str = "",
    rcode: str = "",
    response_type: str = "",
    track_burst: bool = True,
) -> dict[str, Any]:
    """
    Return {score, level, reasons: [str], entropy, maxLabelLen, depth}.
    level: ok | suspicious | high
    """
    reasons: list[str] = []
    score = 0
    labels = _labels(qname)
    depth = len(labels)
    max_len = max((len(x) for x in labels), default=0)
    # entropy on longest label (ignore TLD-ish last label if multi)
    candidates = labels[:-1] if len(labels) > 1 else labels
    best_ent = 0.0
    best_lab = ""
    for lab in candidates:
        if len(lab) < ENTROPY_MIN_LEN:
            continue
        # strip hyphens for entropy of "randomness"
        core = re.sub(r"[^a-z0-9]", "", lab.lower())
        if len(core) < ENTROPY_MIN_LEN:
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

    if max_len >= LABEL_LEN_HARD:
        score += 3
        reasons.append(f"label_len>={LABEL_LEN_HARD}")
    elif max_len >= LABEL_LEN_SOFT:
        score += 2
        reasons.append(f"label_len>={LABEL_LEN_SOFT}")

    if best_ent >= ENTROPY_HARD and len(best_lab) >= ENTROPY_MIN_LEN:
        score += 3
        reasons.append(f"entropy>={ENTROPY_HARD}")
    elif best_ent >= ENTROPY_SOFT and len(best_lab) >= ENTROPY_MIN_LEN:
        score += 2
        reasons.append(f"entropy>={ENTROPY_SOFT}")

    if depth >= DEPTH_SOFT:
        score += 1
        reasons.append(f"depth>={DEPTH_SOFT}")

    qt = (qtype or "").strip().upper()
    if qt in _RARE_QTYPES:
        score += 2
        reasons.append(f"qtype={qt or 'rare'}")

    # NXDOMAIN storms often accompany DGA; light bump
    rc = (rcode or "").strip().upper()
    rt = (response_type or "").strip()
    if rc in ("NXDOMAIN", "NAMEERROR") or "Blocked" in rt:
        # don't score blocked alone — but NXDOMAIN + entropy already counted
        if rc in ("NXDOMAIN", "NAMEERROR") and score >= 2:
            score += 1
            reasons.append("nxdomain")

    if track_burst:
        # count odd-looking names toward per-client burst
        if score >= 2 or max_len >= 16 or best_ent >= ENTROPY_SOFT:
            b = _note_burst(client_ip, qname)
            if b:
                score += b
                reasons.append(f"burst>={BURST_UNIQUE}/{int(BURST_WINDOW_SEC)}s")

    if score >= SCORE_HIGH:
        level = "high"
    elif score >= SCORE_SUSPICIOUS:
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


def enrich_entries(
    entries: list[dict[str, Any]],
    *,
    suspicious_only: bool = False,
) -> list[dict[str, Any]]:
    """Attach suspicion to each entry; optionally drop level=ok."""
    out: list[dict[str, Any]] = []
    # Chronological for burst (API often returns newest first)
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
        )
        row = dict(e)
        row["suspicion"] = sus
        scored_rev.append(row)
    # back to original order (newest first)
    scored = list(reversed(scored_rev))
    if not suspicious_only:
        return scored
    for row in scored:
        lvl = (row.get("suspicion") or {}).get("level")
        if lvl in ("suspicious", "high"):
            out.append(row)
    return out
