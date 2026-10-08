# Handoff CURRENT — 2026-10-08 ~13:15 МСК

> **Новому агенту:** `docs/SKELETON.md` → этот файл → `docs/CODEMAP.md` →
> ADR/UI по задаче. Метод: `CLAUDE.md` (выше дефолта Cursor). Caveman (§13).

---

## Статус

**РЕАЛИЗОВАНО НО НЕ ПРИНЯТО** · lab выкладка suspicion/auto-block (локально, без commit)

Lab **`172.29.110.165`**: `/opt/dns`. Сосед **2fa_*** — не трогали.
`DNS_BIND_IP=172.29.110.165`.

Smoke: UI :9080 200 · Settings → **Suspicion** · `GET/PUT /api/settings/suspicion`
· prefs в `config/panel/ui.yml` → `suspicion:` · score high+entropy OK ·
autoBlock default **off** · dig noise `*.dga-lab.example` в лог.

«Принято» — только человек.

---

## Lab (актуально)

| | |
|--|--|
| Хост | `172.29.110.165` (el9 / CentOS Stream 9-совместимое) |
| SSH | `root@172.29.110.165` (пароль **не в git** — у Merl) |
| Каталог DNS | `/opt/dns` (пока пусто; `/opt` без проектов dns) |
| Docker | **нет** (есть **podman** у соседа) — `install.sh` поставит Docker CE |
| UI (после install) | http://172.29.110.165:9080/ · https://…:9443/ |

### Сосед (НЕ УБИВАТЬ)

Podman compose **2fa_***:

| Контейнер / порт | Заметка |
|------------------|---------|
| `2fa_web_1` | host **:80**, **:443** |
| `2fa_api_1` | host **:8000** |
| `2fa_express-bot_1` | host **:8030** |
| `2fa_radius_1` | RADIUS (host **:1812** udp) |
| db/redis/workers | без публикации наружу / внутренние |

`10.89.0.1:53` = **aardvark-dns** (podman) — не host DNS; наш `:53` на
`0.0.0.0` для Technitium обычно свободен (перед install — `ss` снова).

**Запрет:** `podman stop/rm` 2fa_*, `systemctl` чужого, чужие `/opt/*`,
занятые 80/443/8000/8030/1812. Наш стек — только `/opt/dns`, порты
53/853/9080/9443 (или `dns ports` если свободны).

Старый lab `192.168.0.178` — **архив**, не использовать.

---

## Репозиторий

| | |
|--|--|
| URL | https://github.com/MerlKoryAmber/DNSSEC |
| Ветка | `main` @ `4d931c1` |
| Workspace | `C:\code\dns` |

---

## Критично (коротко)

- Hybrid B: Technitium спереди → Blocky. ADR 0002.
- Порты UI: **`sudo dns ports`** (не веб). 80/443 панели — только если свободны.
- **update keep:** не затирает technitium / blocky / panel / ssl / generated / `.env`
- Прокси: dockerd drop-in + build.args; runtime `x-proxy-guard`
- Выкладка: scp → `/opt/dns` → человек смотрит → commit → отдельно push
- После recreate panel → часто `docker restart dns-nginx`

### Сессия 2026-10-02 (в main)

`5fb4172` proxy dockerd · `e990d5d` build proxy · `c5d401a` TLS upload UX ·
`eb1964a` dns ports · `8ccf078` 80/443 по ss · `4d931c1` keep blocky

---

## Открытое

- [ ] Первый install на `172.29.110.165` (не трогая 2fa)
- [ ] Smoke UI/DNS/DoH; приёмка человеком
- [ ] Если forwarders сбрасывались на старом хосте до `4d931c1` — здесь чистый старт

## Снимки

`CURRENT.md` (этот) · `2026-10-02.md` · `2026-10-01.md` (устарели по lab IP)
