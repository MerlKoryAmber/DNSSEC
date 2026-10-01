# ADR 0001 — стек dns-panel

- Дата: 2026-10-01 МСК
- Статус: принято для lab (частично уточнено ADR 0002)

## Решение

- Движок DNS (лицо / зоны / client DoT·DoH): Technitium (Docker)
- Recursive upstream chain: **Blocky** за Technitium — см. `docs/adr/0002-hybrid-blocky.md`
- Панель: FastAPI + vanilla JS по `docs/design/UI_UX.md`
- Прокси: nginx на порту **9080** (80/443 заняты radiusproxy на lab)
- Technitium web :5380 только во внутренней сети compose / loopback lab

## Последствия

- DoH на lab: `http(s)://HOST:9080|9443/dns-query` (nginx → **HTTPS** `technitium:443`; Technitium ≥15 не принимает wire DoH на HTTP :8053)
- DoT: 853/tcp (Technitium)
- Forwarders UI → Blocky YAML (`strategy: strict`)
- Не конфликтуем с `/opt/radiusproxy`
