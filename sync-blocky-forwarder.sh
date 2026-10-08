#!/usr/bin/env bash
# Technitium → Blocky IP после recreate.
# Пароль на диск НЕ храним. Основная защита — фиксированный DNS_BLOCKY_IP в compose.
# Этот скрипт: best-effort через admin/admin только для install/update на хосте.
# Из blocky-watch без пароля — только проверка IP (см. ниже).
# shellcheck shell=bash
set -euo pipefail

DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
FIXED_IP="${DNS_BLOCKY_IP:-172.18.0.100}"
TECH_URL="${TECHNITIUM_URL:-http://127.0.0.1:5380}"
TECH_URL="${TECH_URL%/}"

log() { echo "[dns-fwd] $*"; }

ip="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dns-blocky 2>/dev/null || true)"
if [[ -z "$ip" ]]; then
  log "WARN: dns-blocky IP empty — skip"
  exit 0
fi

log "Blocky IP=${ip} (expect ${FIXED_IP})"
if [[ "$ip" != "$FIXED_IP" ]]; then
  log "WARN: IP ≠ fixed — проверь compose ipv4_address / DNS_BLOCKY_IP"
fi

# Из контейнера watch без интерактивного пароля — не логинимся, fixed IP достаточно
if [[ "${DNS_FWD_CHECK_ONLY:-0}" == "1" ]]; then
  exit 0
fi

# Хост update/install: один раз выставить forwarder = текущий IP (дефолт admin/admin)
pass="${TECHNITIUM_ADMIN_PASSWORD:-admin}"
user="${TECHNITIUM_ADMIN_USER:-admin}"
token="$(curl -sf -X POST "${TECH_URL}/api/user/login" \
  --data-urlencode "user=${user}" \
  --data-urlencode "pass=${pass}" \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true

if [[ -z "${token:-}" ]]; then
  log "INFO: API login skip (не admin/admin?) — зайди в панель: login сам пропишет forwarder"
  log "INFO: при fixed IP ${FIXED_IP} после одного успешного login recreate не ломает DNS"
  exit 0
fi

curl -sf -G "${TECH_URL}/api/settings/set" \
  --data-urlencode "token=${token}" \
  --data-urlencode "forwarders=${ip}" \
  --data-urlencode "forwarderProtocol=Udp" \
  --data-urlencode "concurrentForwarding=false" \
  --data-urlencode "dnssecValidation=false" >/dev/null
curl -sf -G "${TECH_URL}/api/cache/flush" \
  --data-urlencode "token=${token}" >/dev/null 2>&1 || true

log "Technitium forwarders → ${ip}"
exit 0
