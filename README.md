# DNS Panel (Technitium + Blocky)

Свой web-UI (FastAPI + JS) управляет DNS-стеком. Консоль Technitium (`:5380`) наружу не отдаётся.

Репозиторий: https://github.com/MerlKoryAmber/DNSSEC

## Стек

```
Клиент DNS  → Technitium :53 / :853 (DoT) / DoH
                ├─ auth zones → локально
                └─ рекурсия → Blocky (внутри compose)
Клиент UI   → nginx :9080 / :9443 → static + /api → panel
```

## Lab

| | |
|--|--|
| Хост | `192.168.0.178` (CentOS Stream 9) |
| Каталог | `/opt/dns` |
| UI HTTP | http://192.168.0.178:9080/ |
| UI HTTPS | https://192.168.0.178:9443/ |
| DoH | `http://HOST:9080/dns-query` |
| DoT | `HOST:853` |
| DNS | `HOST:53` |

Чужие стеки (`/opt/radiusproxy`, `/opt/spm`, порты 80/443/8000) **не трогаем**.

Логин панели = аккаунт Technitium (lab: `admin` / `admin` — смените).

## Установка с GitHub

```bash
# на сервере (root)
dnf install -y git   # если ещё нет
cd /tmp
git clone --depth 1 https://github.com/MerlKoryAmber/DNSSEC.git /opt/dns.src
bash /opt/dns.src/install.sh
# install копирует/поднимает стек в /opt/dns и ставит CLI
```

Либо уже лежащий каталог:

```bash
bash /opt/dns/install.sh
```

## CLI меню

После install:

```bash
sudo dns              # интерактивное меню
sudo dns status
sudo dns url
sudo dns ports        # HTTP/HTTPS + HTTP on/off
sudo dns update       # с GitHub, сохранить данные
sudo dns update-wipe  # update + wipe Technitium data (2× confirm)
sudo dns backup
sudo dns fix-forwarder
sudo dns restart
sudo dns uninstall
sudo dns help
```

Бинарник: `/usr/bin/dns` ← `/opt/dns/dns.sh`.  
Паттерн: `docs/patterns/cli-menu-linux.md` (как в squid-panel).

| Скрипт | Назначение |
|--------|------------|
| `install.sh` | первичная установка + CLI + firewall |
| `update.sh` | clone GitHub → rsync кода (keep `.env` / technitium / TLS) |
| `uninstall.sh` | compose down + remove CLI (+ optional wipe `/opt/dns`) |
| `dns.sh` | меню и подкоманды |

## Разделы UI

Dashboard · Zones · Forwarders · Client protocol · Blocking · Query log · Settings  
(General: timezone + query log storage; Panel TLS cert; Blocking).  
Порты панели — `sudo dns ports`, не UI.

## Документация

- Скелет агента: `docs/SKELETON.md`
- Карта кода: `docs/CODEMAP.md`
- UX: `docs/design/UI_UX.md`
- Метод: `CLAUDE.md`
