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
    set +u
    # shellcheck disable=SC1090
    set -a
    # shellcheck disable=SC1091
    . "${DNS_DIR}/.env" || true
    set +a
    set -u
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

set_env_kv() {
  local file="$1" key="$2" val="$3"
  local tmp
  mkdir -p "$(dirname "$file")"
  touch "$file"
  tmp="$(mktemp)"
  if grep -qE "^[[:space:]]*${key}=" "$file" 2>/dev/null; then
    sed -E "s|^[[:space:]]*${key}=.*|${key}=${val}|" "$file" >"$tmp"
  else
    cat "$file" >"$tmp"
    printf '%s=%s\n' "$key" "$val" >>"$tmp"
  fi
  mv "$tmp" "$file"
}

read_http_enabled_host() {
  local yml="${DNS_DIR}/config/panel/ui.yml" line
  if [ -f "$yml" ]; then
    line=$(grep -E '^[[:space:]]*httpEnabled:' "$yml" | head -1 || true)
    case "$line" in
      *false*|*False*|*no*|*No*|*0*) echo "0"; return ;;
    esac
  fi
  echo "1"
}

write_http_conf_host() {
  local enabled="$1" https_port="$2"
  local conf="${DNS_DIR}/nginx/generated/http.conf"
  mkdir -p "$(dirname "$conf")"
  if [ "$enabled" = "1" ]; then
    cat >"$conf" <<'EOF'
server {
    listen 80;
    server_name _;
    include /etc/nginx/panel_locations.conf;
}
EOF
  else
    cat >"$conf" <<EOF
server {
    listen 80;
    server_name _;
    return 301 https://\$host:${https_port}\$request_uri;
}
EOF
  fi
}

write_ui_listen_host() {
  local https_port="$1" py_bool="$2" en_flag yml="${DNS_DIR}/config/panel/ui.yml"
  if [ "$py_bool" = "True" ]; then en_flag=1; else en_flag=0; fi
  mkdir -p "$(dirname "$yml")"
  if docker exec dns-panel python -c "from app.panel_tls import write_listen_settings; write_listen_settings(${https_port}, ${py_bool})" 2>/dev/null; then
    return 0
  fi
  if [ -f "$yml" ] && grep -qE '^[[:space:]]*httpsPort:' "$yml"; then
    sed -i -E "s|^[[:space:]]*httpsPort:.*|httpsPort: ${https_port}|" "$yml"
  elif [ -f "$yml" ]; then
    printf 'httpsPort: %s\n' "$https_port" >>"$yml"
  else
    printf 'httpsPort: %s\nhttpEnabled: %s\n' "$https_port" \
      "$([ "$en_flag" = "1" ] && echo true || echo false)" >"$yml"
  fi
  if [ -f "$yml" ] && grep -qE '^[[:space:]]*httpEnabled:' "$yml"; then
    sed -i -E "s|^[[:space:]]*httpEnabled:.*|httpEnabled: $([ "$en_flag" = "1" ] && echo true || echo false)|" "$yml"
  elif [ -f "$yml" ]; then
    printf 'httpEnabled: %s\n' "$([ "$en_flag" = "1" ] && echo true || echo false)" >>"$yml"
  fi
  write_http_conf_host "$en_flag" "$https_port"
}

firewall_swap_tcp() {
  local old="$1" new="$2"
  [ "$old" = "$new" ] && return 0
  if ! command -v firewall-cmd >/dev/null 2>&1; then
    return 0
  fi
  if ! systemctl is-active --quiet firewalld 2>/dev/null; then
    return 0
  fi
  firewall-cmd --permanent --add-port="${new}/tcp" 2>/dev/null || true
  case "$old" in
    80|443|53|853|8000|1812|1813) ;;
    *) firewall-cmd --permanent --remove-port="${old}/tcp" 2>/dev/null || true ;;
  esac
  firewall-cmd --reload 2>/dev/null || true
}

valid_port() {
  local p="$1"
  case "$p" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$p" -ge 1 ] && [ "$p" -le 65535 ]
}

port_in_use() {
  local port="$1"
  ss -lntu 2>/dev/null | awk '{print $5}' | grep -E "[:.]${port}$" >/dev/null 2>&1
}

# Only ports this stack must keep (or Technitium local API). 80/443 NOT banned —
# reserved only if already listening (e.g. radiusproxy).
port_reserved() {
  local p="$1"
  case "$p" in
    53|5380) return 0 ;;
  esac
  [ "$p" = "$DOT_PORT" ] && return 0
  return 1
}

port_conflict_msg() {
  local p="$1" role="$2"
  if port_reserved "$p"; then
    echo "ERROR: ${role} port ${p} reserved for DNS stack (53 / DoT ${DOT_PORT} / Technitium 5380)"
    return 0
  fi
  if port_in_use "$p"; then
    echo "ERROR: ${role} port ${p} already in use on host (ss)"
    return 0
  fi
  return 1
}

cmd_set_ports() {
  local old_http old_https old_en new_http new_https new_en reply en_py
  load_install_meta
  old_http="$UI_PORT"
  old_https="$TLS_PORT"
  old_en="$(read_http_enabled_host)"

  new_http=""
  new_https=""
  new_en=""
  if [ -n "${1:-}" ]; then new_http="$1"; fi
  if [ -n "${2:-}" ]; then new_https="$2"; fi
  if [ -n "${3:-}" ]; then
    case "$3" in
      on|ON|1|yes|true|TRUE) new_en=1 ;;
      off|OFF|0|no|false|FALSE) new_en=0 ;;
      *) echo -e "${red}ERROR:${plain} http enable must be on|off"; return 1 ;;
    esac
  fi

  echo "=== Panel listen ports ==="
  echo " Current HTTP:  :${old_http} ($([ "$old_en" = "1" ] && echo enabled || echo redirect→HTTPS))"
  echo " Current HTTPS: :${old_https}"
  echo ""

  if [ -z "$new_http" ] || [ -z "$new_https" ] || [ -z "$new_en" ]; then
    if [ ! -t 0 ]; then
      echo -e "${red}ERROR:${plain} non-interactive: dns ports <http> <https> <on|off>"
      return 1
    fi
    [ -z "$new_http" ] && {
      read -r -p "HTTP port [${old_http}]: " reply
      new_http="${reply:-$old_http}"
    }
    [ -z "$new_https" ] && {
      read -r -p "HTTPS port [${old_https}]: " reply
      new_https="${reply:-$old_https}"
    }
    if [ -z "$new_en" ]; then
      if [ "$old_en" = "1" ]; then
        read -r -p "Enable HTTP cleartext UI? [Y/n]: " reply
        case "${reply:-Y}" in n|N|no|NO) new_en=0 ;; *) new_en=1 ;; esac
      else
        read -r -p "Enable HTTP cleartext UI? [y/N]: " reply
        case "${reply:-N}" in y|Y|yes|YES) new_en=1 ;; *) new_en=0 ;; esac
      fi
    fi
  fi

  if ! valid_port "$new_http"; then
    echo -e "${red}ERROR:${plain} bad HTTP port: ${new_http}"; return 1
  fi
  if ! valid_port "$new_https"; then
    echo -e "${red}ERROR:${plain} bad HTTPS port: ${new_https}"; return 1
  fi
  if [ "$new_http" = "$new_https" ]; then
    echo -e "${red}ERROR:${plain} HTTP and HTTPS ports must differ"; return 1
  fi
  # skip "in use" for ports we already own (no-op / swap)
  if [ "$new_http" != "$old_http" ]; then
    msg=$(port_conflict_msg "$new_http" "HTTP") && { echo -e "${red}${msg}${plain}"; return 1; }
  fi
  if [ "$new_https" != "$old_https" ]; then
    msg=$(port_conflict_msg "$new_https" "HTTPS") && { echo -e "${red}${msg}${plain}"; return 1; }
  fi

  if [ "$new_http" = "$old_http" ] && [ "$new_https" = "$old_https" ] && [ "$new_en" = "$old_en" ]; then
    echo "No change."
    return 0
  fi

  echo " Will set: HTTP :${new_http} ($([ "$new_en" = "1" ] && echo enabled || echo redirect)) · HTTPS :${new_https}"
  if ! confirm "Apply and recreate dns-nginx (+ panel)?"; then
    echo "Cancelled."
    return 0
  fi

  set_env_kv "${DNS_DIR}/.env" DNS_UI_PORT "$new_http"
  set_env_kv "${DNS_DIR}/.env" DNS_UI_TLS_PORT "$new_https"
  mkdir -p /etc/dns
  set_env_kv "$INSTALL_META" DNS_UI_PORT "$new_http"
  set_env_kv "$INSTALL_META" DNS_UI_TLS_PORT "$new_https"
  if ! grep -q '^DNS_DOT_PORT=' "$INSTALL_META" 2>/dev/null; then
    set_env_kv "$INSTALL_META" DNS_DOT_PORT "$DOT_PORT"
  fi
  chmod 600 "$INSTALL_META" 2>/dev/null || true

  if [ "$new_en" = "1" ]; then en_py=True; else en_py=False; fi
  write_ui_listen_host "$new_https" "$en_py"
  write_http_conf_host "$new_en" "$new_https"

  firewall_swap_tcp "$old_http" "$new_http"
  firewall_swap_tcp "$old_https" "$new_https"

  echo "Recreating nginx + panel…"
  compose up -d --no-deps --force-recreate nginx panel
  sleep 2
  docker restart dns-nginx 2>/dev/null || true

  UI_PORT="$new_http"
  TLS_PORT="$new_https"
  echo -e "${green}OK:${plain} ports applied"
  cmd_url
}

show_usage() {
  echo "DNS Panel management CLI"
  echo ""
  echo "  dns                 Interactive menu"
  echo "  dns status          Compose / ports status"
  echo "  dns url             Panel / DoH / DoT URLs"
  echo "  dns ports           Set panel HTTP/HTTPS ports (+ HTTP on/off)"
  echo "  dns ports <http> <https> <on|off>"
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
  echo -e " ${green}11.${plain} Set panel ports (HTTP/HTTPS)"
  echo -e " ${green}0.${plain} Exit"
  echo " ------------------------------------------"
}

run_menu() {
  export DNS_MENU=1
  while true; do
    show_menu
    read -r -p "Select [0-11]: " choice
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
      11) cmd_set_ports; press_enter ;;
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
  ports|set-ports|listen) shift; cmd_set_ports "$@" ;;
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
