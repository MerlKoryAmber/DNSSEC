#!/usr/bin/env bash
# DNS Panel — update from GitHub (keep or wipe Technitium data)
# Usage: sudo bash /opt/dns/update.sh [--keep-data|--wipe-data]
# Always cd /tmp before clone (do not run from a tree that will be replaced).
set -euo pipefail

REPO_URL="${DNS_REPO_URL:-https://github.com/MerlKoryAmber/DNSSEC}"
BRANCH="${DNS_REPO_BRANCH:-main}"
DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
CLONE_NEW="/opt/dns.src.new"
COMPOSE_PROJECT="dns"
SELF="${DNS_DIR}/update.sh"

red='\033[0;31m'
green='\033[0;32m'
yellow='\033[0;33m'
plain='\033[0m'

if ! pwd >/dev/null 2>&1; then
  cd /tmp 2>/dev/null || cd / || true
fi

wipe_data=""
for arg in "$@"; do
  case "$arg" in
    --wipe-data|--drop-db) wipe_data=1 ;;
    --keep-data|--keep-db) wipe_data=0 ;;
    --continue) ;;
    "") ;;
    *)
      echo "ERROR: unknown argument: $arg"
      echo "Usage: sudo bash ${DNS_DIR}/update.sh [--keep-data|--wipe-data]"
      exit 1
      ;;
  esac
done

if [ -z "$wipe_data" ]; then
  if [ "${DNS_WIPE_DATA:-}" = "1" ]; then
    wipe_data=1
  elif [ "${DNS_WIPE_DATA:-}" = "0" ]; then
    wipe_data=0
  fi
fi

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo -e "${red}ERROR:${plain} run as root"
    exit 1
  fi
}

ask_wipe() {
  if [ -n "$wipe_data" ]; then
    return
  fi
  echo "Wipe Technitium data (zones / query logs / DoT certs)?"
  echo "  y = wipe config/technitium"
  echo "  N = keep data (default)"
  if [ -t 0 ]; then
    read -r -p "Wipe data? [y/N] " reply
  else
    echo "No TTY: keeping data."
    reply=""
  fi
  case "$reply" in
    y|Y|yes|YES) wipe_data=1 ;;
    *) wipe_data=0 ;;
  esac
}

install_cli() {
  if [ -f "${DNS_DIR}/dns.sh" ]; then
    chmod 755 \
      "${DNS_DIR}/dns.sh" "${DNS_DIR}/update.sh" "${DNS_DIR}/uninstall.sh" \
      "${DNS_DIR}/install.sh" "${DNS_DIR}/docker-host-proxy.sh" 2>/dev/null || true
    install -m 755 "${DNS_DIR}/dns.sh" /usr/bin/dns
    install -m 755 "${DNS_DIR}/dns.sh" /usr/local/bin/dns 2>/dev/null || true
    echo "CLI: /usr/bin/dns"
  fi
}

sync_install_env() {
  local ui tls dot
  ui=9080
  tls=9443
  dot=853
  if [ -f "${DNS_DIR}/.env" ]; then
    # .env may reference unset vars — don't kill update under set -u
    set +u
    # shellcheck disable=SC1090
    set -a
    # shellcheck disable=SC1091
    . "${DNS_DIR}/.env" || echo "[dns-update] WARN: .env source failed"
    set +a
    set -u
    ui="${DNS_UI_PORT:-$ui}"
    tls="${DNS_UI_TLS_PORT:-$tls}"
    dot="${DNS_DOT_PORT:-$dot}"
  fi
  mkdir -p /etc/dns
  cat >/etc/dns/install.env <<EOF
DNS_UI_PORT=${ui}
DNS_UI_TLS_PORT=${tls}
DNS_DOT_PORT=${dot}
INSTALLED_AT=$(date +%Y%m%d%H%M%S)
EOF
  chmod 600 /etc/dns/install.env
}

fix_blocky_forwarder() {
  local ip token
  ip=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dns-blocky 2>/dev/null || true)
  [ -z "$ip" ] && return 0
  token="$(curl -sf -X POST "http://127.0.0.1:5380/api/user/login" \
    --data-urlencode "user=admin" \
    --data-urlencode "pass=admin" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')" || true
  [ -z "${token:-}" ] && return 0
  curl -sf -G "http://127.0.0.1:5380/api/settings/set" \
    --data-urlencode "token=${token}" \
    --data-urlencode "forwarders=${ip}" \
    --data-urlencode "forwarderProtocol=Udp" \
    --data-urlencode "dnssecValidation=false" >/dev/null || true
  curl -sf -G "http://127.0.0.1:5380/api/cache/flush" \
    --data-urlencode "token=${token}" >/dev/null 2>&1 || true
  echo "Forwarder synced to Blocky ${ip}"
}

# --- phase 1: clone then re-exec from new tree ---
if [ "${1:-}" != "--continue" ]; then
  need_root
  echo "=== DNS Panel update.sh ==="
  echo "Repo: $REPO_URL ($BRANCH)"
  echo ""
  ask_wipe
  if [ "$wipe_data" = "1" ]; then
    echo -e "${yellow}Will WIPE Technitium data.${plain}"
    cont_flag="--wipe-data"
  else
    echo "Will KEEP Technitium data / .env / TLS / panel prefs / Blocky forwarders."
    cont_flag="--keep-data"
  fi

  if ! command -v git >/dev/null 2>&1; then
    echo "Installing git…"
    dnf install -y git
  fi

  cd /tmp 2>/dev/null || cd / || true
  echo "[1/4] Cloning…"
  rm -rf "$CLONE_NEW"
  # What does THIS host resolve as tip? (ловит корп-кэш/зеркало)
  echo -n "ls-remote main: "
  tip="$(GIT_TERMINAL_PROMPT=0 git ls-remote "$REPO_URL" "refs/heads/${BRANCH}" 2>/dev/null | awk '{print $1; exit}')" || tip=""
  echo "${tip:-<failed>}"
  # no-cache headers — на случай HTTP-прокси, кэширующего smart-HTTP
  GIT_TERMINAL_PROMPT=0 git \
    -c http.extraHeader="Cache-Control: no-cache" \
    -c http.extraHeader="Pragma: no-cache" \
    clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$CLONE_NEW"
  echo "Cloned:"
  git -C "$CLONE_NEW" log -1 --oneline
  got="$(git -C "$CLONE_NEW" rev-parse HEAD)"
  if [ -n "$tip" ] && [ "$got" != "$tip" ]; then
    echo -e "${yellow}WARN:${plain} ls-remote=${tip:0:7} ≠ clone=${got:0:7} — возможен кэш/зеркало proxy"
  fi
  # старый зависающий шаг был ровно: «host proxy / registry check»
  if grep -qF 'host proxy / registry check' "$CLONE_NEW/update.sh" 2>/dev/null; then
    echo -e "${red}ERROR:${plain} в клоне старый update.sh (шаг registry-check). Нужен ≥7998e60."
    echo "  git ls-remote $REPO_URL refs/heads/$BRANCH"
    exit 1
  fi
  if ! grep -qF '[3c/4] host proxy' "$CLONE_NEW/update.sh" 2>/dev/null; then
    echo -e "${yellow}WARN:${plain} update.sh в клоне без шага [3c/4] host proxy"
  fi
  chmod 755 "$CLONE_NEW/update.sh" "$CLONE_NEW/uninstall.sh" "$CLONE_NEW/install.sh" \
    "$CLONE_NEW/dns.sh" "$CLONE_NEW/docker-host-proxy.sh" 2>/dev/null || true
  exec /bin/bash "$CLONE_NEW/update.sh" --continue "$cont_flag"
fi

# --- phase 2: apply into /opt/dns ---
need_root
ask_wipe

echo "[2/4] Syncing code into ${DNS_DIR} (preserving data)…"
mkdir -p "$DNS_DIR"

# Preserve live secrets/data while rsync replaces code.
# config/blocky = Forwarders UI (must NOT reset to repo defaults on keep-data).
rsync -a \
  --exclude '.git/' \
  --exclude 'config/technitium/' \
  --exclude 'config/panel/' \
  --exclude 'config/blocky/' \
  --exclude 'config/nginx/ssl/' \
  --exclude 'nginx/generated/' \
  --exclude '.env' \
  --exclude 'storage/' \
  "$CLONE_NEW"/ "$DNS_DIR"/

# Seed Blocky YAML only if missing (first install / wiped by hand)
if [ ! -f "${DNS_DIR}/config/blocky/config.yml" ]; then
  mkdir -p "${DNS_DIR}/config/blocky"
  if [ -f "${CLONE_NEW}/config/blocky/config.yml" ]; then
    cp -a "${CLONE_NEW}/config/blocky/config.yml" "${DNS_DIR}/config/blocky/config.yml"
    echo "Seeded config/blocky/config.yml from repo (was missing)"
  fi
fi

# Ensure scripts executable
chmod 755 \
  "${DNS_DIR}/dns.sh" "${DNS_DIR}/update.sh" "${DNS_DIR}/uninstall.sh" \
  "${DNS_DIR}/install.sh" "${DNS_DIR}/docker-host-proxy.sh" 2>/dev/null || true

if [ "$wipe_data" = "1" ]; then
  echo "[3/4] Wiping Technitium data…"
  (cd "$DNS_DIR" && docker compose -p "$COMPOSE_PROJECT" stop technitium 2>/dev/null || true)
  rm -rf "${DNS_DIR}/config/technitium"
  mkdir -p "${DNS_DIR}/config/technitium"
else
  echo "[3/4] Keeping Technitium data"
  mkdir -p "${DNS_DIR}/config/technitium"
fi

install_cli
echo "[3b/4] sync install.env…"
sync_install_env

# dockerd pull via host proxy (containers still cleared by compose x-proxy-guard)
echo "[3c/4] host proxy…"
if [ ! -f "${DNS_DIR}/docker-host-proxy.sh" ]; then
  echo -e "${red}ERROR:${plain} missing ${DNS_DIR}/docker-host-proxy.sh" >&2
  exit 1
fi
# shellcheck disable=SC1091
. "${DNS_DIR}/docker-host-proxy.sh"
echo "[3c/4] configure dockerd drop-in…"
dns_configure_docker_host_proxy
dns_load_host_proxy
dns_assert_registry_pull_path
export HTTP_PROXY HTTPS_PROXY NO_PROXY
export http_proxy="${HTTP_PROXY:-}" https_proxy="${HTTPS_PROXY:-}" no_proxy="${NO_PROXY:-}"

echo "[4/4] docker compose up --build…"
cd "$DNS_DIR"
docker compose -p "$COMPOSE_PROJECT" up -d --build
sleep 5
docker restart dns-nginx 2>/dev/null || true
# wait Technitium briefly
for i in $(seq 1 30); do
  curl -sf "http://127.0.0.1:5380/api/status" >/dev/null 2>&1 && break
  sleep 2
done
fix_blocky_forwarder

rm -rf "$CLONE_NEW"
echo ""
echo -e "${green}OK:${plain} update finished"
echo "CLI: /usr/bin/dns"
if [ -f "${DNS_DIR}/.env" ]; then
  set +u
  # shellcheck disable=SC1091
  set -a; . "${DNS_DIR}/.env"; set +a
  set -u
fi
ip=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Panel: http://${ip:-HOST}:${DNS_UI_PORT:-9080}/"
