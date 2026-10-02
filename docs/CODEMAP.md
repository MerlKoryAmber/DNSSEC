# DNS panel — карта кода

Полный скелет: **`docs/SKELETON.md`**.  
Handoff: `docs/agent_reports/handoff/CURRENT.md`.

## Назначение

Свой web-UI (FastAPI + JS) → Technitium + Blocky (hybrid B).  
Консоль Technitium `:5380` наружу не публикуется.

## Порты (default)

- Host: `53`, `853`, `9080` (HTTP UI + DoH), `9443` (HTTPS UI)
- DoH: nginx `/dns-query` → Technitium HTTPS `:443` (`enableDnsOverHttps`)
- Смена UI-портов: **`sudo dns ports`** (не API / не Settings Listen)
- Логи: docker `10m×3`; Technitium file 30d / stats 90d; Query Logs **2.5M / 90d** (~2 GiB), blocked-only default

## UI

**Dashboard** · Zones · Forwarders · Client protocol · Blocking · Query log · **Settings** (General · Blocking · Panel TLS cert)

## API (кратко)

| Путь | Данные |
|------|--------|
| `/api/dashboard` | Technitium stats + hybrid strip |
| `/api/blocking*` | Technitium Blocking + Allowed/Blocked + **Log** (Query Logs) |
| `/api/forwarders*` | Blocky YAML |
| `/api/zones*`, `/api/settings*` | Technitium |
| `/api/settings/panel-tls` | nginx PEM upload/status (порты — CLI) |
| `/api/settings/ui` | timezone, `logAllowedQueries`, `maxLogRecords`, `maxLogDays` |

## Ключевые файлы

`panel/app/routes.py`, `auth.py`, `session_secret.py`, `signals.py`, `technitium.py`, `blocky_config.py`, `tls_store.py`, `panel_tls.py`,  
`nginx/generated/http.conf`, `panel/static/js/app.js`, `panel/static/css/app.css`,  
`dns.sh`, `update.sh`, `uninstall.sh`, `install.sh`, `docker-host-proxy.sh`,  
`panel/Dockerfile`, `blocky-watch/Dockerfile`,  
`docs/adr/0002-hybrid-blocky.md`, `docs/patterns/cli-menu-linux.md`

## Прокси

- Runtime: compose `x-proxy-guard` (пусто в dns-*)
- Pull: `docker-host-proxy.sh` → dockerd systemd
- Build: `build.args` + Dockerfile `ARG`
