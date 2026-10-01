#!/usr/bin/env bash
# DNS Panel — uninstall (compose down; optional wipe of /opt/dns)
# Does NOT touch /opt/radiusproxy, /opt/spm, or foreign containers.
set -euo pipefail

DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
COMPOSE_PROJECT="dns"
INSTALL_META="/etc/dns/install.env"

UI_PORT="9080"
TLS_PORT="9443"
DOT_PORT="853"

if [ -f "$INSTALL_META" ]; then
  # shellcheck disable=SC1090
  . "$INSTALL_META"
fi
UI_PORT="${DNS_UI_PORT:-$UI_PORT}"
TLS_PORT="${DNS_UI_TLS_PORT:-$TLS_PORT}"
DOT_PORT="${DNS_DOT_PORT:-$DOT_PORT}"

echo "=== DNS Panel Uninstaller ==="
echo ""

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "ERROR: run as root"
  exit 1
fi

echo "This will:"
echo "  - docker compose -p ${COMPOSE_PROJECT} down (only dns-* containers)"
echo "  - remove /usr/bin/dns /usr/local/bin/dns"
echo "  - remove firewall ports ${UI_PORT},${TLS_PORT},${DOT_PORT},53 (if firewalld)"
echo "  - remove ${INSTALL_META}"
echo ""
echo "Will NOT touch: /opt/radiusproxy, /opt/spm, other compose projects."
echo ""
read -r -p "Uninstall DNS Panel? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo "[1/5] Stopping compose project ${COMPOSE_PROJECT}…"
if [ -f "${DNS_DIR}/docker-compose.yml" ]; then
  (cd "$DNS_DIR" && docker compose -p "$COMPOSE_PROJECT" down) || true
else
  for c in dns-nginx dns-panel dns-technitium dns-blocky dns-blocky-watch; do
    docker rm -f "$c" 2>/dev/null || true
  done
fi

echo "[2/5] Removing CLI…"
rm -f /usr/bin/dns /usr/local/bin/dns

echo "[3/5] Firewall…"
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --permanent --remove-port=53/tcp 2>/dev/null || true
  firewall-cmd --permanent --remove-port=53/udp 2>/dev/null || true
  firewall-cmd --permanent --remove-port="${DOT_PORT}/tcp" 2>/dev/null || true
  firewall-cmd --permanent --remove-port="${UI_PORT}/tcp" 2>/dev/null || true
  firewall-cmd --permanent --remove-port="${TLS_PORT}/tcp" 2>/dev/null || true
  firewall-cmd --reload 2>/dev/null || true
fi

echo "[4/5] Removing install meta…"
rm -f "$INSTALL_META"
rmdir /etc/dns 2>/dev/null || true

echo "[5/5] Data directory…"
echo "Files remain under ${DNS_DIR} (Technitium data, TLS, .env)."
read -r -p "Also DELETE ${DNS_DIR}? (yes/no): " WIPE
if [ "$WIPE" = "yes" ]; then
  if [ "$DNS_DIR" = "/" ] || [ -z "$DNS_DIR" ]; then
    echo "ERROR: refusing empty or root path"
    exit 1
  fi
  rm -rf "$DNS_DIR"
  echo "Removed $DNS_DIR"
else
  echo "Kept $DNS_DIR"
fi

echo ""
echo "=== Uninstall complete ==="
echo "Docker engine left running. Foreign stacks untouched."
echo ""
