# Handoff CURRENT — 2026-10-01 ~22:45 МСК

Читать после `docs/SKELETON.md`.

## Статус

**РЕАЛИЗОВАНО НО НЕ ПРИНЯТО:** Linux CLI menu по паттерну squid-panel —
`dns.sh` → `/usr/bin/dns`, плюс `update.sh` / `uninstall.sh`, проводка в
`install.sh`, docs `docs/patterns/cli-menu-linux.md`.

## Lab

`192.168.0.178` `/opt/dns` · CLI: `sudo dns` / `sudo dns status`

## Deploy note

scp `dns.sh` `update.sh` `uninstall.sh` `install.sh` →
`chmod +x` + `install -m 755 /opt/dns/dns.sh /usr/bin/dns`.
