"""Host CPU/RAM + DNS stack service probes (lab dashboard)."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

_prev_cpu: tuple[float, float] | None = None  # (idle+iowait+… total busy? → total, idle)


def _read_proc_stat() -> tuple[float, float] | None:
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            line = f.readline()
    except OSError:
        return None
    if not line.startswith("cpu "):
        return None
    parts = [float(x) for x in line.split()[1:]]
    if len(parts) < 4:
        return None
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)  # idle + iowait
    total = sum(parts)
    return total, idle


def read_cpu_ram() -> dict[str, Any]:
    """Best-effort host view via /proc (Docker usually sees host mem/load)."""
    global _prev_cpu
    out: dict[str, Any] = {
        "cpuPercent": None,
        "load1": None,
        "load5": None,
        "load15": None,
        "memUsedBytes": None,
        "memTotalBytes": None,
        "memPercent": None,
    }
    try:
        with open("/proc/loadavg", encoding="utf-8") as f:
            a, b, c = f.read().split()[:3]
        out["load1"] = float(a)
        out["load5"] = float(b)
        out["load15"] = float(c)
    except (OSError, ValueError):
        pass

    try:
        mem: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, rest = line.split(":", 1)
                num = rest.strip().split()[0]
                mem[key] = int(num) * 1024  # kB → bytes
        total = mem.get("MemTotal")
        avail = mem.get("MemAvailable")
        if total and avail is not None:
            used = total - avail
            out["memTotalBytes"] = total
            out["memUsedBytes"] = used
            out["memPercent"] = round(100.0 * used / total, 1)
    except (OSError, ValueError):
        pass

    cur = _read_proc_stat()
    if cur and _prev_cpu:
        dt = cur[0] - _prev_cpu[0]
        di = cur[1] - _prev_cpu[1]
        if dt > 0:
            out["cpuPercent"] = round(max(0.0, min(100.0, 100.0 * (1.0 - di / dt))), 1)
    if cur:
        _prev_cpu = cur
        if out["cpuPercent"] is None:
            # first hit: tiny sample
            time.sleep(0.08)
            cur2 = _read_proc_stat()
            if cur2:
                dt = cur2[0] - cur[0]
                di = cur2[1] - cur[1]
                if dt > 0:
                    out["cpuPercent"] = round(max(0.0, min(100.0, 100.0 * (1.0 - di / dt))), 1)
                _prev_cpu = cur2

    return out


async def _tcp_ok(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        del reader
        return True
    except Exception:
        return False


async def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(url)
            return r.status_code < 500
    except Exception:
        return False


async def probe_services() -> list[dict[str, Any]]:
    tech = (os.environ.get("TECHNITIUM_URL") or "http://technitium:5380").rstrip("/")
    blocky_host = os.environ.get("BLOCKY_UPSTREAM") or "blocky"
    nginx_url = os.environ.get("NGINX_INTERNAL_URL") or "http://nginx/"

    tech_ok, blocky_ok, nginx_ok = await asyncio.gather(
        _http_ok(f"{tech}/"),
        _tcp_ok(blocky_host, 53),
        _http_ok(nginx_url),
    )
    return [
        {"id": "technitium", "name": "Technitium", "ok": tech_ok},
        {"id": "blocky", "name": "Blocky", "ok": blocky_ok},
        {"id": "panel", "name": "Panel", "ok": True},
        {"id": "nginx", "name": "Nginx", "ok": nginx_ok},
    ]
