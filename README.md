# DNS Panel + Technitium (lab)

Свой web-UI (FastAPI + JS) управляет Technitium по API. Консоль Technitium наружу не отдаётся.

## Lab-порты (CentOS 9)

На `192.168.0.178` заняты **80/443/8000** (`radiusproxy`) — их не трогаем.

| Порт | Назначение |
|------|------------|
| 9080 | UI + DoH `/dns-query` |
| 53 | классический DNS |
| 853 | DoT |

Каталог установки: `/opt/dns`.

## Установка на lab

```bash
# с рабочей машины (пример)
scp -r ./dns root@192.168.0.178:/opt/dns
ssh root@192.168.0.178 'bash /opt/dns/install.sh'
```

`install.sh` не останавливает чужие контейнеры и не пишет в `/opt/radiusproxy`.

## Вход

Открыть `http://192.168.0.178:9080/` — логин Technitium (по умолчанию `admin` / `admin`).

Разделы: Зоны (Primary/Secondary/Stub/Forwarder), записи, апстрим (53+DoT+DoH), протоколы DoH/DoT.

## Правила агента

Скелет: `docs/SKELETON.md`. Метод: `CLAUDE.md`. UX: `docs/design/UI_UX.md`. Карта: `docs/CODEMAP.md`.
