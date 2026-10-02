# Pattern: Linux CLI management menu (DNS Panel)

Дата: 2026-10-01, 22:40 МСК.  
Источник идеи: squid-panel `docs/patterns/cli-menu-linux.md`.  
Адаптация под `/opt/dns` + Docker Compose (Technitium + Blocky + panel).

---

## Зачем

Одна команда на сервере — нумерованное меню и те же глаголы CLI:

- update / uninstall  
- status / restart (только dns-* контейнеры)  
- backup конфигов (+ Technitium data)  
- URL панели, fix Blocky forwarder IP  
- смена пароля Technitium admin (через API)

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
| Не трогать | `/opt/radiusproxy`, `/opt/spm`, чужие контейнеры, порты 80/443/8000. |
| Update | `update.sh` — clone GitHub, rsync кода с сохранением data; cwd → `/tmp`. |
| Язык меню | English labels (как UI). |

---

## Меню DNS

```
1. Update (keep data)
2. Update + wipe Technitium data
3. Uninstall
4. Reset Technitium admin password
5. Status
6. Restart stack (compose)
7. Restart nginx
8. Backup config + Technitium data
9. Show panel URL
10. Fix Blocky forwarder IP
11. Set panel ports (HTTP/HTTPS)
0. Exit
```

Подкоманды: `update`, `update-wipe`, `uninstall`, `password`, `status`,
`restart`, `restart-nginx`, `backup`, `url`, `fix-forwarder`, `ports`, `help`.

`dns ports` — HTTP/HTTPS host ports + Enable HTTP (cleartext vs redirect).
Пишет `.env` / `/etc/dns/install.env` / `config/panel/ui.yml` /
`nginx/generated/http.conf`, firewalld, recreate `nginx`+`panel`.
В веб-UI Listen **нет** (только read-only в Panel TLS).

---

## Файлы

| Путь | Роль |
|------|------|
| `dns.sh` | CLI меню → `/usr/bin/dns` |
| `update.sh` | GitHub → `/opt/dns` (keep / wipe) |
| `uninstall.sh` | compose down + remove CLI (+ optional wipe) |
| `install.sh` | ставит CLI + пишет `install.env` |

Repo update: `https://github.com/MerlKoryAmber/DNSSEC` (branch `main`).
