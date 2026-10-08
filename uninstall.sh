#!/usr/bin/env bash
# DNS Panel — uninstall (compose down; optional wipe of /opt/dns)
# Does NOT touch /opt/radiusproxy, /opt/spm, 2fa_*, or foreign containers.
set -euo pipefail

DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
COMPOSE_PROJECT="dns"
INSTALL_META="/etc/dns/install.env"

UI_PORT="9080"
TLS_PORT="9443"
DOT_PORT="853"

YES=0
WIPE_DIR="" # empty = ask; 1 = wipe; 0 = keep

for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --wipe-dir|--delete-dir) WIPE_DIR=1 ;;
    --keep-dir) WIPE_DIR=0 ;;
    --help|-h)
      echo "Usage: $0 [--yes] [--wipe-dir|--keep-dir]"
      exit 0
      ;;
    "") ;;
    *)
      echo "ERROR: unknown argument: $arg"
      exit 1
      ;;
  esac
done

is_yes() {
  case "${1:-}" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

if [ -f "$INSTALL_META" ]; then
  # shellcheck disable=SC1090
  set +u
  # shellcheck disable=SC1091
  . "$INSTALL_META"
  set -u
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
echo "Will NOT touch: /opt/radiusproxy, /opt/spm, 2fa_*, other compose projects."
echo ""

if [ "$YES" != 1 ]; then
  read -r -p "Uninstall DNS Panel? [y/N]: " CONFIRM
  if ! is_yes "$CONFIRM"; then
    echo "Cancelled."
    exit 0
  fi
else
  echo "Confirmed via --yes"
fi

echo ""
echo "[1/5] Stopping compose project ${COMPOSE_PROJECT}…"
set +e
if [ -f "${DNS_DIR}/docker-compose.yml" ]; then
  (cd "$DNS_DIR" && docker compose -p "$COMPOSE_PROJECT" down --remove-orphans)
  echo "[1/5] compose down rc=$?"
else
  for c in dns-nginx dns-panel dns-technitium dns-blocky dns-blocky-watch; do
    docker rm -f "$c" 2>/dev/null
  done
  echo "[1/5] containers force-removed (no compose file)"
fi
# leftover containers with dns- prefix from this project
docker ps -aq --filter "name=dns-" 2>/dev/null | while read -r id; do
  [ -n "$id" ] || continue
  docker rm -f "$id" 2>/dev/null || true
done
set -e

echo "[2/5] Removing CLI…"
rm -f /usr/bin/dns /usr/local/bin/dns

echo "[3/5] Firewall…"
set +e
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --permanent --remove-port=53/tcp 2>/dev/null
  firewall-cmd --permanent --remove-port=53/udp 2>/dev/null
  firewall-cmd --permanent --remove-port="${DOT_PORT}/tcp" 2>/dev/null
  firewall-cmd --permanent --remove-port="${UI_PORT}/tcp" 2>/dev/null
  firewall-cmd --permanent --remove-port="${TLS_PORT}/tcp" 2>/dev/null
  firewall-cmd --reload 2>/dev/null
fi
set -e

echo "[4/5] Removing install meta…"
rm -f "$INSTALL_META"
rmdir /etc/dns 2>/dev/null || true

echo "[5/5] Data directory…"
echo "Files remain under ${DNS_DIR} (Technitium data, TLS, .env)."
if [ -z "$WIPE_DIR" ]; then
  read -r -p "Also DELETE ${DNS_DIR}? [y/N]: " WIPE
  if is_yes "$WIPE"; then
    WIPE_DIR=1
  else
    WIPE_DIR=0
  fi
fi
if [ "$WIPE_DIR" = "1" ]; then
  if [ "$DNS_DIR" = "/" ] || [ -z "$DNS_DIR" ] || [ "$DNS_DIR" = "/opt" ]; then
    echo "ERROR: refusing unsafe path: ${DNS_DIR}"
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
