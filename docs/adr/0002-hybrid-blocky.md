# ADR 0002 — hybrid Technitium + Blocky (вариант B)

- Дата: 2026-10-01 МСК
- Статус: принято для lab
- Сменяет частично ADR 0001 (forwarders)

## Контекст

ТЗ: upstream forwarders с **разным типом на строку** (Classic / DoT / DoH) и
**последовательным failover** (1 → 2 → 3). Technitium умеет порядок
(`concurrentForwarding=false`), но **один** `forwarderProtocol` на весь список.

## Решение (вариант B)

```
Клиент → Technitium (53 / 853 / DoH, зоны)
            ├─ auth zones → локально
            └─ рекурсия → Blocky:53 (internal)
                            └─ upstreams strict: DoH / DoT / Classic по строкам
```

- **Technitium** — лицо DNS, зоны, client protocol, UI login.
- **Blocky** — только recursive upstream chain; наружу 53/853 **не** публикуем.
- Панель **Forwarders** читает/пишет `config/blocky/config.yml` (группа `default`,
  `strategy: strict`).
- Панель при Save forwarders гарантирует у Technitium:
  `forwarders=<IP Blocky>`, `forwarderProtocol=Udp`, `concurrentForwarding=false`,
  `dnssecValidation=false`.

## Не в этом ADR

- Раздел Blocked / block lists в UI — TODO отдельно.
- Blocky спереди (вариант A) — отвергнут для текущей панели.

## Последствия

- +1 hop на рекурсию (приемлемо).
- Reload Blocky после Save — `blocky-watch` (inotify + `docker restart`).
- При Save Technitium получает **IP** Blocky (не hostname — иначе бывает
  Resolver exception) и `dnssecValidation=false` (иначе EDE RRSIG Missing на
  forwarder-ответах).
- Тест forwarder — Technitium `dnsClient/resolve` с protocol на элемент.
