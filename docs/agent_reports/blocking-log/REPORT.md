# Blocking Log — отчёт

Время: 2026-10-01 ~17:55 МСК  
Статус: **РЕАЛИЗОВАНО НО НЕ ПРИНЯТО** (нужен zip app на lab)

## Что сделано

- Вкладка **Blocking → Log**: фильтры domain / client / type / protocol, Allow из строки
- API: `GET /api/blocking/log`, `POST /api/blocking/log/ensure`, `POST /api/blocking/log/install` (zip)
- Backend ставит Technitium app **Query Logs (Sqlite)** (vendor zip или upload)

## Lab блокер

С lab и с рабочей станции `download.technitium.com` — timeout.  
Нужен zip вручную → upload в UI или `/opt/dns/vendor/QueryLogsSqliteApp-v9.1.2.zip`.

## UI_UX

Сверка: work scroll, empty/install state, фильтры в toolbar, без alert.
