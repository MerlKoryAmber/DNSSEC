# DNS — SKELETON

> **Точка входа для агента.** Читать до любого grep / правок.
> Обновлять в том же заходе, что и структурные изменения (порты, маршруты, сервисы, ownership файлов).

Время: МСК (UTC+3). Владелец: Merl.

---

## 0. Порядок чтения (обязательный)

1. Этот файл — `docs/SKELETON.md`
2. Handoff — `docs/agent_reports/handoff/CURRENT.md`
3. Карта — `docs/CODEMAP.md` (детали файлов)
4. ADR по теме задачи из §6
5. Если UI — целиком `docs/design/UI_UX.md`
6. Только потом точечный Read файла из §4 (не grep «всего репо»)

Метод работы: `CLAUDE.md` (выше дефолта Cursor).

---

## 1. Что это

Свой web-UI управляет DNS-стеком на lab.  
Консоль Technitium (`:5380`) **наружу не отдаём**.

```
Клиент DNS ──► Technitium (53 / 853 / DoH)
                  ├─ auth zones → локально
                  └─ рекурсия → Blocky:53 (только dns_net)
                                    └─ upstreams strategy:strict
                                       (Classic / DoT / DoH по строкам, порядок = failover)
Клиент UI  ──► nginx:9080 → static + /api → panel → Technitium API + Blocky YAML
```

Вариант A (Blocky спереди) — **отвергнут**. См. ADR 0002.

---

## 2. Lab

| | |
|--|--|
| Хост | **`172.29.110.165`** (el9) — местная лаба с 2026-10-08 |
| SSH | `root@172.29.110.165` (пароль не в git) |
| Каталог | `/opt/dns` |
| UI | `http://172.29.110.165:9080/` · `https://172.29.110.165:9443/` |
| Логин панели | Technitium (не коммитить пароли) |
| Сосед | **2fa_*** (podman): :80 :443 :8000 :8030 :1812 — **не трогать** |
| Было | `192.168.0.178` — архив |

**Публичные порты стека (default):** `53/tcp+udp` (на lab с podman —
`DNS_BIND_IP`=LAN IP, не `0.0.0.0`), `853/tcp` (DoT), `9080/tcp` (UI HTTP),
`9443/tcp` (UI HTTPS).

**Не трогать:** podman `2fa_*`, чужие `/opt/*`, `systemctl` чужого, `git push` /
`git add .` без команды. Порты `80`/`443` панели — только если свободны
(`dns ports` + `ss`); на этой lab они заняты 2fa_web.

**Деплой:** scp точечно в `/opt/dns` → `docker compose -p dns up -d --build …` →
человек смотрит → **потом** предложить commit → отдельно push.
`install.sh` ставит Docker CE рядом с podman — **не** останавливать 2fa.

---

## 3. Сервисы (compose project `dns`)

| Контейнер | Роль | Host ports | Важно |
|-----------|------|------------|--------|
| `dns-technitium` | лицо DNS, зоны, client DoT/DoH, login | `53`, `853`, `127.0.0.1:5380` | forwarders → IP Blocky; `dnssecValidation=false`; outbound blocklists через `TECHNITIUM_HTTP(S)_PROXY` (+ `NO_PROXY` mesh) |
| `dns-blocky` | recursive upstreams | **нет** | `config/blocky/config.yml`, `strategy: strict`; IP **`172.18.0.100`** (`DNS_BLOCKY_IP`) — не плывёт после recreate |
| `dns-blocky-watch` | inotify: Blocky YAML + panel signals → restart blocky / HUP·recreate nginx | — | **единственный** docker.sock; после reload blocky — `sync-blocky-forwarder.sh` |
| `dns-panel` | FastAPI | internal `:8000` | mounts config; **без** docker.sock |
| `dns-nginx` | static UI + proxy | `9080→80`, `9443→443` | `/api`→panel, `/dns-query`→technitium:443; `resolver 127.0.0.11` + variable `proxy_pass` (без stale IP/502); TLS `config/nginx/ssl` |

Сеть: `dns_net`. Blocky **не** публиковать на host :53.

**Прокси (корп-хост — интернет только через proxy):**
- **Источники:** env → `/etc/environment` → `docker.service.d/*.conf` → `proxy=` в
  `/etc/dnf/dnf.conf` / `yum.conf`. Install/update пишут dockerd drop-in и
  **падают**, если Hub недоступен напрямую и proxy не найден (не висеть 0 B).
- **dockerd (FROM / pull слоёв):** drop-in
  `/etc/systemd/system/docker.service.d/http-proxy.conf` — без него `python:3.12-slim`
  висит на корп.
- **docker build RUN (pip/apk):** BuildKit ≠ proxy демона. Compose `build.args` +
  `ARG` в Dockerfiles; shell export перед `compose up --build`.
- **runtime dns-* (кроме Technitium):** `x-proxy-guard` — пустые `*_PROXY` + `NO_PROXY` (mesh).
- **Technitium outbound (block lists):** `dns_sync_technitium_proxy_env` при
  install/update пишет `TECHNITIUM_HTTP(S)_PROXY` в `.env` из системных
  HTTP(S)_PROXY. Mesh в `TECHNITIUM_NO_PROXY`. ACL — на корп-прокси.
  Пусто = напрямую. Не руками.

**Лимиты логов (диск):**
| Источник | Лимит |
|----------|--------|
| Docker `json-file` (все сервисы) | `max-size: 10m`, `max-file: 3` (~150 MB стек) |
| Technitium file log | `maxLogFileDays=30`, `logQueries=false` |
| Technitium stats | `maxStatFileDays=90` |
| Query Logs Sqlite | `maxLogRecords=2 500 000` (~2 GiB @ ~800 B/row), `maxLogDays=90`; Settings → General; **по умолчанию только blocked** (`logAllowedQueries=false`) |

---

## 4. Карта файлов (куда смотреть, не грепать)

### Docs
| Путь | Зачем |
|------|--------|
| `docs/SKELETON.md` | этот скелет |
| `docs/CODEMAP.md` | краткая карта + API |
| `docs/adr/0001-stack.md` | стек / порты |
| `docs/adr/0002-hybrid-blocky.md` | hybrid B, forwarders |
| `docs/design/UI_UX.md` | UX Interros/gold — сверка попунктно |
| `docs/agent_reports/handoff/CURRENT.md` | статус «сейчас» |
| `CLAUDE.md` | метод агента |

### Compose / config
| Путь | Зачем |
|------|--------|
| `docker-compose.yml` | сервисы, env, volumes |
| `install.sh` | первичная установка + CLI `/usr/bin/dns` + docker proxy |
| `update.sh` | update с GitHub (keep / wipe Technitium data) + docker proxy |
| `uninstall.sh` | compose down + remove CLI (+ optional wipe `/opt/dns`) |
| `dns.sh` | interactive CLI menu → `/usr/bin/dns` (в т.ч. `ports`) |
| `docker-host-proxy.sh` | systemd drop-in HTTP(S)_PROXY для dockerd pull |
| `sync-blocky-forwarder.sh` | Technitium forwarders → IP Blocky (update / watch / `dns` 10) |
| `blocky-watch/Dockerfile` | docker:cli + inotify (без runtime `apk`) |
| `docs/patterns/cli-menu-linux.md` | паттерн меню (из squid-panel) |
| `config/blocky/config.yml` | upstreams Blocky (пишет panel); **update keep исключает** — иначе сброс forwarders |
| `config/technitium/` | данные Technitium (volume) |
| `nginx/nginx.conf` | proxy UI/API/DoH + include generated HTTP |
| `nginx/generated/http.conf` | HTTP :80 serve vs 301→HTTPS (`dns ports` / panel_tls) |
| `config/nginx/ssl/` | Panel TLS PEM `panel.{crt,key}` |

### Panel backend (`panel/app/`)
| Файл | Ответственность |
|------|-----------------|
| `main.py` | FastAPI app, mount static?, include routers |
| `config.py` | Settings: TECHNITIUM_*, BLOCKY_* |
| `auth.py` | `/api/auth/login|logout|me`, session cookie `SameSite=strict`; login rate-limit (fail/IP) |
| `session_secret.py` | если secret=default → файл `config/panel/session_secret` |
| `blocky_glue.py` | Technitium→Blocky IP при login / PUT forwarders (без пароля на диске) |
| `signals.py` | panel → `config/panel/signals/` (`nginx.hup` / `nginx.recreate`) для stack-watch |
| `routes.py` | zones, records, settings, **forwarders** |
| `technitium.py` | HTTP-клиент Technitium API |
| `blocky_config.py` | encode/decode/read/write Blocky YAML |
| `blocklist_presets.py` | curated blocklist URLs (seed выключенными) |
| `query_logs.py` | ensure Query Logs (Sqlite) + resolve logger |
| `dns_suspicion.py` | эвристики tunnel/DGA-ish + prefs auto-block (`ui.yml` → `suspicion:`) |
| `host_stats.py` | CPU/RAM (/proc) + probes Technitium/Blocky/Nginx |
| `panel_tls.py` | Panel UI TLS (nginx PEM); listen ports пишет CLI `dns ports` |
| `ui_prefs.py` | UI prefs in `ui.yml` (timezone display, default Europe/Moscow) |
| `tls_store.py` | .pfx write + PEM key/chain → PKCS#12 |

### Panel UI (`panel/static/`)
| Файл | Ответственность |
|------|-----------------|
| `index.html` | shell + favicon + cache-bust `?v=` |
| `js/api.js` | `window.DnsApi` |
| `js/app.js` | hash-router, все экраны; brand-mark login/sidebar |
| `css/app.css` | Interros/gold (+ silver/bronze) как squid-panel |
| `css/inter-font.css` + `fonts/inter-*.ttf` | Inter локально (с squid-panel) |
| `img/brand-mascot.png` | маскот Interros (с squid-panel) |

### Ownership по фичам
| Фича | Backend | UI | Данные |
|------|---------|-----|--------|
| Login | `auth.py` | `app.js` login + user-menu change password | Technitium |
| Zones / records | `routes.py` | `app.js` zones/records | Technitium |
| Forwarders | `routes.py` + `blocky_config.py` | `app.js` `#/forwarders` | Blocky YAML + glue Technitium |
| Client protocol | `routes.py` settings | `app.js` `#/client-protocol` | Technitium |
| Blocking | `routes.py` `/api/blocking*` + `blocklist_store.py` | `app.js` `#/blocking` | Lists / Allowed / Blocked |
| Query log | `routes.py` `/api/blocking/log*` + `query_logs.py` + `dns_suspicion.py` + `blocky_querylog.py` | `app.js` `#/query-log` | Technitium rows + Risk; **Upstream** из Blocky CSV (`responseReason`) |
| Settings | `routes.py` + `panel_tls.py` + `dns_suspicion.py` | `#/settings` · General · Blocking · Suspicion · Panel TLS; порты — CLI | Suspicion: auto-block + пороги |
| Panel listen ports | `dns.sh` `ports` (+ `panel_tls.write_listen_settings`) | — | `.env` / `ui.yml` / `http.conf` |
| Dashboard | `routes.py` `/api/dashboard` + `technitium.py` + `host_stats.py` | `app.js` `#/dashboard` | Technitium stats + CPU/RAM + services |

---

## 5. API (prefix `/api`)

### Auth — `auth.py`
- `POST /auth/login` `{user,password}`
- `POST /auth/logout`
- `GET /auth/me`
- `POST /auth/change-password` `{currentPassword,newPassword,totp?}` → Technitium `user/changePassword`

### DNS — `routes.py`
- Zones: `GET/POST /zones`, `DELETE /zones/{name}`
- Records: `GET/POST/PUT/DELETE /zones/{name}/records`
- Settings (Technitium, **не** список Forwarders UI): `GET/PUT /settings`,
  `POST /settings/dns-tls-cert` (.pfx), `POST /settings/dns-tls-pem` (key+chain → pfx)
  `GET/POST /settings/panel-tls` (PEM key+cert → nginx HTTPS, HUP)
  Listen ports — **только CLI** `sudo dns ports` (не API)

- Forwarders (Blocky): `GET/PUT /forwarders`, `POST /forwarders/test`
- Blocking (Technitium): `GET/PUT /blocking`, force-update / temporary-disable,
  `GET/POST/DELETE /blocking/allowed|blocked`, flush, import
- Blocking log: `GET /blocking/log`, `POST /blocking/log/ensure` (Query Logs Sqlite)
- Dashboard: `GET /dashboard?type=LastHour|LastDay|LastWeek|LastMonth|LastYear`

### Glue при `PUT /forwarders`
1. Пишет `config/blocky/config.yml` (`upstreams.groups.default`, `strategy: strict`)
2. Technitium: `forwarders=<IP Blocky>`, `forwarderProtocol=Udp`, `concurrentForwarding=false`, `dnssecValidation=false`  
   (hostname `blocky` → Resolver exception; DNSSEC on → EDE RRSIG Missing)
3. `blocky-watch` рестартит Blocky по изменению файла

### UI hash-маршруты
`#/login` · `#/dashboard` · `#/zones` · `#/forwarders` · `#/client-protocol` · `#/blocking` · `#/query-log` · `#/settings` · `#/settings/blocking` · `#/settings/panel-tls`

---

## 6. ADR / решения

| ADR | Тема |
|-----|------|
| 0001 | Стек Technitium + panel + nginx:9080 |
| 0002 | Hybrid B: Technitium спереди, Blocky сзади; mixed types + sequential |

Открытый TODO: — (Blocked UI сделан как **Blocking** через Technitium).

---

## 7. Грабли (лаборатория)

- Stale upstream IP после recreate panel: nginx должен иметь `resolver` + variable `proxy_pass` (не `upstream { server panel:8000; }`).
- **update keep-data** раньше затирал `config/blocky/config.yml` дефолтом
  из GitHub → сброс Forwarders. С `4d931c1`: exclude `config/blocky/`
  (+ seed если файла нет).
- Technitium forwarder = **IP** Blocky, не имя сервиса.
- **Host HTTP_PROXY в контейнерах** → service mesh ломается. Compose
  держит пустые `*_PROXY` + `NO_PROXY` (см. `x-proxy-guard`) на panel/blocky/nginx.
  Technitium — отдельно `TECHNITIUM_*_PROXY` + `NO_PROXY` на mesh; не лить
  host proxy во все dns-*.
- **dockerd без proxy drop-in** → `docker pull` мимо корпоративного прокси.
  Чинится `docker-host-proxy.sh` (install/update). Контейнеры при этом
  остаются без proxy.
- `dnssecValidation` must be off при forward через Blocky.
- **Client DoT/DoH:** нужен `.pfx` в `config/technitium/ssl/dns-tls.pfx`. Без
  сертификата DoT на :853 отвечает без peer cert / handshake fail. После
  загрузки cert — restart Technitium если TLS не поднялся.
  **DoH wire:** Technitium ≥15 — только HTTPS (`enableDnsOverHttps`, порт 443
  внутри контейнера). nginx `/dns-query` → `https://technitium:443` (`proxy_ssl_verify off`).
  HTTP `:8053` / `enableDnsOverHttp` → 403 «supported only on HTTPS».
- **Panel TLS:** PEM `config/nginx/ssl/panel.{crt,key}`; HTTPS default `:9443`.
  HTTP on/off — `nginx/generated/http.conf` (serve vs 301→HTTPS).
  Смена портов / HTTP enable — **`sudo dns ports`**, не веб-UI.
- **Upstream DoT (исходящий :853):** с lab исходящий TCP/853 наружу может
  резаться сетью — не путать с client DoT на входящем 853.
- Писать Blocky YAML **in-place** (тот же inode), не rename через tmp→replace на file bind.
- Cache Technitium после смены DNSSEC: `/api/cache/flush` на :5380.
- Не `git add .`; секреты / `.env` не коммитить.
- Force-push нельзя.

---

## 8. Чеклист «готово» по изменению

- [ ] SKELETON / CODEMAP / handoff CURRENT обновлены, если менялись порты/маршруты/ownership
- [ ] ADR, если новое архитектурное решение
- [ ] Lab: scp + compose; проверка фактом (dig / API), не только HTTP 200
- [ ] UI: сверка `UI_UX.md` попунктно
- [ ] «Принято» — только человек
