"""Panel UI preferences (ui.yml) — timezone display, etc."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Default: МСК (UTC+3) — CLAUDE.md / SKELETON
DEFAULT_TIMEZONE = "Europe/Moscow"
ALLOWED_TIMEZONES = (
    "Europe/Moscow",  # UTC+3
    "UTC",
    "local",  # browser local
)

# Query Logs budget ≈ 2 GiB. ~800 B/row mixed answers → ~2.5M rows.
DEFAULT_MAX_LOG_RECORDS = 2_500_000
DEFAULT_MAX_LOG_DAYS = 90
MIN_MAX_LOG_RECORDS = 1_000
MAX_MAX_LOG_RECORDS = 20_000_000
MIN_MAX_LOG_DAYS = 0  # 0 = no age cleanup (Technitium)
MAX_MAX_LOG_DAYS = 3650
BYTES_PER_ROW_ESTIMATE = 800


def _data_dir() -> Path:
    path = Path(os.environ.get("PANEL_DATA_DIR", "/var/lib/panel"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ui_cfg_path() -> Path:
    return _data_dir() / "ui.yml"


def _load_ui_cfg() -> dict[str, Any]:
    cfg = _ui_cfg_path()
    if not cfg.is_file():
        return {}
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_ui_cfg(data: dict[str, Any]) -> None:
    cfg = _ui_cfg_path()
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def normalize_timezone(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in ALLOWED_TIMEZONES:
        return raw
    # aliases
    if raw in ("MSK", "UTC+3"):
        return "Europe/Moscow"
    if raw in ("GMT", "Z", "Etc/UTC"):
        return "UTC"
    if raw in ("browser", "auto"):
        return "local"
    raise ValueError(
        "Timezone must be Europe/Moscow (UTC+3), UTC, or local (browser)"
    )


def read_timezone() -> str:
    data = _load_ui_cfg()
    try:
        return normalize_timezone(data.get("timezone") or DEFAULT_TIMEZONE)
    except ValueError:
        return DEFAULT_TIMEZONE


def write_timezone(timezone: str) -> str:
    tz = normalize_timezone(timezone)
    data = _load_ui_cfg()
    data["timezone"] = tz
    _save_ui_cfg(data)
    return tz


def read_log_allowed_queries() -> bool:
    """If False (default) — persist only blocked DNS in Query Logs DB."""
    data = _load_ui_cfg()
    if "logAllowedQueries" in data:
        return bool(data.get("logAllowedQueries"))
    return False


def write_log_allowed_queries(enabled: bool) -> bool:
    data = _load_ui_cfg()
    data["logAllowedQueries"] = bool(enabled)
    _save_ui_cfg(data)
    return bool(enabled)


def normalize_max_log_records(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("maxLogRecords must be an integer") from exc
    if n < MIN_MAX_LOG_RECORDS or n > MAX_MAX_LOG_RECORDS:
        raise ValueError(
            f"maxLogRecords must be {MIN_MAX_LOG_RECORDS}…{MAX_MAX_LOG_RECORDS}"
        )
    return n


def normalize_max_log_days(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("maxLogDays must be an integer") from exc
    if n < MIN_MAX_LOG_DAYS or n > MAX_MAX_LOG_DAYS:
        raise ValueError(f"maxLogDays must be {MIN_MAX_LOG_DAYS}…{MAX_MAX_LOG_DAYS}")
    return n


def read_max_log_records() -> int:
    data = _load_ui_cfg()
    try:
        return normalize_max_log_records(
            data.get("maxLogRecords", DEFAULT_MAX_LOG_RECORDS)
        )
    except ValueError:
        return DEFAULT_MAX_LOG_RECORDS


def read_max_log_days() -> int:
    data = _load_ui_cfg()
    try:
        return normalize_max_log_days(data.get("maxLogDays", DEFAULT_MAX_LOG_DAYS))
    except ValueError:
        return DEFAULT_MAX_LOG_DAYS


def write_log_retention(max_log_records: int | None = None, max_log_days: int | None = None) -> dict[str, int]:
    data = _load_ui_cfg()
    if max_log_records is not None:
        data["maxLogRecords"] = normalize_max_log_records(max_log_records)
    if max_log_days is not None:
        data["maxLogDays"] = normalize_max_log_days(max_log_days)
    if "maxLogRecords" not in data:
        data["maxLogRecords"] = DEFAULT_MAX_LOG_RECORDS
    if "maxLogDays" not in data:
        data["maxLogDays"] = DEFAULT_MAX_LOG_DAYS
    _save_ui_cfg(data)
    return {
        "maxLogRecords": int(data["maxLogRecords"]),
        "maxLogDays": int(data["maxLogDays"]),
    }


def estimate_log_db_bytes(records: int | None = None) -> int:
    n = read_max_log_records() if records is None else int(records)
    return max(0, n) * BYTES_PER_ROW_ESTIMATE


def status() -> dict[str, Any]:
    tz = read_timezone()
    records = read_max_log_records()
    days = read_max_log_days()
    est = estimate_log_db_bytes(records)
    return {
        "timezone": tz,
        "timezoneLabel": {
            "Europe/Moscow": "UTC+3 (Moscow)",
            "UTC": "UTC",
            "local": "Browser local",
        }.get(tz, tz),
        "options": [
            {"value": "Europe/Moscow", "label": "UTC+3 (Moscow)"},
            {"value": "UTC", "label": "UTC"},
            {"value": "local", "label": "Browser local"},
        ],
        "logAllowedQueries": read_log_allowed_queries(),
        "maxLogRecords": records,
        "maxLogDays": days,
        "logDbBudgetBytes": 2 * 1024 * 1024 * 1024,
        "logDbEstimateBytes": est,
        "logDbEstimateLabel": f"~{est / (1024 * 1024):.0f} MiB @ ~{BYTES_PER_ROW_ESTIMATE} B/row",
    }
