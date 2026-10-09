# Pattern: Linux CLI management menu (DNS Panel)

Дата: 2026-10-09, 13:50 МСК.  
Источник идеи: squid-panel `docs/patterns/cli-menu-linux.md`.  
Адаптация под `/opt/dns` + Docker Compose.  
Актуально с `main` (см. handoff CURRENT).

---

## Зачем

Одна команда на сервере — нумерованное меню и те же глаголы CLI:

- update / uninstall  
- status / restart (только dns-* контейнеры)  
- backup конфигов (+ DNS data)  
- URL панели, fix upstream forwarder  
- **сброс пароля входа в панель** (forgot → admin/admin)  
- **порты панели** HTTP/HTTPS + Enable HTTP (`dns ports`)

Язык меню — **панель**, без брендов движков (Technitium / Blocky) в пунктах.

---

## Контракт

| Правило | Деталь |
|---------|--------|
| Entry | `/usr/bin/dns` (обязательно). Дополнительно `/usr/local/bin/dns`. |
| Источник | `/opt/dns/dns.sh`; `install.sh` ставит в `/usr/bin/dns`. |
| Root | Только root / `sudo dns`. |
| Без аргументов | Интерактивное меню. |
| С аргументом | Сразу действие; exit ≠ 0 при ошибке. |
| Опасное | Confirm `[y/N]`; wipe данных — **два** confirm. |
| Не трогать | podman `2fa_*` (80/443/8000/8030/1812), чужие `/opt/*`. |
| Update | `update.sh` — clone GitHub, rsync кода; keep: technitium, panel, **blocky**, nginx ssl/generated, `.env`. |
| Язык меню | English labels (как UI), product-facing. |

---

## Меню DNS

```
1. Update (keep data)
2. Update + wipe DNS data
3. Uninstall
4. Reset panel admin password
5. Status
6. Restart stack
7. Restart nginx
8. Backup
9. Show panel URL
10. Fix upstream forwarder
11. Set panel ports (HTTP/HTTPS)
0. Exit
```

Подкоманды: `update`, `update-wipe`, `uninstall`, `password`, `status`,
`restart`, `restart-nginx`, `backup`, `url`, `fix-forwarder`, `ports`, `help`.

### `dns password`

Сброс пароля входа в панель **без** знания текущего (forgot):

1. confirm  
2. backup `config/technitium/auth.config` → `storage/backups/`  
3. stop `dns-technitium`  
4. rename `auth.config` → `resetadmin.config` (штатный recovery движка)  
5. start → login **admin / admin**  
6. после входа сменить пароль в UI  

Zones / lists / TLS не трогаем.

### `dns ports`

HTTP/HTTPS host ports + Enable HTTP (cleartext vs redirect to HTTPS).

Пишет: `.env` · `/etc/dns/install.env` · `config/panel/ui.yml` ·
`nginx/generated/http.conf` · firewalld (add new / remove old non-shared) ·
`compose up --force-recreate nginx panel`.

Неинтерактивно: `dns ports <http> <https> <on|off>`.

В веб-UI секции Listen **нет** (Panel TLS показывает порты read-only).

Мета: `/etc/dns/install.env` (`DNS_UI_PORT`, `DNS_UI_TLS_PORT`, `DNS_DOT_PORT`).

---

## Файлы

| Путь | Роль |
|------|------|
| `dns.sh` | CLI меню → `/usr/bin/dns` |
| `update.sh` | GitHub → `/opt/dns` (keep / wipe) |
| `uninstall.sh` | compose down + remove CLI (+ optional wipe) |
