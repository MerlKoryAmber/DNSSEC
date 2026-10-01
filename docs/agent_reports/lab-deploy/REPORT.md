# REPORT — lab deploy DNS panel

- Время: 2026-10-01 ~12:15 МСК
- Статус: РЕАЛИЗОВАНО НО НЕ ПРИНЯТО

## Сделано

- Репозиторий: CLAUDE.md, UI_UX, CODEMAP, ADR-0001, FastAPI+JS панель, compose, install.sh
- Деплой `/opt/dns` на `192.168.0.178`
- Порты: UI/DoH `9080`, DNS `53`, DoT `853`; Technitium UI только `127.0.0.1:5380`
- Не тронуты: `radiusproxy-*`, `/opt/radiusproxy`, порты 80/443/8000

## Проверки

- Login panel `admin/admin` — OK
- Зона `lab.local` + `host.lab.local A 192.168.0.178` — dig OK
- Forwarders + DoT + DoH-HTTP:8053 — включены
- `GET /api/health` — ok
- radiusproxy — running

## Доступ

- UI: http://192.168.0.178:9080/
- Логин: admin / admin (сменить)

## Хвосты

- Пароль admin по умолчанию
- DoH на lab по HTTP (нет 443 — занят radiusproxy)
- Верификация UI глазами человека — pending
