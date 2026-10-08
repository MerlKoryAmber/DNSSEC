# DNS suspicion heuristics — MVP

Время: 2026-10-08 ~12:40 МСК  
Статус: **РЕАЛИЗОВАНО НО НЕ ПРИНЯТО**

## Что

Локальный скорер (не BI.ZONE TI / SIEM):

- энтропия длинных labels  
- длина label / глубина FQDN  
- редкие qtype (TXT/NULL/ANY)  
- burst уникальных «странных» имён с одного client IP (60 с, in-memory)

## Где

- `panel/app/dns_suspicion.py`  
- `GET /api/blocking/log?suspiciousOnly=true` → поле `suspicion` на каждой строке  
- UI Query log: колонка **Risk**, чекбокс **Suspicious**

## Не делает

auto-block, TI feeds, SIEM, idle-ML DoH.

## Как смотреть

Query log → включить **Log allowed** (иначе только blocked) → **Suspicious** → Apply.  
Tooltip на badge: score + reasons.
