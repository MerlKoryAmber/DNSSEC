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
| Хост | `192.168.0.178` CentOS Stream 9 |
| Каталог | `/opt/dns` |
| UI | `http://192.168.0.178:9080/` |
| Логин lab | Technitium `admin` / `admin` (не в git-секреты) |

**Публичные порты стека:** `53/tcp+udp`, `853/tcp` (DoT), `9080/tcp` (UI HTTP), `9443/tcp` (UI HTTPS).

**Не трогать:** `/opt/radiusproxy`, `/opt/spm`, контейнеры чужие, порты `80/443/8000/1812/1813`, `systemctl` чужого, `git push` / `git add .` без команды.

**Деплой:** scp точечно в `/opt/dns` → `docker compose -p dns up -d --build …` → человек смотрит → **потом** предложить commit → отдельным шагом push. После recreate `panel` — часто нужен `docker restart dns-nginx` (stale upstream → 502).

---

## 3. Сервисы (compose project `dns`)

| Контейнер | Роль | Host ports | Важно |
|-----------|------|------------|--------|
| `dns-technitium` | лицо DNS, зоны, client DoT/DoH, login | `53`, `853`, `127.0.0.1:5380` | forwarders → IP Blocky; `dnssecValidation=false` при hybrid |
| `dns-blocky` | recursive upstreams | **нет** | `config/blocky/config.yml`, `strategy: strict` |
| `dns-blocky-watch` | inotify: Blocky YAML + panel signals → restart blocky / HUP·recreate nginx | — | **единственный** docker.sock для panel-ops |
| `dns-panel` | FastAPI | internal `:8000` | mounts config; **без** docker.sock |
| `dns-nginx` | static UI + proxy | `9080→80`, `9443→443` | `/api`→panel, `/dns-query`→technitium:443 (HTTPS DoH); TLS `config/nginx/ssl` |

Сеть: `dns_net`. Blocky **не** публиковать на host :53.

**Прокси:** в compose у всех сервисов сброс `HTTP(S)_PROXY` + `NO_PROXY`
(localhost, имена сервисов, RFC1918). Иначе системный прокси хоста
утекает в контейнеры и ломает panel↔technitium / nginx↔panel.

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
| `install.sh` | первичная установка + CLI `/usr/bin/dns` |
| `update.sh` | update с GitHub (keep / wipe Technitium data) |
| `uninstall.sh` | compose down + remove CLI (+ optional wipe `/opt/dns`) |
| `dns.sh` | interactive CLI menu → `/usr/bin/dns` |
| `docs/patterns/cli-menu-linux.md` | паттерн меню (из squid-panel) |
| `config/blocky/config.yml` | upstreams Blocky (пишет panel) |
| `config/technitium/` | данные Technitium (volume) |
| `nginx/nginx.conf` | proxy UI/API/DoH + include generated HTTP |
| `nginx/generated/http.conf` | HTTP :80 serve vs 301→HTTPS (пишет panel) |
| `config/nginx/ssl/` | Panel TLS PEM `panel.{crt,key}` |

### Panel backend (`panel/app/`)
| Файл | Ответственность |
|------|-----------------|
| `main.py` | FastAPI app, mount static?, include routers |
| `config.py` | Settings: TECHNITIUM_*, BLOCKY_* |
| `auth.py` | `/api/auth/login|logout|me`, session cookie `SameSite=strict`; login rate-limit (fail/IP) |
| `session_secret.py` | если secret=default → файл `config/panel/session_secret` |
| `signals.py` | panel → `config/panel/signals/` (`nginx.hup` / `nginx.recreate`) для stack-watch |
| `routes.py` | zones, records, settings, **forwarders** |
| `technitium.py` | HTTP-клиент Technitium API |
| `blocky_config.py` | encode/decode/read/write Blocky YAML |
| `blocklist_presets.py` | curated blocklist URLs (seed выключенными) |
| `query_logs.py` | ensure Query Logs (Sqlite) + resolve logger |
| `host_stats.py` | CPU/RAM (/proc) + probes Technitium/Blocky/Nginx |
| `panel_tls.py` | Panel UI TLS (nginx PEM) + Listen; reload через signals (не docker.sock) |
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
| Query log | `routes.py` `/api/blocking/log*` + `query_logs.py` | `app.js` `#/query-log` | Technitium Query Logs Sqlite |
| Settings | `routes.py` + `panel_tls.py` | `app.js` `#/settings` | Blocking · **Panel TLS** |
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
  `PUT /settings/panel-tls/https-port` `{port,httpEnabled}` → `.env` + `nginx/generated/http.conf` + recreate nginx

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

- После recreate `panel` → 502 на `/api` → `docker restart dns-nginx`.
- Technitium forwarder = **IP** Blocky, не имя сервиса.
- **Host HTTP_PROXY в контейнерах** → service mesh ломается. Compose
  держит пустые `*_PROXY` + `NO_PROXY` (см. `x-proxy-guard`). Не прокидывать
  proxy из systemd/docker daemon в dns-* без NO_PROXY на `dns_net`.
- `dnssecValidation` must be off при forward через Blocky.
- **Client DoT/DoH:** нужен `.pfx` в `config/technitium/ssl/dns-tls.pfx`. Без
  сертификата DoT на :853 отвечает без peer cert / handshake fail. После
  загрузки cert — restart Technitium если TLS не поднялся.
  **DoH wire:** Technitium ≥15 — только HTTPS (`enableDnsOverHttps`, порт 443
  внутри контейнера). nginx `/dns-query` → `https://technitium:443` (`proxy_ssl_verify off`).
  HTTP `:8053` / `enableDnsOverHttp` → 403 «supported only on HTTPS».
- **Panel TLS:** PEM `config/nginx/ssl/panel.{crt,key}`; HTTPS `:9443` (порт из UI).
  HTTP on/off — `nginx/generated/http.conf` (serve vs 301→HTTPS). Save Listen → HUP + recreate nginx.
- **Upstream DoT (исходящий :853):** с lab `192.168.0.178` TCP/853 наружу =
  Connection refused (сеть/провайдер). Forwarders kind=DoT в Test/Save будут
  падать; DoH/Classic с lab работают. Не путать с client DoT на входящем 853.
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
