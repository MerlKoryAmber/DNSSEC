#!/usr/bin/env bash
# Technitium → Blocky IP (hybrid B). Без UI/меню.
# Пароль: TECHNITIUM_ADMIN_PASSWORD | /opt/dns/.env | admin/admin.
# shellcheck shell=bash
set -euo pipefail

DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
ENV_FILE="${DNS_ENV_FILE:-${DNS_DIR}/.env}"
# Стабильный IP Blocky на dns_net (см. docker-compose.yml) — не плывёт после recreate
FIXED_IP="${DNS_BLOCKY_IP:-172.18.0.100}"
# с хоста: 127.0.0.1:5380; из blocky-watch: http://technitium:5380
TECH_URL="${TECHNITIUM_URL:-http://127.0.0.1:5380}"
TECH_URL="${TECH_URL%/}"

log() { echo "[dns-fwd] $*"; }

load_pass() {
  local line
  if [[ -n "${TECHNITIUM_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "$TECHNITIUM_ADMIN_PASSWORD"
    return 0
  fi
  if [[ -f "$ENV_FILE" ]]; then
    line="$(grep -E '^TECHNITIUM_ADMIN_PASSWORD=' "$ENV_FILE" 2>/dev/null | tail -1 || true)"
    if [[ -n "$line" ]]; then
      printf '%s' "${line#TECHNITIUM_ADMIN_PASSWORD=}" | sed 's/^["'\'']//;s/["'\'']$//'
      return 0
    fi
  fi
  printf '%s' "admin"
}

ip="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dns-blocky 2>/dev/null || true)"
if [[ -z "$ip" ]]; then
  log "WARN: dns-blocky IP empty — skip"
  exit 0
fi

# предпочитаем фактический IP контейнера (должен совпасть с FIXED_IP после compose)
target="$ip"
pass="$(load_pass)"
user="${TECHNITIUM_ADMIN_USER:-admin}"

token=""
token="$(curl -sf -X POST "${TECH_URL}/api/user/login" \
  --data-urlencode "user=${user}" \
  --data-urlencode "pass=${pass}" \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true

if [[ -z "${token:-}" && "$pass" != "admin" ]]; then
  log "WARN: login failed with .env password"
fi
if [[ -z "${token:-}" ]]; then
  token="$(curl -sf -X POST "${TECH_URL}/api/user/login" \
    --data-urlencode "user=admin" \
    --data-urlencode "pass=admin" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true
fi

if [[ -z "${token:-}" ]]; then
  log "WARN: cannot login Technitium — set TECHNITIUM_ADMIN_PASSWORD in ${ENV_FILE}"
  log "WARN: Blocky IP сейчас ${target} (ожидаем ${FIXED_IP}); forwarder не обновлён"
  exit 0
fi

curl -sf -G "${TECH_URL}/api/settings/set" \
  --data-urlencode "token=${token}" \
  --data-urlencode "forwarders=${target}" \
  --data-urlencode "forwarderProtocol=Udp" \
  --data-urlencode "concurrentForwarding=false" \
  --data-urlencode "dnssecValidation=false" >/dev/null
curl -sf -G "${TECH_URL}/api/cache/flush" \
  --data-urlencode "token=${token}" >/dev/null 2>&1 || true

log "Technitium forwarders → ${target} (fixed expect ${FIXED_IP})"
if [[ "$target" != "$FIXED_IP" ]]; then
  log "WARN: Blocky IP ${target} ≠ ${FIXED_IP} — проверь compose ipv4_address / DNS_BLOCKY_IP"
fi
exit 0
