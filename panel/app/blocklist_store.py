from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .blocklist_presets import PRESET_BLOCK_LISTS, merge_presets_disabled
from .config import settings


def _path() -> Path:
    return Path(settings.panel_data_dir) / "blocklists.yml"


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    kind = item.get("kind") if item.get("kind") in ("block", "allow") else "block"
    note = str(item.get("note") or "").strip()
    out = {
        "url": url,
        "kind": kind,
        "disabled": bool(item.get("disabled")),
    }
    if note:
        out["note"] = note
    return out


def _preset_note(url: str) -> str:
    key = url.strip().lower()
    for p in PRESET_BLOCK_LISTS:
        if p["url"].strip().lower() == key:
            return str(p.get("note") or "").strip()
    return ""


def read_items() -> list[dict[str, Any]]:
    path = _path()
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("items") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw:
        if isinstance(x, dict):
            n = _normalize_item(x)
            if n:
                # curated captions — always from presets for known URLs
                pn = _preset_note(n["url"])
                if pn:
                    n["note"] = pn
                out.append(n)
    return out


def write_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = {f"{x['kind']}\0{x['url'].lower()}": x for x in read_items()}
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for x in items:
        n = _normalize_item(x) if isinstance(x, dict) else None
        if not n:
            continue
        key = f"{n['kind']}\0{n['url'].lower()}"
        if key in seen:
            continue
        seen.add(key)
        pn = _preset_note(n["url"])
        if pn:
            n["note"] = pn
        elif not n.get("note"):
            if key in prev and prev[key].get("note"):
                n["note"] = prev[key]["note"]
        cleaned.append(n)
    text = yaml.safe_dump({"items": cleaned}, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return cleaned


def encode_line(item: dict[str, Any]) -> str:
    s = ("!" + item["url"]) if item.get("kind") == "allow" else item["url"]
    if item.get("disabled"):
        s = "#" + s
    return s


def parse_line(raw: str) -> dict[str, Any] | None:
    s = str(raw or "").strip()
    if not s:
        return None
    disabled = False
    if s.startswith("#"):
        disabled = True
        s = s[1:].strip()
        if not s:
            return None
    kind = "block"
    if s.startswith("!"):
        kind = "allow"
        s = s[1:].strip()
        if not s:
            return None
    return {"url": s, "kind": kind, "disabled": disabled}


def items_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in lines:
        item = parse_line(line)
        if item:
            out.append(item)
    return out


def lines_from_items(items: list[dict[str, Any]]) -> list[str]:
    return [encode_line(x) for x in items]


def technitium_urls(items: list[dict[str, Any]]) -> str:
    """Только включённые — Technitium выкидывает набор из одних #."""
    enabled = []
    for x in items:
        if x.get("disabled"):
            continue
        enabled.append(("!" + x["url"]) if x.get("kind") == "allow" else x["url"])
    return ",".join(enabled) if enabled else "false"


def ensure_presets() -> list[dict[str, Any]]:
    items = read_items()
    lines = lines_from_items(items)
    merged_lines = merge_presets_disabled(lines)
    # merge_presets_disabled adds #url for missing; re-parse
    merged_items = items_from_lines(merged_lines)
    # keep enabled state from existing for same url
    by_key = {f"{x['kind']}\0{x['url'].lower()}": x for x in items}
    final: list[dict[str, Any]] = []
    seen: set[str] = set()
    for x in merged_items:
        key = f"{x['kind']}\0{x['url'].lower()}"
        if key in seen:
            continue
        seen.add(key)
        if key in by_key:
            final.append(by_key[key])
        else:
            # new preset → disabled
            final.append({**x, "disabled": True})
    # also keep any existing not in presets order after
    for x in items:
        key = f"{x['kind']}\0{x['url'].lower()}"
        if key not in seen:
            final.append(x)
            seen.add(key)
    return write_items(final)


def seed_from_presets_only() -> list[dict[str, Any]]:
    """Если пусто — записать все пресеты выключенными."""
    items = read_items()
    if items:
        return ensure_presets()
    seeded = [
        {
            "url": p["url"],
            "kind": p.get("kind") or "block",
            "disabled": True,
            "note": str(p.get("note") or "").strip(),
        }
        for p in PRESET_BLOCK_LISTS
    ]
    return write_items(seeded)
