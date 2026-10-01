# Handoff CURRENT — 2026-10-01 ~20:20 МСК

Читать после `docs/SKELETON.md`.

## Статус

**РЕАЛИЗОВАНО НО НЕ ПРИНЯТО:** Settings → Panel TLS → **Listen**:
HTTPS port + галка **Enable HTTP** (off = nginx :80 → 301 HTTPS).
`ui.yml` + `.env` DNS_UI_TLS_PORT + `nginx/generated/http.conf` + recreate nginx.

## Lab

`192.168.0.178` `/opt/dns` UI `http://:9080` · `https://:9443`
(порт / HTTP on-off — из UI Save Listen)

## Deploy note

После scp: `docker compose -p dns up -d --build panel` + recreate `nginx`
(volume `nginx/generated`). Cache UI `?v=40`.
