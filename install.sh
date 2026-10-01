#!/usr/bin/env bash
# install.sh — DNS panel + Technitium на CentOS 9 в /opt/dns
# НЕ трогает другие проекты (radiusproxy и т.п.), не docker stop чужих контейнеров.
set -euo pipefail

TARGET_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
UI_PORT="${DNS_UI_PORT:-9080}"
TLS_PORT="${DNS_UI_TLS_PORT:-9443}"
DOT_PORT="${DNS_DOT_PORT:-853}"
COMPOSE_PROJECT="dns"

log() { echo "[dns-install] $*"; }
die() { echo "[dns-install] ERROR: $*" >&2; exit 1; }

need_root() {
  [[ "$(id -u)" -eq 0 ]] || die "нужен root"
}

check_other_stacks() {
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qE '^radiusproxy-'; then
    log "обнаружен radiusproxy — не трогаем (порты 80/443/8000 остаются ему)"
  fi
  if [[ -d /opt/radiusproxy ]]; then
    log "каталог /opt/radiusproxy на месте — не изменяем"
  fi
}

port_in_use() {
  local port="$1" proto="${2:-tcp}"
  ss -lntu 2>/dev/null | awk '{print $1,$5}' | grep -E "${proto}.*[:.]${port}$" >/dev/null 2>&1
}

check_ports() {
  local p
  for p in 53; do
    if port_in_use "$p" tcp || port_in_use "$p" udp; then
      die "порт 53 занят — освободите или смените схему (сейчас нужен классический DNS на 53)"
    fi
  done
  if port_in_use "$DOT_PORT" tcp; then
    die "порт DoT ${DOT_PORT} занят"
  fi
  if port_in_use "$UI_PORT" tcp; then
    die "порт UI ${UI_PORT} занят (не используем 80/443 — они у radiusproxy)"
  fi
  if port_in_use "$TLS_PORT" tcp; then
    die "порт UI HTTPS ${TLS_PORT} занят"
  fi
  for p in 80 443 8000; do
    if port_in_use "$p" tcp; then
      log "порт ${p} занят другим сервисом — OK, наш стек его не занимает"
    fi
  done
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker + compose уже есть"
    return
  fi
  log "ставим Docker CE (не трогая существующие контейнеры)"
  dnf -y install dnf-plugins-core
  dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || true
  dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
}

prepare_resolved() {
  # Только если stub слушает :53 — иначе не трогаем
  if ss -lntup 2>/dev/null | grep -E 'systemd-resolve|127\.0\.0\.53:53' >/dev/null 2>&1; then
    log "systemd-resolved stub на 53 — отключаем только DNSStubListener"
    mkdir -p /etc/systemd/resolved.conf.d
    cat >/etc/systemd/resolved.conf.d/dns-panel.conf <<'EOF'
[Resolve]
DNSStubListener=no
EOF
    systemctl restart systemd-resolved || true
  else
    log "конфликта systemd-resolved со stub :53 нет — не меняем"
  fi
}

firewall_ports() {
  if ! command -v firewall-cmd >/dev/null 2>&1; then
    log "firewalld нет — пропуск"
    return
  fi
  if ! systemctl is-active --quiet firewalld; then
    log "firewalld не активен — пропуск"
    return
  fi
  log "открываем только порты DNS-стека: 53/tcp+udp, ${DOT_PORT}/tcp, ${UI_PORT}/tcp, ${TLS_PORT}/tcp"
  firewall-cmd --permanent --add-port=53/tcp || true
  firewall-cmd --permanent --add-port=53/udp || true
  firewall-cmd --permanent --add-port="${DOT_PORT}/tcp" || true
  firewall-cmd --permanent --add-port="${UI_PORT}/tcp" || true
  firewall-cmd --permanent --add-port="${TLS_PORT}/tcp" || true
  firewall-cmd --reload || true
}

sync_files() {
  local src
  src="$(cd "$(dirname "$0")" && pwd)"
  if [[ "$src" != "$TARGET_DIR" ]]; then
    log "копируем файлы в ${TARGET_DIR}"
    mkdir -p "$TARGET_DIR"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a \
        --exclude 'config/technitium/' \
        --exclude '.git/' \
        --exclude '.env' \
        "$src"/ "$TARGET_DIR"/
    else
      # без --delete: не сносим config/technitium
      shopt -s dotglob
      for item in "$src"/*; do
        base="$(basename "$item")"
        [[ "$base" == ".git" ]] && continue
        [[ "$base" == ".env" ]] && continue
        if [[ "$base" == "config" ]]; then
          mkdir -p "$TARGET_DIR/config"
          continue
        fi
        cp -a "$item" "$TARGET_DIR"/
      done
      # скопировать содержимое config кроме technitium data если есть
      if [[ -d "$src/config" ]]; then
        mkdir -p "$TARGET_DIR/config"
        for item in "$src/config"/*; do
          [[ -e "$item" ]] || continue
          [[ "$(basename "$item")" == "technitium" ]] && continue
          cp -a "$item" "$TARGET_DIR/config"/
        done
      fi
    fi
  fi
  mkdir -p "$TARGET_DIR/config/technitium"
  if [[ ! -f "$TARGET_DIR/.env" ]]; then
    cp "$TARGET_DIR/.env.example" "$TARGET_DIR/.env"
    if command -v openssl >/dev/null 2>&1; then
      sed -i "s/^PANEL_SESSION_SECRET=.*/PANEL_SESSION_SECRET=$(openssl rand -hex 24)/" "$TARGET_DIR/.env"
    fi
  fi
  grep -q '^DNS_UI_PORT=' "$TARGET_DIR/.env" || echo "DNS_UI_PORT=${UI_PORT}" >>"$TARGET_DIR/.env"
  sed -i "s/^DNS_UI_PORT=.*/DNS_UI_PORT=${UI_PORT}/" "$TARGET_DIR/.env"
  if grep -q '^DNS_UI_TLS_PORT=' "$TARGET_DIR/.env"; then
    sed -i "s/^DNS_UI_TLS_PORT=.*/DNS_UI_TLS_PORT=${TLS_PORT}/" "$TARGET_DIR/.env"
  else
    echo "DNS_UI_TLS_PORT=${TLS_PORT}" >>"$TARGET_DIR/.env"
  fi
  if grep -q '^DNS_DOT_PORT=' "$TARGET_DIR/.env"; then
    sed -i "s/^DNS_DOT_PORT=.*/DNS_DOT_PORT=${DOT_PORT}/" "$TARGET_DIR/.env"
  else
    echo "DNS_DOT_PORT=${DOT_PORT}" >>"$TARGET_DIR/.env"
  fi
}

install_cli() {
  if [[ -f "$TARGET_DIR/dns.sh" ]]; then
    chmod 755 "$TARGET_DIR/dns.sh" "$TARGET_DIR/update.sh" "$TARGET_DIR/uninstall.sh" 2>/dev/null || true
    install -m 755 "$TARGET_DIR/dns.sh" /usr/bin/dns
    install -m 755 "$TARGET_DIR/dns.sh" /usr/local/bin/dns 2>/dev/null || true
    log "CLI menu installed: /usr/bin/dns"
  else
    log "WARN: dns.sh missing — CLI not installed"
  fi
  mkdir -p /etc/dns
  cat >/etc/dns/install.env <<EOF
DNS_UI_PORT=${UI_PORT}
DNS_UI_TLS_PORT=${TLS_PORT}
DNS_DOT_PORT=${DOT_PORT}
INSTALLED_AT=$(date +%Y%m%d%H%M%S)
EOF
  chmod 600 /etc/dns/install.env
}

compose_up() {
  cd "$TARGET_DIR"
  mkdir -p "$TARGET_DIR/config/panel/signals"
  chmod 700 "$TARGET_DIR/config/panel/signals" 2>/dev/null || true
  if [[ -f "$TARGET_DIR/.env" ]]; then
    grep -q '^DNS_HOST_PROJECT=' "$TARGET_DIR/.env" || echo "DNS_HOST_PROJECT=${TARGET_DIR}" >>"$TARGET_DIR/.env"
  fi
  log "docker compose up (project=${COMPOSE_PROJECT}) — только сервисы dns-*"
  docker compose -p "$COMPOSE_PROJECT" --project-directory "$TARGET_DIR" up -d --build
}

wait_technitium() {
  local i
  log "ждём Technitium API на 127.0.0.1:5380…"
  for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:5380/api/status" >/dev/null 2>&1; then
      log "Technitium готов"
      return 0
    fi
    sleep 2
  done
  die "Technitium не ответил за 120с"
}

init_protocols() {
  log "включаем DoH-HTTP:8053 и DoT:853 через API"
  local token
  token="$(curl -sf "http://127.0.0.1:5380/api/user/login?user=admin&pass=admin" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true
  if [[ -z "${token:-}" ]]; then
    log "WARN: не удалось залогиниться admin/admin — настройте DoH/DoT в панели вручную"
    return 0
  fi
  curl -sf -G "http://127.0.0.1:5380/api/settings/set" \
    -H "Authorization: Bearer ${token}" \
    --data-urlencode "enableDnsOverHttp=true" \
    --data-urlencode "dnsOverHttpPort=8053" \
    --data-urlencode "enableDnsOverTls=true" \
    --data-urlencode "dnsOverTlsPort=853" \
    --data-urlencode "forwarders=1.1.1.1,8.8.8.8,https://cloudflare-dns.com/dns-query" \
    --data-urlencode "concurrentForwarding=true" \
    >/dev/null || log "WARN: settings/set не применился"
}

smoke() {
  log "smoke-check"
  curl -sf "http://127.0.0.1:${UI_PORT}/api/health" >/dev/null && log "panel health OK" || log "WARN: panel health fail"
  if command -v dig >/dev/null 2>&1; then
    dig @127.0.0.1 example.com A +time=2 +tries=1 >/dev/null && log "dig OK" || log "WARN: dig fail (норм до прогрева)"
  else
    dnf -y install bind-utils >/dev/null 2>&1 || true
  fi
  echo
  echo "============================================"
  echo " DNS Panel:  http://$(hostname -I | awk '{print $1}'):${UI_PORT}/"
  echo " HTTPS:      https://HOST:${TLS_PORT}/"
  echo " DoH:        http://HOST:${UI_PORT}/dns-query"
  echo " DoT:        HOST:${DOT_PORT}"
  echo " DNS:        HOST:53"
  echo " Login:      admin / admin  (смените пароль)"
  echo " Каталог:    ${TARGET_DIR}"
  echo " CLI:        /usr/bin/dns   (sudo dns)"
  echo " Чужие стеки не останавливались."
  echo "============================================"
}

main() {
  need_root
  # Preserve ports from previous install if env not set
  if [[ -f /etc/dns/install.env ]]; then
    # shellcheck disable=SC1091
    . /etc/dns/install.env
    UI_PORT="${DNS_UI_PORT:-$UI_PORT}"
    TLS_PORT="${DNS_UI_TLS_PORT:-$TLS_PORT}"
    DOT_PORT="${DNS_DOT_PORT:-$DOT_PORT}"
  fi
  check_other_stacks
  check_ports
  install_docker
  prepare_resolved
  firewall_ports
  sync_files
  install_cli
  compose_up
  wait_technitium
  init_protocols
  smoke
}

main "$@"
