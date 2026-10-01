from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class TechnitiumError(Exception):
    def __init__(self, message: str, status: str = "error", raw: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.raw = raw or {}


class TechnitiumClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or settings.technitium_url).rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict:
        url = f"{self.base_url}{path}"
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, url, params=clean, headers=self._headers())
                try:
                    data = r.json()
                except Exception as exc:
                    raise TechnitiumError(f"Некорректный ответ Technitium HTTP {r.status_code}") from exc
        except httpx.TimeoutException as exc:
            raise TechnitiumError(f"Technitium timeout ({path})") from exc
        status = data.get("status")
        if status == "ok":
            return data
        if status == "invalid-token":
            raise TechnitiumError("Сессия истекла", status="invalid-token", raw=data)
        raise TechnitiumError(
            data.get("errorMessage") or data.get("innerErrorMessage") or "Ошибка Technitium",
            status=status or "error",
            raw=data,
        )

    async def login(self, user: str, password: str) -> dict:
        return await self._request(
            "GET",
            "/api/user/login",
            {"user": user, "pass": password, "includeInfo": "true"},
        )

    async def logout(self) -> dict:
        return await self._request("GET", "/api/user/logout")

    async def session_info(self) -> dict:
        return await self._request("GET", "/api/user/session/get", {"includeInfo": "true"})

    async def change_password(
        self,
        current_password: str,
        new_password: str,
        totp: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"pass": current_password, "newPass": new_password}
        if totp:
            params["totp"] = totp
        return await self._request("GET", "/api/user/changePassword", params)

    async def zones_list(self, page: int = 1, per_page: int = 100, filter_type: str | None = None) -> dict:
        return await self._request(
            "GET",
            "/api/zones/list",
            {
                "pageNumber": page,
                "zonesPerPage": per_page,
                "filterType": filter_type,
            },
        )

    async def zone_create(self, params: dict[str, Any]) -> dict:
        return await self._request("GET", "/api/zones/create", params)

    async def zone_delete(self, zone: str) -> dict:
        return await self._request("GET", "/api/zones/delete", {"zone": zone})

    async def records_get(self, zone: str, domain: str | None = None) -> dict:
        return await self._request(
            "GET",
            "/api/zones/records/get",
            {
                "zone": zone,
                "domain": domain or zone,
                "listZone": "true",
            },
        )

    async def records_add(self, params: dict[str, Any]) -> dict:
        return await self._request("GET", "/api/zones/records/add", params)

    async def records_update(self, params: dict[str, Any]) -> dict:
        return await self._request("GET", "/api/zones/records/update", params)

    async def records_delete(self, params: dict[str, Any]) -> dict:
        return await self._request("GET", "/api/zones/records/delete", params)

    async def settings_get(self) -> dict:
        return await self._request("GET", "/api/settings/get")

    async def settings_set(self, params: dict[str, Any]) -> dict:
        return await self._request("GET", "/api/settings/set", params)

    async def dns_resolve(
        self,
        server: str,
        domain: str = "example.com",
        qtype: str = "A",
        protocol: str = "Udp",
    ) -> dict:
        return await self._request(
            "GET",
            "/api/dnsClient/resolve",
            {
                "server": server,
                "domain": domain,
                "type": qtype,
                "protocol": protocol,
            },
        )

    async def _request_text(self, method: str, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}{path}"
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        if self.token and "token" not in clean:
            clean["token"] = self.token
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.request(method, url, params=clean, headers=self._headers())
            if r.status_code >= 400:
                raise TechnitiumError(f"Technitium HTTP {r.status_code}")
            # export may be plain text; error JSON still possible
            ctype = (r.headers.get("content-type") or "").lower()
            if "json" in ctype:
                data = r.json()
                if data.get("status") == "invalid-token":
                    raise TechnitiumError("Сессия истекла", status="invalid-token", raw=data)
                if data.get("status") not in (None, "ok"):
                    raise TechnitiumError(
                        data.get("errorMessage") or "Ошибка Technitium",
                        status=data.get("status") or "error",
                        raw=data,
                    )
            return r.text

    async def allowed_list_export(self) -> list[str]:
        text = await self._request_text("GET", "/api/allowed/export")
        return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    async def blocked_list_export(self) -> list[str]:
        text = await self._request_text("GET", "/api/blocked/export")
        return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    async def allowed_add(self, domain: str) -> dict:
        return await self._request("GET", "/api/allowed/add", {"domain": domain})

    async def allowed_delete(self, domain: str) -> dict:
        return await self._request("GET", "/api/allowed/delete", {"domain": domain})

    async def allowed_flush(self) -> dict:
        return await self._request("GET", "/api/allowed/flush")

    async def allowed_import(self, domains: list[str]) -> dict:
        return await self._request_form("POST", "/api/allowed/import", {"allowedZones": ",".join(domains)})

    async def blocked_add(self, domain: str) -> dict:
        return await self._request("GET", "/api/blocked/add", {"domain": domain})

    async def blocked_delete(self, domain: str) -> dict:
        return await self._request("GET", "/api/blocked/delete", {"domain": domain})

    async def blocked_flush(self) -> dict:
        return await self._request("GET", "/api/blocked/flush")

    async def blocked_import(self, domains: list[str]) -> dict:
        return await self._request_form("POST", "/api/blocked/import", {"blockedZones": ",".join(domains)})

    async def _request_form(self, method: str, path: str, form: dict[str, Any]) -> dict:
        url = f"{self.base_url}{path}"
        params = {}
        if self.token:
            params["token"] = self.token
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.request(
                method,
                url,
                params=params,
                data=form,
                headers=self._headers(),
            )
            try:
                data = r.json()
            except Exception as exc:
                raise TechnitiumError(f"Некорректный ответ Technitium HTTP {r.status_code}") from exc
        status = data.get("status")
        if status == "ok":
            return data
        if status == "invalid-token":
            raise TechnitiumError("Сессия истекла", status="invalid-token", raw=data)
        raise TechnitiumError(
            data.get("errorMessage") or data.get("innerErrorMessage") or "Ошибка Technitium",
            status=status or "error",
            raw=data,
        )

    async def force_update_block_lists(self) -> dict:
        return await self._request("GET", "/api/settings/forceUpdateBlockLists")

    async def temporary_disable_blocking(self, minutes: int) -> dict:
        return await self._request(
            "GET",
            "/api/settings/temporaryDisableBlocking",
            {"minutes": minutes},
        )

    async def dashboard_stats(self, stats_type: str = "LastHour", utc: bool = True) -> dict:
        return await self._request(
            "GET",
            "/api/dashboard/stats/get",
            {
                "type": stats_type,
                "utc": "true" if utc else "false",
            },
        )

    async def dashboard_metrics(self) -> dict:
        return await self._request("GET", "/api/dashboard/metrics/json")

    async def apps_list(self) -> dict:
        return await self._request("GET", "/api/apps/list")

    async def apps_list_store(self) -> dict:
        return await self._request("GET", "/api/apps/listStoreApps", timeout=8.0)

    async def apps_download_and_install(self, name: str, url: str) -> dict:
        return await self._request(
            "GET",
            "/api/apps/downloadAndInstall",
            {"name": name, "url": url},
            timeout=20.0,
        )

    async def apps_install_zip(self, name: str, zip_bytes: bytes, filename: str = "app.zip") -> dict:
        url = f"{self.base_url}/api/apps/install"
        params: dict[str, str] = {"name": name}
        if self.token:
            params["token"] = self.token
        files = {"appZip": (filename, zip_bytes, "application/zip")}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(url, params=params, files=files, headers=self._headers())
                try:
                    data = r.json()
                except Exception as exc:
                    raise TechnitiumError(f"Некорректный ответ Technitium HTTP {r.status_code}") from exc
        except httpx.TimeoutException as exc:
            raise TechnitiumError("Technitium timeout (/api/apps/install)") from exc
        status = data.get("status")
        if status == "ok":
            return data
        if status == "invalid-token":
            raise TechnitiumError("Сессия истекла", status="invalid-token", raw=data)
        raise TechnitiumError(
            data.get("errorMessage") or data.get("innerErrorMessage") or "Ошибка Technitium",
            status=status or "error",
            raw=data,
        )

    async def apps_config_get(self, name: str) -> dict:
        return await self._request("GET", "/api/apps/config/get", {"name": name})

    async def apps_config_set(self, name: str, config: str) -> dict:
        return await self._request(
            "GET",
            "/api/apps/config/set",
            {"name": name, "config": config},
        )

    async def logs_query(self, params: dict[str, Any]) -> dict:
        return await self._request("GET", "/api/logs/query", params)
