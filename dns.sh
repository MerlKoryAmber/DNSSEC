#!/usr/bin/env bash
# DNS Panel — interactive management CLI
# Install: /usr/bin/dns (+ /usr/local/bin/dns) from /opt/dns/dns.sh
# Usage: dns | dns help | dns <command>
set -euo pipefail

DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
UPDATE_SH="${DNS_DIR}/update.sh"
UNINSTALL_SH="${DNS_DIR}/uninstall.sh"
INSTALL_META="/etc/dns/install.env"
BACKUP_ROOT="${DNS_DIR}/storage/backup"
COMPOSE_PROJECT="dns"

UI_PORT="9080"
TLS_PORT="9443"
DOT_PORT="853"

red='\033[0;31m'
green='\033[0;32m'
yellow='\033[0;33m'
plain='\033[0m'

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo -e "${red}ERROR:${plain} run as root (sudo dns …)"
    exit 1
  fi
}

ensure_valid_cwd() {
  if ! pwd >/dev/null 2>&1; then
    cd /tmp 2>/dev/null || cd / || true
  fi
}

load_install_meta() {
  if [ -f "$INSTALL_META" ]; then
    # shellcheck disable=SC1090
    . "$INSTALL_META"
  fi
  if [ -f "${DNS_DIR}/.env" ]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck disable=SC1091
    . "${DNS_DIR}/.env"
    set +a
  fi
  UI_PORT="${DNS_UI_PORT:-$UI_PORT}"
  TLS_PORT="${DNS_UI_TLS_PORT:-$TLS_PORT}"
  DOT_PORT="${DNS_DOT_PORT:-$DOT_PORT}"
}

confirm() {
  local prompt="${1:-Continue?}"
  local reply
  read -r -p "$prompt [y/N] " reply
  case "$reply" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

press_enter() {
  if [ "${DNS_MENU:-0}" = "1" ]; then
    echo ""
    read -r -p "Press Enter to return to menu…" _
  fi
}

compose() {
  (cd "$DNS_DIR" && docker compose -p "$COMPOSE_PROJECT" "$@")
}

cmd_status() {
  echo "=== DNS Panel status ==="
  echo " dir: $DNS_DIR"
  load_install_meta
  echo " UI HTTP:  :${UI_PORT}"
  echo " UI HTTPS: :${TLS_PORT}"
  echo " DoT:      :${DOT_PORT}"
  echo ""
  if [ -f "${DNS_DIR}/docker-compose.yml" ]; then
    compose ps 2>/dev/null || docker ps --filter "name=dns-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  else
    echo -e "${yellow}WARN:${plain} docker-compose.yml missing"
  fi
  echo ""
  if [ -x "$UPDATE_SH" ] || [ -f "$UPDATE_SH" ]; then
    echo " update.sh: $UPDATE_SH"
  else
    echo " update.sh: missing"
  fi
}

cmd_url() {
  local ip
  load_install_meta
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -z "$ip" ] && ip="127.0.0.1"
  echo "Panel HTTP:  http://${ip}:${UI_PORT}/"
  echo "Panel HTTPS: https://${ip}:${TLS_PORT}/"
  echo "DoH:         http://${ip}:${UI_PORT}/dns-query"
  echo "DoT:         ${ip}:${DOT_PORT}"
  echo "DNS:         ${ip}:53"
  echo " (TLS may be self-signed)"
}

cmd_update_keep() {
  if [ ! -f "$UPDATE_SH" ]; then
    echo -e "${red}ERROR:${plain} $UPDATE_SH not found"
    return 1
  fi
  if ! confirm "Run update from GitHub (keep Technitium data / .env / TLS)?"; then
    echo "Cancelled."
    return 0
  fi
  ensure_valid_cwd
  cd /tmp 2>/dev/null || cd / || true
  bash "$UPDATE_SH" --keep-data
}

cmd_update_wipe() {
  if [ ! -f "$UPDATE_SH" ]; then
    echo -e "${red}ERROR:${plain} $UPDATE_SH not found"
    return 1
  fi
  echo -e "${yellow}WARNING:${plain} wipes config/technitium (zones, query logs, certs for DoT)."
  if ! confirm "Really wipe Technitium data and update?"; then
    echo "Cancelled."
    return 0
  fi
  if ! confirm "Second confirm — WIPE Technitium data?"; then
    echo "Cancelled."
    return 0
  fi
  ensure_valid_cwd
  cd /tmp 2>/dev/null || cd / || true
  bash "$UPDATE_SH" --wipe-data
}

cmd_uninstall() {
  if [ ! -f "$UNINSTALL_SH" ]; then
    echo -e "${red}ERROR:${plain} $UNINSTALL_SH not found"
    return 1
  fi
  if ! confirm "Uninstall DNS Panel stack (compose down)?"; then
    echo "Cancelled."
    return 0
  fi
  bash "$UNINSTALL_SH"
}

cmd_password() {
  local cur new1 new2 token host
  host="http://127.0.0.1:5380"
  if ! curl -sf "${host}/api/status" >/dev/null 2>&1; then
    echo -e "${red}ERROR:${plain} Technitium API not reachable on 127.0.0.1:5380"
    return 1
  fi
  read -r -s -p "Current admin password: " cur
  echo ""
  read -r -s -p "New admin password: " new1
  echo ""
  read -r -s -p "Repeat new password: " new2
  echo ""
  if [ -z "$new1" ]; then
    echo "Empty password — cancelled."
    return 1
  fi
  if [ "$new1" != "$new2" ]; then
    echo "Passwords do not match."
    return 1
  fi
  token="$(curl -sf -X POST "${host}/api/user/login" \
    --data-urlencode "user=admin" \
    --data-urlencode "pass=${cur}" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true
  if [ -z "${token:-}" ]; then
    echo -e "${red}ERROR:${plain} login failed (wrong current password?)"
    return 1
  fi
  if curl -sf -G "${host}/api/user/changePassword" \
    --data-urlencode "token=${token}" \
    --data-urlencode "pass=${cur}" \
    --data-urlencode "newPass=${new1}" >/dev/null; then
    echo -e "${green}OK:${plain} admin password changed"
  else
    echo -e "${red}ERROR:${plain} changePassword failed"
    return 1
  fi
}

cmd_restart() {
  if ! confirm "Restart all dns-* containers (compose restart)?"; then
    echo "Cancelled."
    return 0
  fi
  compose restart
  compose ps
}

cmd_restart_nginx() {
  docker restart dns-nginx 2>/dev/null || compose restart nginx
  docker ps --filter name=dns-nginx --format '{{.Names}} {{.Status}}'
}

cmd_backup() {
  local ts dest
  load_install_meta
  ts=$(date +%Y%m%d%H%M%S)
  mkdir -p "$BACKUP_ROOT"
  dest="${BACKUP_ROOT}/dns-${ts}"
  mkdir -p "$dest"
  [ -f "${DNS_DIR}/.env" ] && cp -a "${DNS_DIR}/.env" "${dest}/.env" || echo "WARN: .env missing"
  [ -f "${DNS_DIR}/config/blocky/config.yml" ] && cp -a "${DNS_DIR}/config/blocky/config.yml" "${dest}/blocky-config.yml"
  if [ -d "${DNS_DIR}/config/panel" ]; then
    mkdir -p "${dest}/panel"
    cp -a "${DNS_DIR}/config/panel/." "${dest}/panel/" 2>/dev/null || true
  fi
  if [ -d "${DNS_DIR}/config/nginx/ssl" ]; then
    mkdir -p "${dest}/nginx-ssl"
    cp -a "${DNS_DIR}/config/nginx/ssl/." "${dest}/nginx-ssl/" 2>/dev/null || true
  fi
  if [ -d "${DNS_DIR}/nginx/generated" ]; then
    mkdir -p "${dest}/nginx-generated"
    cp -a "${DNS_DIR}/nginx/generated/." "${dest}/nginx-generated/" 2>/dev/null || true
  fi
  if [ -d "${DNS_DIR}/config/technitium" ]; then
    echo "Copying Technitium data (may take a while)…"
    tar -C "${DNS_DIR}/config" -czf "${dest}/technitium.tgz" technitium 2>/dev/null \
      || echo "WARN: technitium archive failed"
  fi
  [ -f "$INSTALL_META" ] && cp -a "$INSTALL_META" "${dest}/install.env"
  echo "Backup: $dest"
  ls -lah "$dest"
}

cmd_fix_forwarder() {
  local ip token
  if ! docker inspect dns-blocky >/dev/null 2>&1; then
    echo -e "${red}ERROR:${plain} dns-blocky not running"
    return 1
  fi
  ip=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dns-blocky)
  if [ -z "$ip" ]; then
    echo -e "${red}ERROR:${plain} cannot resolve Blocky IP"
    return 1
  fi
  echo "Blocky IP: $ip"
  token="$(curl -sf -X POST "http://127.0.0.1:5380/api/user/login" \
    --data-urlencode "user=admin" \
    --data-urlencode "pass=admin" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true
  if [ -z "${token:-}" ]; then
    echo -e "${yellow}WARN:${plain} login admin/admin failed — enter password"
    local pass
    read -r -s -p "Technitium admin password: " pass
    echo ""
    token="$(curl -sf -X POST "http://127.0.0.1:5380/api/user/login" \
      --data-urlencode "user=admin" \
      --data-urlencode "pass=${pass}" \
      | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true
  fi
  if [ -z "${token:-}" ]; then
    echo -e "${red}ERROR:${plain} cannot login to Technitium"
    return 1
  fi
  curl -sf -G "http://127.0.0.1:5380/api/settings/set" \
    --data-urlencode "token=${token}" \
    --data-urlencode "forwarders=${ip}" \
    --data-urlencode "forwarderProtocol=Udp" \
    --data-urlencode "dnssecValidation=false" >/dev/null
  curl -sf -G "http://127.0.0.1:5380/api/cache/flush" \
    --data-urlencode "token=${token}" >/dev/null || true
  echo -e "${green}OK:${plain} Technitium forwarders → ${ip}"
  if command -v dig >/dev/null 2>&1; then
    dig @127.0.0.1 example.com A +time=2 +tries=1 +noall +answer || true
  fi
}

show_usage() {
  echo "DNS Panel management CLI"
  echo ""
  echo "  dns                 Interactive menu"
  echo "  dns status          Compose / ports status"
  echo "  dns url             Panel / DoH / DoT URLs"
  echo "  dns update          Update from GitHub (keep data)"
  echo "  dns update-wipe     Update + wipe Technitium data"
  echo "  dns uninstall       Remove stack"
  echo "  dns password        Reset Technitium admin password"
  echo "  dns restart         Restart all dns-* containers"
  echo "  dns restart-nginx   Restart dns-nginx only"
  echo "  dns backup          Backup .env / TLS / panel / Technitium"
  echo "  dns fix-forwarder   Set Technitium forwarder = Blocky IP"
  echo "  dns help            This text"
  echo ""
  echo "Does not touch /opt/radiusproxy, /opt/spm, or foreign containers."
}

show_menu() {
  echo ""
  echo -e " ${green}DNS Panel${plain} — Technitium + Blocky"
  echo " ------------------------------------------"
  echo -e " ${green}1.${plain} Update (keep data)"
  echo -e " ${green}2.${plain} Update + wipe Technitium data"
  echo -e " ${green}3.${plain} Uninstall"
  echo -e " ${green}4.${plain} Reset Technitium admin password"
  echo -e " ${green}5.${plain} Status"
  echo -e " ${green}6.${plain} Restart stack"
  echo -e " ${green}7.${plain} Restart nginx"
  echo -e " ${green}8.${plain} Backup"
  echo -e " ${green}9.${plain} Show panel URL"
  echo -e " ${green}10.${plain} Fix Blocky forwarder IP"
  echo -e " ${green}0.${plain} Exit"
  echo " ------------------------------------------"
}

run_menu() {
  export DNS_MENU=1
  while true; do
    show_menu
    read -r -p "Select [0-10]: " choice
    case "$choice" in
      1) cmd_update_keep; press_enter ;;
      2) cmd_update_wipe; press_enter ;;
      3) cmd_uninstall; press_enter ;;
      4) cmd_password; press_enter ;;
      5) cmd_status; press_enter ;;
      6) cmd_restart; press_enter ;;
      7) cmd_restart_nginx; press_enter ;;
      8) cmd_backup; press_enter ;;
      9) cmd_url; press_enter ;;
      10) cmd_fix_forwarder; press_enter ;;
      0|q|Q) exit 0 ;;
      *) echo "Invalid option" ;;
    esac
  done
}

need_root
ensure_valid_cwd
load_install_meta

case "${1:-}" in
  "") run_menu ;;
  help|-h|--help) show_usage ;;
  status) cmd_status ;;
  url) cmd_url ;;
  update) cmd_update_keep ;;
  update-wipe|update-drop) cmd_update_wipe ;;
  uninstall) cmd_uninstall ;;
  password) cmd_password ;;
  restart) cmd_restart ;;
  restart-nginx) cmd_restart_nginx ;;
  backup) cmd_backup ;;
  fix-forwarder|fix-fwd) cmd_fix_forwarder ;;
  *)
    echo -e "${red}Unknown:${plain} $1"
    show_usage
    exit 1
    ;;
esac
