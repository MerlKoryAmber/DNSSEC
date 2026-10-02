# DNS Panel (Technitium + Blocky)

Свой web-UI (FastAPI + JS) управляет DNS-стеком. Консоль Technitium (`:5380`) наружу не отдаётся.

Репозиторий: https://github.com/MerlKoryAmber/DNSSEC · ветка `main`

## Стек

```
Клиент DNS  → Technitium :53 / :853 (DoT) / DoH
                ├─ auth zones → локально
                └─ рекурсия → Blocky (только dns_net, strategy: strict)
Клиент UI   → nginx :9080 / :9443 → static + /api → panel
```

Hybrid B: Technitium спереди, Blocky сзади (ADR 0002). Вариант «Blocky спереди» отвергнут.

## Порты по умолчанию

| Сервис | Порт |
|--------|------|
| DNS | `53` tcp/udp |
| DoT (клиентский) | `853` |
| UI HTTP + DoH path | `9080` (`/dns-query`) |
| UI HTTPS | `9443` |
| Technitium API | `127.0.0.1:5380` (не снаружи) |

Смена UI HTTP/HTTPS и «Enable HTTP» — только CLI: `sudo dns ports` (не веб-UI).

Чужие стеки (`/opt/radiusproxy`, `/opt/spm`) **не трогаем**.  
Порты `80`/`443` можно назначить панели через `dns ports`, если на хосте свободны.

Логин панели = аккаунт Technitium (смените дефолт `admin` / `admin`).

## Установка с GitHub

```bash
# на сервере (root); нужен HTTP(S)_PROXY в env или /etc/environment за корп-прокси
dnf install -y git
cd /tmp
git clone --depth 1 https://github.com/MerlKoryAmber/DNSSEC.git /opt/dns.src
bash /opt/dns.src/install.sh
# → /opt/dns, CLI /usr/bin/dns, compose project dns
```

Повторно из уже лежащего дерева:

```bash
bash /opt/dns/install.sh
```

Обновление:

```bash
sudo dns update          # keep data
# или
sudo bash /opt/dns/update.sh --keep-data
```

## Прокси (важно)

| Слой | Поведение |
|------|-----------|
| **dockerd** (pull образов) | `docker-host-proxy.sh` → systemd drop-in; install/update |
| **docker build** (`pip` / `apk`) | compose `build.args` + `ARG` в Dockerfile panel / blocky-watch |
| **runtime dns-*** | compose `x-proxy-guard` — пустой proxy (service mesh) |

Без host `HTTP_PROXY`/`HTTPS_PROXY` pull и build идут напрямую.

## CLI

```bash
sudo dns                 # меню
sudo dns status
sudo dns url
sudo dns ports           # HTTP/HTTPS + HTTP on/off (интерактив)
sudo dns ports 9080 9443 on
sudo dns update
sudo dns update-wipe     # 2× confirm
sudo dns backup
sudo dns fix-forwarder
sudo dns restart
sudo dns restart-nginx
sudo dns password
sudo dns uninstall
sudo dns help
```

Бинарник: `/usr/bin/dns` ← `/opt/dns/dns.sh`.  
Паттерн: `docs/patterns/cli-menu-linux.md`.

| Файл | Назначение |
|------|------------|
| `install.sh` | установка + CLI + firewall + docker proxy |
| `update.sh` | GitHub → rsync (keep `.env` / technitium / TLS) |
| `uninstall.sh` | compose down + remove CLI (+ optional wipe) |
| `dns.sh` | меню и подкоманды |
| `docker-host-proxy.sh` | drop-in HTTP(S)_PROXY для dockerd |

## UI

Dashboard · Zones · Forwarders · Client protocol · Blocking · Query log · Settings  
(General: timezone + query log; **Panel TLS** — только PEM; Blocking).

## Документация

| Файл | Зачем |
|------|--------|
| `docs/SKELETON.md` | скелет для агента |
| `docs/CODEMAP.md` | карта + API |
| `docs/agent_reports/handoff/CURRENT.md` | статус «сейчас» |
| `docs/design/UI_UX.md` | UX |
| `docs/adr/` | решения стека |
| `CLAUDE.md` | метод работы с агентом |
