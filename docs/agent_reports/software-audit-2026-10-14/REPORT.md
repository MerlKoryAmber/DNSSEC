# Software audit — DNS panel / hybrid B

| | |
|--|--|
| Дата | **2026-10-14 ~15:00 МСК** |
| Роль | независимый аудитор (только чтение) |
| Scope | репозиторий `C:\code\dns` — код + docs |
| Вне scope | lab SSH/docker live, `.env` значения, git commit/push |
| Метод | `SKELETON` → handoff → `CODEMAP` → ADR 0001/0002 → точечный Read |
| Вердикт | **Архитектура hybrid B в целом соответствует ADR0002. Критичных дыр «panel→docker.sock / :5380 наружу / секреты в git» нет. Есть HIGH по rate-limit spoof, паролям в query к Technitium, purge vs sqlite, отсутствие IPAM; docs handoff устарел.** |

«Принято» — только человек.

---

## 1. Архитектура (факт)

| Проверка | Факт | Вердикт |
|----------|------|---------|
| Hybrid B Technitium→Blocky | `docs/adr/0002-hybrid-blocky.md`; `blocky_glue.py` пишет IP + Udp + `dnssecValidation=false`; Blocky без host :53 | PASS |
| :5380 не наружу | `docker-compose.yml`: `"127.0.0.1:5380:5380"` | PASS |
| Panel без docker.sock | volumes panel — config/ssl/env; sock только у `blocky-watch` | PASS |
| Signals вместо sock | `signals.py` → `nginx.hup` / `nginx.recreate`; watch читает `/signals` | PASS |
| nginx stale IP | `nginx.conf` `resolver 127.0.0.11`; `panel_locations.conf` variable `proxy_pass` | PASS |
| Proxy split | `x-proxy-guard` на mesh; Technitium `TECHNITIUM_*_PROXY`; sync в `docker-host-proxy.sh` `dns_sync_technitium_proxy_env` | PASS |
| Fixed Blocky IP | `ipv4_address: ${DNS_BLOCKY_IP:-172.18.0.100}` | см. F-03 |

---

## 2. Находки

### CRITICAL

*(нет подтверждённых CRITICAL в коде без live-эксплойта)*

---

### HIGH

#### F-01 — Login rate-limit обходится через `X-Forwarded-For`

- **Факт:** `auth.py` `_client_ip` берёт **первый** элемент `X-Forwarded-For`. nginx: `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` — **дописывает** клиентский XFF, не затирает.
- **Следствие:** атакующий шлёт `X-Forwarded-For: <новый-IP>` → лимит 20/5мин на IP не держит.
- **Приоритет:** HIGH (bruteforce Technitium login через panel).

#### F-02 — Пароли Technitium в query string (panel→API)

- **Факт:** `technitium.py` `login` / `change_password` — `GET` с `pass` / `newPass` в params. httpx логирует URL при debug; прокси/access-логи Technitium могут видеть query.
- **Следствие:** утечка пароля в логах стека при включённом verbose.
- **Приоритет:** HIGH (дизайн API Technitium; panel не экранирует).

#### F-03 — `dns_net` без явного IPAM subnet под `172.18.0.100`

- **Факт:** `docker-compose.yml` сети `dns_net` — **нет** `ipam.config.subnet`, но у blocky задан `ipv4_address: 172.18.0.100`.
- **Следствие:** если пул Docker выдаст другой префикс — recreate/up падает или IP ≠ glue. `sync-blocky-forwarder.sh` только WARN.
- **Приоритет:** HIGH (хрупкость hybrid B на «нечистом» Docker host).

#### F-04 — Purge sqlite на каждом `GET /blocking/log`

- **Факт:** `routes.py` при `logAllowedQueries=false` вызывает `ql.purge_allowed_low_risk()` (до 250×2000 строк, открытие `querylogs.db` из volume Technitium). Ошибки глотаются `except Exception: pass`.
- **Следствие:** гонка с писателем Query Logs app; лаг UI; silent fail → диск снова забивается ok-строками.
- **Приоритет:** HIGH (данные/диск/гонки).

#### F-05 — Upload zip → Technitium Apps без проверки содержимого

- **Факт:** `POST /blocking/log/install` — лимит 50 MB, имя файла как есть → `apps_install_zip`. Нет magic/`PK` check, нет allowlist имени app beyond константы на стороне panel (имя app фиксировано `Query Logs (Sqlite)`, zip произвольный).
- **Следствие:** любой валидный session token панели может скормить Technitium произвольный app zip (поверхность = доверие к Technitium install).
- **Приоритет:** HIGH (authenticated RCE-класс через apps API, если Technitium исполняет код app).

---

### MEDIUM

#### F-06 — Silent `except` на критичном glue / lifespan

- **Факт:** `auth.py` login: `ensure_technitium_points_at_blocky` в `except Exception: pass`. `main.py` lifespan: `ensure_session_secret` / TLS bootstrap тоже silent.
- **Следствие:** hybrid B может не выставиться после login без сигнала; слабый secret останется если bootstrap упал.
- **Приоритет:** MEDIUM.

#### F-07 — Нет panel RBAC

- **Факт:** любой валидный Technitium token (`Depends(get_client)`) → zones/forwarders/blocking/TLS/apps install. Проверок group/role в panel нет.
- **Следствие:** limited Technitium user (если создан) = полный admin панели.
- **Приоритет:** MEDIUM (зависит от multi-user в Technitium).

#### F-08 — Session cookie: `URLSafeSerializer` без TTL в подписи

- **Факт:** `auth.py` — подпись без expiry; TTL только `max_age` cookie + жизнь token Technitium.
- **Следствие:** украденная cookie валидна, пока Technitium token жив (и cookie не протух на клиенте).
- **Приоритет:** MEDIUM. Смягчение: `HttpOnly` + `SameSite=strict` + `secure` при HTTPS.

#### F-09 — `blocky-watch` + полный `docker.sock`

- **Факт:** by design (`SKELETON`). Watch может `docker restart` / `compose … force-recreate nginx`.
- **Следствие:** компрометация volume `config/panel/signals` или самого watch = управление контейнерами проекта.
- **Приоритет:** MEDIUM (архитектурный blast radius; panel sock не имеет — хорошо).

#### F-10 — Technitium image `latest`

- **Факт:** `docker.io/technitium/dns-server:latest` без pin digest/tag.
- **Следствие:** непредсказуемый upgrade / supply drift.
- **Приоритет:** MEDIUM.

#### F-11 — Login fail counter in-memory

- **Факт:** `_LOGIN_FAILS` сбрасывается при restart panel.
- **Следствие:** recreate panel обнуляет throttle (плюс F-01).
- **Приоритет:** MEDIUM.

---

### LOW

#### F-12 — CSRF: нет Origin/CSRF-token

- **Факт:** cookie session + `SameSite=strict`; UI same-origin через nginx.
- **Следствие:** классический cross-site POST с cookie маловероятен; защита = SameSite, не double-submit.
- **Приоритет:** LOW.

#### F-13 — Security headers только на `location /`

- **Факт:** `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` в `panel_locations.conf` только у `/`, не у `/api/` и DoH.
- **Приоритет:** LOW.

#### F-14 — XSS UI: в основном `escapeHtml`

- **Факт:** `app.js` массово экранирует qname/url/ошибки в `innerHTML`. Статический HTML-каркас без user data — ок.
- **Приоритет:** LOW / NOTE (регрессии возможны при новых строках без escape).

#### F-15 — Path traversal uploads

- **Факт:** TLS/PEM пишутся в фиксированные пути (`tls_store.write_pfx` → `ssl/dns-tls.pfx`; `panel_tls` → `panel.{crt,key}`). Filename пользователя не входит в path.
- **Вердикт:** path traversal **не найден** для cert uploads.

#### F-16 — SKELETON API не знает `POST /blocking/log/install`

- **Факт:** маршрут есть в `routes.py`; в §5 SKELETON только `ensure`.
- **Приоритет:** LOW (docs drift).

---

### NOTE

#### N-01 — Handoff `CURRENT.md` устарел vs реальность репо/скелета

- Handoff: «Docker **нет**», «`/opt/dns` пока пусто», «Первый install» в открытом; ветка `@ 4d931c1`.
- SKELETON / CODEMAP: lab `172.22.86.236`, стек описан как рабочий; suspicion уже в коде.
- **Не аудит lab** — только drift документа передачи.

#### N-02 — ADR 0002 §«Не в этом ADR»: Blocked UI = TODO

- В продукте Blocking через Technitium уже есть (`routes.py` `/blocking*`, SKELETON ownership). ADR текст отстал.

#### N-03 — CODEMAP UI-список без Suspicion

- CODEMAP: Settings `(General · Blocking · Panel TLS)`; API suspicion есть. SKELETON UI — Suspicion есть.

#### N-04 — Секреты в git

- `.gitignore`: `.env`, `session_secret`, `technitium_admin.pass`, `config/nginx/ssl/*`, technitium data. `.env.example` — плейсхолдер secret. **Секреты в tracked files не найдены** (поверхностно по политике ignore).

#### N-05 — Фичи по карте (кратко)

| Фича | Код | Заметка |
|------|-----|---------|
| Blocking/lists | `routes.py` + `blocklist_store.py` | ок |
| Query log + purge blocked+risk | `query_logs.purge_allowed_low_risk` ASC cursor | логика верная; см. F-04 |
| dns_suspicion DKIM/DNSBL skips | `_SKIP_LABELS`, `_SKIP_ZONE_NEEDLES` | ок |
| forwarders / glue | `blocky_config` in-place write; `blocky_glue` | ок; silent login — F-06 |
| TECHNITIUM_*_PROXY sync | `dns_sync_technitium_proxy_env` | ок |
| nginx resolver | есть | ок |

#### N-06 — `sync-blocky-forwarder.sh` дефолт `admin`/`admin`

- Хост install/update best-effort; watch mode `DNS_FWD_CHECK_ONLY=1` без пароля. Ожидаемо для first-boot; после смены пароля sync на хосте skip → login glue.

---

## 3. Docs drift (явные)

| Где | Что |
|-----|-----|
| `docs/agent_reports/handoff/CURRENT.md` | состояние lab/Docker/install не актуально относительно SKELETON |
| `docs/adr/0002-hybrid-blocky.md` | Blocked TODO vs реализованный Blocking |
| `docs/CODEMAP.md` UI | нет Suspicion в списке экранов |
| `docs/SKELETON.md` §5 API | нет `POST /blocking/log/install` |

Код ↔ SKELETON по портам/ownership/docker.sock — **согласованы**.

---

## 4. Что не проверялось

- Live lab (SSH/dig/compose ps) — запрет заказчика.
- Реальные значения `/opt/dns/.env`, ACL корп-прокси.
- Полный ручной XSS fuzz / dependency CVE scan.
- Поведение Technitium Apps sandbox при malicious zip (нужен live).

---

## 5. Топ для родителя (сжато)

1. **HIGH** F-01 XFF spoof → login rate-limit  
2. **HIGH** F-02 пароли в GET query к Technitium  
3. **HIGH** F-03 нет IPAM под fixed Blocky IP  
4. **HIGH** F-04 purge sqlite на каждый GET log  
5. **HIGH** F-05 zip install apps без валидации  
6. **MEDIUM** F-06 silent glue/lifespan  
7. **MEDIUM** F-07 нет RBAC в panel  
8. **NOTE** handoff/ADR/CODEMAP drift  

Синтаксис ключевых модулей (`auth`, `routes`, `query_logs`, `dns_suspicion`, `blocky_glue`): **ok** (локальный `ast.parse`).
