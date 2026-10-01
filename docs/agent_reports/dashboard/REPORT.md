# Dashboard — отчёт

Время: 2026-10-01 ~17:35 МСК  
Статус: **РЕАЛИЗОВАНО НО НЕ ПРИНЯТО**

## Что сделано

- `GET /api/dashboard?type=LastHour|LastDay|LastWeek|LastMonth|LastYear`
- Technitium `/api/dashboard/stats/get` + metrics + hybrid strip (Blocky forwarders, Blocking, DoT/DoH)
- UI `#/dashboard` — KPI, sparkline, bars, tops; дефолт после логина
- Lab: scp + `docker compose -p dns up -d --build panel` + `docker restart dns-nginx`

## Проверка (lab)

- `/api/health` → ok
- login admin → dashboard: `queries 0`, `fwd 3`, `blocking True`, `chart_pts 60`

## UI_UX сверка (попунктно)

1. Viewport высота/ширина/отступы — `.form-panel` + grid `minmax`, clamp
2. Скролл только work — `.dash-panel` / `.form-panel` overflow
3. Sticky chrome+thead — shell; tops внутри `.dash-top-scroll`
4. Empty — Loading / No data / Failed
5. Модалки — не используются на экране
6. Узкий экран — auto-fit KPI/grid
7. Контент на всю `.work` — без узкой колонки

## Хвост

Приёмка человеком (Ctrl+F5 → Dashboard).
