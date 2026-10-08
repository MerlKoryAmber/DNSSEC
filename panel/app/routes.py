from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .auth import get_client
from .technitium import TechnitiumClient, TechnitiumError

router = APIRouter(prefix="/api", tags=["dns"])


def _map_error(exc: TechnitiumError) -> HTTPException:
    code = 401 if getattr(exc, "status", None) == "invalid-token" else 400
    return HTTPException(status_code=code, detail=exc.message)


class ZoneCreate(BaseModel):
    zone: str = Field(min_length=1)
    type: str = Field(description="Primary|Secondary|Stub|Forwarder")
    primaryNameServerAddresses: Optional[str] = None
    initializeForwarder: Optional[bool] = True
    protocol: Optional[str] = None
    forwarder: Optional[str] = None
    dnssecValidation: Optional[bool] = None


class RecordBody(BaseModel):
    domain: str
    type: str
    value: Optional[str] = None
    ttl: Optional[int] = None
    ptr: Optional[bool] = None
    # extras for various types
    preference: Optional[int] = None
    exchange: Optional[str] = None
    nameServer: Optional[str] = None
    rname: Optional[str] = None
    text: Optional[str] = None
    priority: Optional[int] = None
    weight: Optional[int] = None
    port: Optional[int] = None
    target: Optional[str] = None
    cname: Optional[str] = None
    forwarder: Optional[str] = None
    protocol: Optional[str] = None
    newValue: Optional[str] = None
    newTtl: Optional[int] = None


class SettingsUpdate(BaseModel):
    forwarders: Optional[str] = Field(
        default=None,
        description="Comma-separated addresses. Protocol via forwarderProtocol.",
    )
    forwarderProtocol: Optional[str] = Field(
        default=None,
        description="Udp|Tcp|Tls|Https|Quic — one protocol for all forwarders",
    )
    concurrentForwarding: Optional[bool] = None
    enableDnsOverHttp: Optional[bool] = None
    enableDnsOverTls: Optional[bool] = None
    enableDnsOverHttps: Optional[bool] = None
    dnsOverHttpPort: Optional[int] = None
    dnsOverTlsPort: Optional[int] = None
    dnsOverHttpsPort: Optional[int] = None
    dnsServerDomain: Optional[str] = None


@router.get("/zones")
async def list_zones(
    page: int = 1,
    per_page: int = 100,
    filter_type: Optional[str] = None,
    client: TechnitiumClient = Depends(get_client),
):
    try:
        return await client.zones_list(page, per_page, filter_type)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.post("/zones")
async def create_zone(body: ZoneCreate, client: TechnitiumClient = Depends(get_client)):
    params: dict[str, Any] = {"zone": body.zone, "type": body.type}
    if body.primaryNameServerAddresses:
        params["primaryNameServerAddresses"] = body.primaryNameServerAddresses
    if body.type == "Forwarder":
        params["initializeForwarder"] = str(body.initializeForwarder).lower()
        if body.protocol:
            params["protocol"] = body.protocol
        if body.forwarder:
            params["forwarder"] = body.forwarder
        if body.dnssecValidation is not None:
            params["dnssecValidation"] = str(body.dnssecValidation).lower()
    try:
        return await client.zone_create(params)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.delete("/zones/{zone_name}")
async def delete_zone(zone_name: str, client: TechnitiumClient = Depends(get_client)):
    try:
        return await client.zone_delete(zone_name)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.get("/zones/{zone_name}/records")
async def get_records(zone_name: str, client: TechnitiumClient = Depends(get_client)):
    try:
        return await client.records_get(zone_name)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.post("/zones/{zone_name}/records")
async def add_record(zone_name: str, body: RecordBody, client: TechnitiumClient = Depends(get_client)):
    params = body.model_dump(exclude_none=True)
    params["zone"] = zone_name
    try:
        return await client.records_add(params)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.put("/zones/{zone_name}/records")
async def update_record(zone_name: str, body: RecordBody, client: TechnitiumClient = Depends(get_client)):
    params = body.model_dump(exclude_none=True)
    params["zone"] = zone_name
    try:
        return await client.records_update(params)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.delete("/zones/{zone_name}/records")
async def delete_record(zone_name: str, body: RecordBody, client: TechnitiumClient = Depends(get_client)):
    params = body.model_dump(exclude_none=True)
    params["zone"] = zone_name
    try:
        return await client.records_delete(params)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.get("/settings")
async def get_settings(client: TechnitiumClient = Depends(get_client)):
    try:
        return await client.settings_get()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.put("/settings")
async def put_settings(body: SettingsUpdate, client: TechnitiumClient = Depends(get_client)):
    params: dict[str, Any] = {}
    data = body.model_dump(exclude_none=True)
    want_tls = data.get("enableDnsOverTls") is True or data.get("enableDnsOverHttps") is True
    if want_tls:
        try:
            cur = await client.settings_get()
            path = ((cur.get("response") or cur).get("dnsTlsCertificatePath") or "").strip()
        except TechnitiumError as exc:
            raise _map_error(exc) from exc
        if not path:
            raise HTTPException(
                status_code=400,
                detail="DoT / direct DoH require a TLS certificate (.pfx). Upload it first.",
            )
    for key, val in data.items():
        if isinstance(val, bool):
            params[key] = str(val).lower()
        else:
            params[key] = val
    try:
        return await client.settings_set(params)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.post("/settings/dns-tls-cert")
async def upload_dns_tls_cert(
    file: UploadFile = File(...),
    password: str = Form(""),
    client: TechnitiumClient = Depends(get_client),
):
    """Загрузка PKCS#12 (.pfx) для DoT / DoH / DoQ (dnsTlsCertificatePath)."""
    from . import tls_store

    name = (file.filename or "").lower()
    if not (name.endswith(".pfx") or name.endswith(".p12")):
        raise HTTPException(status_code=400, detail="Нужен файл .pfx / .p12 с приватным ключом")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 5 МБ)")

    tls_store.write_pfx(raw)
    try:
        data = await client.settings_set(tls_store.settings_params_for_pfx(password))
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {
        "status": "ok",
        "mode": "pfx",
        "filename": file.filename,
        "pathSet": True,
        "passwordSet": bool(password),
        "response": data,
    }


@router.post("/settings/dns-tls-pem")
async def upload_dns_tls_pem(
    key: UploadFile = File(...),
    chain: UploadFile = File(...),
    key_password: str = Form(""),
    client: TechnitiumClient = Depends(get_client),
):
    """PEM private key + certificate (chain) → PKCS#12 for Technitium."""
    from . import tls_store

    key_raw = await key.read()
    chain_raw = await chain.read()
    if not key_raw:
        raise HTTPException(status_code=400, detail="Empty private key file")
    if not chain_raw:
        raise HTTPException(status_code=400, detail="Empty certificate / chain file")
    if len(key_raw) > 256 * 1024 or len(chain_raw) > 256 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 256 KB each)")
    try:
        pfx = tls_store.pem_to_pfx(key_raw, chain_raw, key_password=key_password or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tls_store.write_pfx(pfx)
    tls_store.save_pem_sidecars(key_raw, chain_raw)
    try:
        # PEM path exported to pfx without password
        data = await client.settings_set(tls_store.settings_params_for_pfx(""))
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {
        "status": "ok",
        "mode": "pem",
        "keyName": key.filename,
        "chainName": chain.filename,
        "pathSet": True,
        "response": data,
    }


@router.get("/settings/panel-tls")
async def get_panel_tls(_client: TechnitiumClient = Depends(get_client)):
    from . import panel_tls

    try:
        panel_tls.ensure_self_signed()
    except Exception:
        pass
    return panel_tls.status()


@router.post("/settings/panel-tls")
async def upload_panel_tls(
    key: UploadFile = File(...),
    cert: UploadFile = File(...),
    _client: TechnitiumClient = Depends(get_client),
):
    """PEM private key + certificate (chain) for panel nginx HTTPS."""
    from . import panel_tls

    key_raw = await key.read()
    cert_raw = await cert.read()
    if not key_raw:
        raise HTTPException(status_code=400, detail="Empty private key file")
    if not cert_raw:
        raise HTTPException(status_code=400, detail="Empty certificate file")
    if len(key_raw) > 256 * 1024 or len(cert_raw) > 256 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 256 KB each)")
    try:
        panel_tls.write_pem(key_raw, cert_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reload = await panel_tls.reload_nginx()
    st = panel_tls.status()
    return {"status": "ok", "reload": reload, **st}


class UiPrefsBody(BaseModel):
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    logAllowedQueries: bool | None = None
    maxLogRecords: int | None = None
    maxLogDays: int | None = None


@router.get("/settings/ui")
async def get_ui_prefs(_client: TechnitiumClient = Depends(get_client)):
    from . import ui_prefs

    return {"status": "ok", **ui_prefs.status()}


@router.put("/settings/ui")
async def put_ui_prefs(body: UiPrefsBody, _client: TechnitiumClient = Depends(get_client)):
    from . import query_logs as ql
    from . import ui_prefs

    if (
        body.timezone is None
        and body.logAllowedQueries is None
        and body.maxLogRecords is None
        and body.maxLogDays is None
    ):
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        if body.timezone is not None:
            ui_prefs.write_timezone(body.timezone)
        filter_result = None
        if body.logAllowedQueries is not None:
            ui_prefs.write_log_allowed_queries(body.logAllowedQueries)
            filter_result = ql.apply_log_allowed_mode(log_allowed=body.logAllowedQueries)
        retention_result = None
        if body.maxLogRecords is not None or body.maxLogDays is not None:
            ui_prefs.write_log_retention(
                max_log_records=body.maxLogRecords,
                max_log_days=body.maxLogDays,
            )
            try:
                retention_result = await ql.apply_retention(_client)
            except TechnitiumError as exc:
                raise _map_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out = {"status": "ok", **ui_prefs.status()}
    if filter_result is not None:
        out["logFilter"] = filter_result
    if retention_result is not None:
        out["logRetention"] = retention_result
    return out


class ForwarderItem(BaseModel):
    addr: str = Field(min_length=1)
    kind: str = Field(description="classic|dot|doh")


class ForwardersTestBody(BaseModel):
    items: list[ForwarderItem]


class ForwardersSaveBody(BaseModel):
    items: list[ForwarderItem]


@router.get("/forwarders")
async def get_forwarders(_client: TechnitiumClient = Depends(get_client)):
    """Upstream list from Blocky (hybrid B)."""
    from . import blocky_config

    return {"items": blocky_config.read_forwarders()}


@router.put("/forwarders")
async def put_forwarders(body: ForwardersSaveBody, client: TechnitiumClient = Depends(get_client)):
    """Write Blocky upstreams (strict order) + point Technitium at Blocky."""
    from . import blocky_config
    from .config import settings as app_settings

    cleaned: list[dict[str, str]] = []
    for item in body.items:
        addr, kind = _normalize_forwarder(item.addr, item.kind)
        err = _validate_forwarder_format(addr, kind)
        if err:
            raise HTTPException(status_code=400, detail=f"{addr}: {err}")
        cleaned.append({"addr": addr, "kind": kind})
    try:
        blocky_config.write_forwarders(cleaned)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot write Blocky config: {exc}") from exc
    # Technitium → Blocky (IP: hostname «blocky» sometimes даёт Resolver exception)
    import socket

    try:
        blocky_target = socket.gethostbyname(app_settings.blocky_upstream)
    except OSError:
        blocky_target = app_settings.blocky_upstream
    try:
        await client.settings_set(
            {
                "forwarders": blocky_target,
                "forwarderProtocol": "Udp",
                "concurrentForwarding": "false",
                # DNSSEC validation ломает ответы от forwarder-only цепочки (Blocky)
                "dnssecValidation": "false",
            }
        )
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True, "items": blocky_config.read_forwarders()}


def _normalize_forwarder(addr: str, kind: str) -> tuple[str, str]:
    """Normalize address for test + Blocky encoding."""
    a = addr.strip()
    k = kind if kind in ("classic", "dot", "doh") else "classic"
    if k == "doh":
        if not a.lower().startswith(("http://", "https://")):
            a = "https://" + a
        from urllib.parse import urlparse

        p = urlparse(a)
        if not p.path or p.path == "/":
            a = f"{p.scheme}://{p.netloc}/dns-query"
    elif k == "dot":
        low = a.lower()
        if low.startswith("tls://"):
            a = a[6:]
        if low.startswith("tcp-tls:"):
            a = a[8:]
        if a.endswith(":853"):
            a = a[:-4]
    elif k == "classic":
        if a.lower().startswith("tls://"):
            a = a[6:]
            k = "dot"
        elif a.lower().startswith("https://"):
            k = "doh"
            a = _normalize_forwarder(a, "doh")[0]
    return a, k


def _validate_forwarder_format(addr: str, kind: str) -> str | None:
    a = addr.strip()
    if not a:
        return "Address is empty"
    if kind == "doh":
        if not a.lower().startswith("https://"):
            return "DoH address must be an https:// URL"
        return None
    if kind == "dot":
        if " " in a:
            return "Invalid DoT address"
        return None
    if "://" in a and not a.lower().startswith("tls://"):
        return "Classic DNS expects IP or hostname, not a URL"
    return None


@router.post("/forwarders/test")
async def test_forwarders(body: ForwardersTestBody, client: TechnitiumClient = Depends(get_client)):
    """Проверка формата и доступности forwarders через dnsClient/resolve."""
    results = []
    proto_map = {"classic": "Udp", "dot": "Tls", "doh": "Https"}
    all_ok = True
    for item in body.items:
        addr, kind = _normalize_forwarder(item.addr, item.kind)
        fmt_err = _validate_forwarder_format(addr, kind)
        entry = {"addr": addr, "kind": kind, "ok": False, "message": ""}
        if fmt_err:
            entry["message"] = fmt_err
            all_ok = False
            results.append(entry)
            continue
        try:
            data = await client.dns_resolve(
                server=addr,
                domain="example.com",
                qtype="A",
                protocol=proto_map[kind],
            )
            result = (data.get("response") or {}).get("result") or {}
            rcode = result.get("RCODE") or result.get("rcode") or ""
            if str(rcode).lower() in ("noerror", "nxdomain", ""):
                meta = result.get("Metadata") or {}
                rtt = meta.get("RoundTripTime") or ""
                entry["ok"] = True
                entry["message"] = f"OK{(' · ' + rtt) if rtt else ''}"
            else:
                entry["message"] = f"Upstream RCODE: {rcode or 'unknown'}"
                all_ok = False
        except TechnitiumError as exc:
            entry["message"] = exc.message
            all_ok = False
        results.append(entry)
    return {"ok": all_ok, "results": results}


# --- Blocking (Technitium Settings → Blocking + Allowed/Blocked) ---

_BLOCKING_KEYS = (
    "enableBlocking",
    "allowTxtBlockingReport",
    "temporaryDisableBlockingTill",
    "blockingBypassList",
    "blockingType",
    "customBlockingAddresses",
    "blockingAnswerTtl",
    "blockListUrls",
    "blockListUpdateIntervalHours",
    "blockListNextUpdatedOn",
)


class BlockingUpdate(BaseModel):
    enableBlocking: Optional[bool] = None
    allowTxtBlockingReport: Optional[bool] = None
    blockingBypassList: Optional[list[str]] = None
    blockingType: Optional[str] = Field(default=None, description="NxDomain|AnyAddress|CustomAddress")
    customBlockingAddresses: Optional[list[str]] = None
    blockingAnswerTtl: Optional[int] = None
    blockListUrls: Optional[list[str]] = None
    blockListUpdateIntervalHours: Optional[int] = None


class DomainBody(BaseModel):
    domain: str = Field(min_length=1)


class DomainsImportBody(BaseModel):
    domains: list[str]


class TemporaryDisableBody(BaseModel):
    minutes: int = Field(ge=1, le=10080)


def _blocking_view(response: dict[str, Any]) -> dict[str, Any]:
    return {k: response.get(k) for k in _BLOCKING_KEYS}


@router.get("/blocking")
async def get_blocking(client: TechnitiumClient = Depends(get_client)):
    from . import blocklist_store

    try:
        data = await client.settings_get()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    resp = data.get("response") or data
    view = _blocking_view(resp)
    # каталог листов — в панели (disabled переживает Technitium)
    items = blocklist_store.read_items()
    view["blockListUrls"] = blocklist_store.lines_from_items(items)
    view["blockListItems"] = items
    return {"response": view}


@router.post("/blocking/seed-presets")
async def seed_blocklist_presets(client: TechnitiumClient = Depends(get_client)):
    """Curated URL-листы в store выключенными; в Technitium — только enabled."""
    from . import blocklist_store

    try:
        items = blocklist_store.seed_from_presets_only()
        await client.settings_set({"blockListUrls": blocklist_store.technitium_urls(items)})
        fresh = await client.settings_get()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    view = _blocking_view(fresh.get("response") or fresh)
    view["blockListUrls"] = blocklist_store.lines_from_items(items)
    view["blockListItems"] = items
    return {"ok": True, "count": len(items), "response": view}


@router.put("/blocking")
async def put_blocking(body: BlockingUpdate, client: TechnitiumClient = Depends(get_client)):
    from . import blocklist_store

    params: dict[str, Any] = {}
    data = body.model_dump(exclude_none=True)
    store_items = None
    for key, val in data.items():
        if key == "blockListUrls" and isinstance(val, list):
            store_items = blocklist_store.write_items(blocklist_store.items_from_lines([str(x) for x in val]))
            params[key] = blocklist_store.technitium_urls(store_items)
            continue
        if isinstance(val, bool):
            params[key] = str(val).lower()
        elif isinstance(val, list):
            params[key] = ",".join(str(x).strip() for x in val if str(x).strip()) or "false"
        else:
            params[key] = val
    try:
        if params:
            await client.settings_set(params)
        fresh = await client.settings_get()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    view = _blocking_view(fresh.get("response") or fresh)
    items = store_items if store_items is not None else blocklist_store.read_items()
    view["blockListUrls"] = blocklist_store.lines_from_items(items)
    view["blockListItems"] = items
    return {"ok": True, "response": view}


@router.post("/blocking/force-update-lists")
async def force_update_block_lists(client: TechnitiumClient = Depends(get_client)):
    try:
        return await client.force_update_block_lists()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.post("/blocking/temporary-disable")
async def temporary_disable_blocking(body: TemporaryDisableBody, client: TechnitiumClient = Depends(get_client)):
    try:
        return await client.temporary_disable_blocking(body.minutes)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc


@router.get("/blocking/allowed")
async def list_allowed(client: TechnitiumClient = Depends(get_client)):
    try:
        items = await client.allowed_list_export()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"items": items}


@router.post("/blocking/allowed")
async def add_allowed(body: DomainBody, client: TechnitiumClient = Depends(get_client)):
    domain = body.domain.strip().rstrip(".").lower()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain is required")
    try:
        await client.allowed_add(domain)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True, "domain": domain}


@router.delete("/blocking/allowed/{domain}")
async def delete_allowed(domain: str, client: TechnitiumClient = Depends(get_client)):
    try:
        await client.allowed_delete(domain)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True}


@router.post("/blocking/allowed/flush")
async def flush_allowed(client: TechnitiumClient = Depends(get_client)):
    try:
        await client.allowed_flush()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True}


@router.post("/blocking/allowed/import")
async def import_allowed(body: DomainsImportBody, client: TechnitiumClient = Depends(get_client)):
    domains = [d.strip().rstrip(".").lower() for d in body.domains if d.strip()]
    if not domains:
        raise HTTPException(status_code=400, detail="No domains")
    try:
        await client.allowed_import(domains)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True, "count": len(domains)}


@router.get("/blocking/blocked")
async def list_blocked(client: TechnitiumClient = Depends(get_client)):
    try:
        items = await client.blocked_list_export()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"items": items}


@router.post("/blocking/blocked")
async def add_blocked(body: DomainBody, client: TechnitiumClient = Depends(get_client)):
    domain = body.domain.strip().rstrip(".").lower()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain is required")
    try:
        await client.blocked_add(domain)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True, "domain": domain}


@router.delete("/blocking/blocked/{domain}")
async def delete_blocked(domain: str, client: TechnitiumClient = Depends(get_client)):
    try:
        await client.blocked_delete(domain)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True}


@router.post("/blocking/blocked/flush")
async def flush_blocked(client: TechnitiumClient = Depends(get_client)):
    try:
        await client.blocked_flush()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True}


@router.post("/blocking/blocked/import")
async def import_blocked(body: DomainsImportBody, client: TechnitiumClient = Depends(get_client)):
    domains = [d.strip().rstrip(".").lower() for d in body.domains if d.strip()]
    if not domains:
        raise HTTPException(status_code=400, detail="No domains")
    try:
        await client.blocked_import(domains)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc
    return {"ok": True, "count": len(domains)}


_DASHBOARD_TYPES = {"LastHour", "LastDay", "LastWeek", "LastMonth", "LastYear"}


def _chart_pair(chart: dict | None) -> dict[str, Any]:
    if not isinstance(chart, dict):
        return {"labels": [], "data": []}
    labels = chart.get("labels") or []
    datasets = chart.get("datasets") or []
    data = []
    if datasets and isinstance(datasets[0], dict):
        data = datasets[0].get("data") or []
    return {"labels": labels, "data": data}


def _main_series(main: dict | None) -> dict[str, Any]:
    if not isinstance(main, dict):
        return {
            "labelFormat": "HH:mm",
            "labels": [],
            "series": {},
        }
    series: dict[str, list] = {}
    for ds in main.get("datasets") or []:
        if not isinstance(ds, dict):
            continue
        label = str(ds.get("label") or "").strip() or "Series"
        series[label] = ds.get("data") or []
    return {
        "labelFormat": main.get("labelFormat") or "HH:mm",
        "labels": main.get("labels") or [],
        "series": series,
    }


@router.get("/dashboard")
async def get_dashboard(
    type: str = "LastHour",  # noqa: A002 — query param name matches Technitium
    client: TechnitiumClient = Depends(get_client),
):
    """Technitium dashboard stats + hybrid status strip."""
    from . import blocky_config

    stats_type = type if type in _DASHBOARD_TYPES else "LastHour"
    try:
        raw = await client.dashboard_stats(stats_type, utc=True)
        settings_raw = await client.settings_get()
    except TechnitiumError as exc:
        raise _map_error(exc) from exc

    resp = raw.get("response") or raw
    settings = settings_raw.get("response") or settings_raw
    forwarders = blocky_config.read_forwarders()
    metrics = None
    try:
        m = await client.dashboard_metrics()
        metrics = m.get("response") or m
    except TechnitiumError:
        metrics = None

    from . import host_stats

    resources = host_stats.read_cpu_ram()
    services = await host_stats.probe_services()

    return {
        "type": stats_type,
        "stats": resp.get("stats") or {},
        "mainChart": _main_series(resp.get("mainChartData")),
        "queryResponse": _chart_pair(resp.get("queryResponseChartData")),
        "queryType": _chart_pair(resp.get("queryTypeChartData")),
        "protocolType": _chart_pair(resp.get("protocolTypeChartData")),
        "topClients": resp.get("topClients") or [],
        "topDomains": resp.get("topDomains") or [],
        "topBlockedDomains": resp.get("topBlockedDomains") or [],
        "hybrid": {
            "forwarders": forwarders,
            "forwarderCount": len(forwarders),
            "enableBlocking": bool(settings.get("enableBlocking")),
            "enableDnsOverTls": bool(settings.get("enableDnsOverTls")),
            "enableDnsOverHttps": bool(settings.get("enableDnsOverHttps")),
            "dnsOverTlsPort": settings.get("dnsOverTlsPort"),
            "dnsOverHttpsPort": settings.get("dnsOverHttpsPort"),
        },
        "metrics": metrics,
        "resources": resources,
        "services": services,
    }


_BLOCKED_RESPONSE_TYPES = {
    "Blocked",
    "UpstreamBlocked",
    "CacheBlocked",
    "Authoritative",
    "Recursive",
    "Cached",
}


@router.get("/blocking/log")
async def get_blocking_log(
    page: int = 1,
    perPage: int = 50,
    qname: str | None = None,
    clientIp: str | None = None,
    protocol: str | None = None,
    responseType: str | None = None,
    rcode: str | None = None,
    qtype: str | None = None,
    start: str | None = None,
    end: str | None = None,
    descending: bool = True,
    ensure: bool = True,
    suspiciousOnly: bool = False,
    client: TechnitiumClient = Depends(get_client),
):
    """Query logs filtered for blocked DNS (Technitium Query Logs app)."""
    from . import dns_suspicion
    from . import query_logs as ql

    try:
        if ensure:
            logger = await ql.ensure_query_logger(client, allow_download=False)
        else:
            listed = await client.apps_list()
            apps = (listed.get("response") or listed).get("apps") or []
            found = ql.find_query_logger(apps)
            if not found:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "missing-app",
                        "message": "Query Logs (Sqlite) not installed. Upload zip on Blocking → Log.",
                    },
                )
            logger = {"name": found[0], "classPath": found[1], "installedNow": False}
    except TechnitiumError as exc:
        if getattr(exc, "status", None) == "missing-app":
            raise HTTPException(
                status_code=409,
                detail={"code": "missing-app", "message": exc.message},
            ) from exc
        raise _map_error(exc) from exc

    # When filtering suspicious in-process, pull a wider page then trim.
    want = min(max(1, perPage), 200)
    fetch_n = min(200, max(want * 4, want)) if suspiciousOnly else want

    params: dict[str, Any] = {
        "name": logger["name"],
        "classPath": logger["classPath"],
        "pageNumber": max(1, page),
        "entriesPerPage": fetch_n,
        "descendingOrder": "true" if descending else "false",
    }
    if qname:
        q = qname.strip().rstrip(".").lower()
        # Technitium: без * — точное совпадение; с * — LIKE. Кусок имени → *piece*
        if q and "*" not in q:
            q = f"*{q}*"
        if q:
            params["qname"] = q
    if clientIp:
        params["clientIpAddress"] = clientIp.strip()
    if protocol:
        params["protocol"] = protocol.strip()
    if responseType and responseType in _BLOCKED_RESPONSE_TYPES:
        params["responseType"] = responseType
    if rcode:
        params["rcode"] = rcode.strip()
    if qtype:
        params["qtype"] = qtype.strip()
    if start:
        params["start"] = start.strip()
    if end:
        params["end"] = end.strip()

    try:
        raw = await client.logs_query(params)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc

    resp = raw.get("response") or raw
    entries = dns_suspicion.enrich_entries(
        list(resp.get("entries") or []),
        suspicious_only=suspiciousOnly,
    )
    if suspiciousOnly:
        entries = entries[:want]
    from . import ui_prefs

    log_allowed = ui_prefs.read_log_allowed_queries()
    return {
        "logger": logger,
        "logAllowedQueries": log_allowed,
        "pageNumber": resp.get("pageNumber") or page,
        "totalPages": resp.get("totalPages") or 1,
        "totalEntries": resp.get("totalEntries") or 0,
        "entries": entries,
        "suspiciousOnly": suspiciousOnly,
        "suspicionNote": (
            "Heuristics on fetched rows (entropy / label length / rare qtype / client burst). "
            "Not commercial TI. «Log allowed» needed to see non-blocked tunnel noise."
        ),
    }


@router.post("/blocking/log/ensure")
async def ensure_blocking_log(client: TechnitiumClient = Depends(get_client)):
    from . import query_logs as ql

    try:
        return await ql.ensure_query_logger(client, allow_download=True)
    except TechnitiumError as exc:
        if getattr(exc, "status", None) == "missing-app":
            raise HTTPException(
                status_code=409,
                detail={"code": "missing-app", "message": exc.message},
            ) from exc
        raise _map_error(exc) from exc


@router.post("/blocking/log/install")
async def install_blocking_log(
    file: UploadFile = File(...),
    client: TechnitiumClient = Depends(get_client),
):
    """Install Query Logs (Sqlite) from uploaded zip (offline lab)."""
    from . import query_logs as ql

    raw = await file.read()
    if len(raw) < 1000:
        raise HTTPException(status_code=400, detail="Empty or invalid zip")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Zip too large (max 50 MB)")
    name = file.filename or "QueryLogsSqliteApp.zip"
    try:
        return await ql.install_from_zip(client, raw, filename=name)
    except TechnitiumError as exc:
        raise _map_error(exc) from exc

