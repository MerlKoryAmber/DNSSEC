#!/usr/bin/env bash
# DNS Panel — pin / snapshot / apply / rollback stack container images.
# Usage (root, from host with /opt/dns):
#   bash stack-images.sh snapshot   # save current versions.env → rollback slot
#   bash stack-images.sh apply      # source versions.env, pull, compose up
#   bash stack-images.sh rollback   # restore previous slot, pull, compose up
#   bash stack-images.sh status
set -euo pipefail

DNS_DIR="${DNS_INSTALL_DIR:-/opt/dns}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-dns}"
VERSIONS_FILE="${DNS_DIR}/versions.env"
ROLLBACK_DIR="${DNS_DIR}/storage/rollback"
PREV_FILE="${ROLLBACK_DIR}/versions.env.previous"
META_FILE="${ROLLBACK_DIR}/meta.txt"

red='\033[0;31m'
green='\033[0;32m'
yellow='\033[0;33m'
plain='\033[0m'

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo -e "${red}ERROR:${plain} run as root"
    exit 1
  fi
}

load_versions_file() {
  local f="$1"
  if [ ! -f "$f" ]; then
    echo -e "${red}ERROR:${plain} missing $f"
    return 1
  fi
  set +u
  set -a
  # shellcheck disable=SC1090
  . "$f"
  set +a
  set -u
  export DNS_TECHNITIUM_IMAGE DNS_BLOCKY_IMAGE DNS_NGINX_IMAGE DNS_DOCKER_CLI_IMAGE
}

compose() {
  # shellcheck disable=SC2086
  docker compose -p "$COMPOSE_PROJECT" --project-directory "$DNS_DIR" "$@"
}

running_image() {
  local name="$1"
  docker inspect -f '{{.Config.Image}}' "$name" 2>/dev/null || echo "(not running)"
}

cmd_status() {
  echo "versions.env: ${VERSIONS_FILE}"
  if [ -f "$VERSIONS_FILE" ]; then
    grep -E '^DNS_.*_IMAGE=' "$VERSIONS_FILE" || true
  else
    echo "(missing)"
  fi
  echo ""
  echo "running:"
  echo "  technitium: $(running_image dns-technitium)"
  echo "  blocky:     $(running_image dns-blocky)"
  echo "  nginx:      $(running_image dns-nginx)"
  echo ""
  if [ -f "$PREV_FILE" ]; then
    echo "rollback slot: $PREV_FILE"
    grep -E '^DNS_.*_IMAGE=' "$PREV_FILE" || true
    [ -f "$META_FILE" ] && cat "$META_FILE"
  else
    echo "rollback slot: (empty — run snapshot before apply)"
  fi
}

cmd_snapshot() {
  need_root
  mkdir -p "$ROLLBACK_DIR"
  # Always pin rollback slot to *currently running* images (not desired versions.env).
  local tech blocky nginx cli
  tech=$(running_image dns-technitium)
  blocky=$(running_image dns-blocky)
  nginx=$(running_image dns-nginx)
  cli="${DNS_DOCKER_CLI_IMAGE:-docker.io/library/docker:27-cli}"
  if [ "$tech" = "(not running)" ] || [ "$blocky" = "(not running)" ] || [ "$nginx" = "(not running)" ]; then
    echo -e "${yellow}WARN:${plain} some containers not running — snapshot may be incomplete"
  fi
  cat >"$PREV_FILE" <<EOF
DNS_TECHNITIUM_IMAGE=${tech}
DNS_BLOCKY_IMAGE=${blocky}
DNS_NGINX_IMAGE=${nginx}
DNS_DOCKER_CLI_IMAGE=${cli}
EOF
  {
    echo "saved_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "saved_at_msk=$(TZ=Europe/Moscow date +%Y-%m-%dT%H:%M:%S) МСК"
    echo "technitium_was=${tech}"
    echo "blocky_was=${blocky}"
    echo "nginx_was=${nginx}"
  } >"$META_FILE"
  echo -e "${green}OK:${plain} snapshot → $PREV_FILE"
  cmd_status
}

cmd_apply() {
  need_root
  if [ ! -f "$VERSIONS_FILE" ]; then
    echo -e "${red}ERROR:${plain} missing $VERSIONS_FILE"
    exit 1
  fi
  # Auto-snapshot only if rollback slot empty (do not clobber an existing slot).
  if [ ! -f "$PREV_FILE" ]; then
    echo "Rollback slot empty — snapshot running images first…"
    cmd_snapshot
  fi

  load_versions_file "$VERSIONS_FILE"
  echo "Applying pins:"
  grep -E '^DNS_.*_IMAGE=' "$VERSIONS_FILE" || true
  cd "$DNS_DIR"
  compose pull technitium blocky nginx || true
  compose up -d --build --force-recreate technitium blocky nginx blocky-watch panel
  sleep 3
  docker restart dns-nginx 2>/dev/null || true
  echo -e "${green}OK:${plain} stack images applied"
  cmd_status
}

cmd_rollback() {
  need_root
  if [ ! -f "$PREV_FILE" ]; then
    echo -e "${red}ERROR:${plain} no rollback slot ($PREV_FILE). Run snapshot/apply first."
    exit 1
  fi
  echo "Restoring previous pins from $PREV_FILE"
  grep -E '^DNS_.*_IMAGE=' "$PREV_FILE" || true
  if [ -t 0 ] && [ "${DNS_ASSUME_YES:-}" != "1" ]; then
    read -r -p "Rollback stack images now? [y/N] " reply
    case "${reply:-}" in y|Y|yes|YES) ;; *) echo "Cancelled."; return 0 ;; esac
  fi
  # keep current as new previous (swap)
  mkdir -p "$ROLLBACK_DIR"
  if [ -f "$VERSIONS_FILE" ]; then
    cp -a "$VERSIONS_FILE" "${ROLLBACK_DIR}/versions.env.before-rollback"
  fi
  cp -a "$PREV_FILE" "$VERSIONS_FILE"
  load_versions_file "$VERSIONS_FILE"
  cd "$DNS_DIR"
  compose pull technitium blocky nginx || true
  compose up -d --build --force-recreate technitium blocky nginx blocky-watch panel
  sleep 3
  docker restart dns-nginx 2>/dev/null || true
  echo -e "${green}OK:${plain} rolled back to previous image pins"
  cmd_status
}

case "${1:-}" in
  status) cmd_status ;;
  snapshot) cmd_snapshot ;;
  apply) cmd_apply ;;
  rollback) cmd_rollback ;;
  *)
    echo "Usage: $0 {status|snapshot|apply|rollback}"
    exit 1
    ;;
esac
