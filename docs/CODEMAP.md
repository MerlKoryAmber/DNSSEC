# DNS panel — карта кода

Полный скелет: **`docs/SKELETON.md`**.  
Handoff (передача агенту): **`docs/agent_reports/handoff/CURRENT.md`**.

## Назначение

Свой web-UI (FastAPI + JS) → Technitium + Blocky (hybrid B).  
Консоль Technitium `:5380` наружу не публикуется.

## Порты (default)

- Host: `53`, `853`, `9080` (HTTP UI + DoH), `9443` (HTTPS UI)
- Lab: **`172.22.86.236`** → `/opt/dns`. Сосед **2fa_*** (podman) держит 80/443/8000/8030/1812 — не трогать.
- DoH: nginx `/dns-query` → Technitium HTTPS `:443` (`enableDnsOverHttps`)
- Смена UI-портов: **`sudo dns ports`** (не API). `80`/`443` только если свободны.
- Hard-ban портов: `53`, DoT, `5380` (+ реально занятые по `ss`)

## UI

**Dashboard** · Zones · Forwarders · Client protocol · Blocking · Query log · **Settings** (General: timezone / Theme / log budget · Cache · Blocking · Suspicion · Panel TLS)

Темы UI: `panel/static/mk-themes/` — `standard` · `forest` · `steampunk` · **`gold`** (default) · **`itheme`** (ITheme: сланец/циан Interros, без золота + «Три вулкана»). Переключение: Settings → Appearance / login.

## API (кратко)

| Путь | Данные |
|------|--------|
| `/api/dashboard` | Technitium stats + hybrid strip |
| `/api/blocking*` | Blocking + lists (`blockListZones`) + Allowed/Blocked + Log (`logAllowed` off → purge ok при ≥75% maxLogRecords; `suspicion`) |
| `/api/forwarders*` | Blocky YAML (`config/blocky/config.yml`) |
| `/api/zones*`, `/api/settings*` | Technitium |
| `/api/settings/panel-tls` | nginx PEM (порты — CLI) |
| `/api/settings/ui` | timezone, log budget |
| `/api/settings/cache` | Technitium `cacheMaximumEntries` / `saveCache`; `POST …/flush` |
| `/api/settings/suspicion` | auto-block + heuristics thresholds (`ui.yml` → `suspicion:`) |

## update keep-data — preserve

| Путь | Содержимое |
|------|------------|
| `config/technitium/` | зоны, protocols, blocking, logs |
| `config/blocky/` | Forwarders |
| `config/panel/` | ui.yml, secrets |
| `config/nginx/ssl/` | Panel TLS |
| `nginx/generated/` | HTTP conf |
| `.env`, `storage/` | порты, бэкапы |

## Ключевые файлы

`panel/app/routes.py`, `auth.py`, `blocky_glue.py`, `blocky_querylog.py`, `session_secret.py`, `signals.py`, `technitium.py`, `blocky_config.py`, `tls_store.py`, `panel_tls.py`, `dns_suspicion.py` (skip mail-auth + DNSBL/URIBL),  
`dns.sh`, `update.sh`, `uninstall.sh`, `install.sh`, `docker-host-proxy.sh`, `sync-blocky-forwarder.sh`,  

`panel/Dockerfile`, `blocky-watch/Dockerfile`,  
`docs/adr/0002-hybrid-blocky.md`, `docs/patterns/cli-menu-linux.md`

## Прокси

- Runtime: `x-proxy-guard` (кроме Technitium)
- Technitium blocklists: `dns_sync_technitium_proxy_env` → `TECHNITIUM_HTTP(S)_PROXY` в `.env` из системы
- Pull: `docker-host-proxy.sh`
- Build: `build.args` + Dockerfile `ARG`
