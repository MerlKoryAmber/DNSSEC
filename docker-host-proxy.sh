#!/usr/bin/env bash
# dockerd HTTP(S)_PROXY for image pull/build (FROM layers).
# Build RUN (pip/apk): compose build.args — BuildKit не берёт proxy демона.
# Runtime containers: compose x-proxy-guard (пусто).
# shellcheck shell=bash

dns_proxy_redact() {
  local u="${1:-}"
  if [[ "$u" =~ ^([[:alnum:]+.-]+://)[^@/]+@(.+)$ ]]; then
    printf '%s***@%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
  else
    printf '%s' "$u"
  fi
}

dns_proxy_set_if_empty() {
  local kind="$1" val="$2"
  [[ -z "$val" ]] && return 0
  case "$kind" in
    HTTP) [[ -z "${HTTP_PROXY:-}${http_proxy:-}" ]] && HTTP_PROXY="$val" ;;
    HTTPS) [[ -z "${HTTPS_PROXY:-}${https_proxy:-}" ]] && HTTPS_PROXY="$val" ;;
    NO) [[ -z "${NO_PROXY:-}${no_proxy:-}" ]] && NO_PROXY="$val" ;;
  esac
  return 0
}

dns_proxy_ingest_line() {
  local line="$1" key val
  line="${line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && return 0
  line="${line#"${line%%[![:space:]]*}"}"
  [[ "$line" == *=* ]] || return 0

  if [[ "$line" =~ ^Environment=\"([A-Za-z0-9_]+)=([^\"]*)\" ]]; then
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
  elif [[ "$line" =~ ^Environment=([A-Za-z0-9_]+)=(.*) ]]; then
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
  else
    line="${line#export }"
    line="${line#export	}"
    key="${line%%=*}"
    val="${line#*=}"
  fi
  key="${key%"${key##*[![:space:]]}"}"
  key="${key#"${key%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  val="${val%$'\r'}"

  case "$key" in
    HTTP_PROXY|http_proxy) dns_proxy_set_if_empty HTTP "$val" ;;
    HTTPS_PROXY|https_proxy) dns_proxy_set_if_empty HTTPS "$val" ;;
    NO_PROXY|no_proxy) dns_proxy_set_if_empty NO "$val" ;;
    ALL_PROXY|all_proxy)
      dns_proxy_set_if_empty HTTP "$val"
      dns_proxy_set_if_empty HTTPS "$val"
      ;;
    proxy|Proxy)
      dns_proxy_set_if_empty HTTP "$val"
      dns_proxy_set_if_empty HTTPS "$val"
      ;;
  esac
  return 0
}

dns_proxy_ingest_file() {
  local f="$1" line
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    dns_proxy_ingest_line "$line" || true
  done <"$f" || true
  return 0
}

dns_load_host_proxy() {
  local f dir="${DNS_INSTALL_DIR:-${DNS_DIR:-/opt/dns}}"

  dns_proxy_ingest_file /etc/environment || true
  for f in /etc/systemd/system/docker.service.d/*.conf; do
    dns_proxy_ingest_file "$f" || true
  done
  dns_proxy_ingest_file /etc/dnf/dnf.conf || true
  dns_proxy_ingest_file /etc/yum.conf || true
  dns_proxy_ingest_file "${dir}/.env" || true
  dns_proxy_ingest_file /opt/dns/.env || true

  HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}"
  HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-}}}"
  NO_PROXY="${NO_PROXY:-${no_proxy:-localhost,127.0.0.1,::1}}"
  export HTTP_PROXY HTTPS_PROXY NO_PROXY
  export http_proxy="${HTTP_PROXY}" https_proxy="${HTTPS_PROXY}" no_proxy="${NO_PROXY}"
  return 0
}

# Always return 0 — update.sh идёт с set -euo pipefail, restart docker не должен убивать update.
dns_configure_docker_host_proxy() {
  local drop_dir="/etc/systemd/system/docker.service.d"
  local drop_file="${drop_dir}/http-proxy.conf"
  local tmp new_hash old_hash need_restart=0

  # isolate from caller pipefail/errexit
  set +e
  set +o pipefail 2>/dev/null || true

  echo "[dns-proxy] load…"
  dns_load_host_proxy

  if [[ -z "${HTTP_PROXY}" && -z "${HTTPS_PROXY}" ]]; then
    echo "[dns-proxy] HTTP(S)_PROXY не найден (shell /etc/environment docker.d dnf /opt/dns/.env)"
    echo "[dns-proxy] dockerd без drop-in — pull base images только напрямую"
    echo "[dns-proxy] debug: HTTP_PROXY=<empty>"
    set -e
    set -o pipefail 2>/dev/null || true
    return 0
  fi
  echo "[dns-proxy] using $(dns_proxy_redact "${HTTPS_PROXY:-$HTTP_PROXY}")"

  mkdir -p "$drop_dir" || echo "[dns-proxy] WARN: mkdir $drop_dir failed"
  tmp="$(mktemp /tmp/dns-docker-proxy.XXXXXX)" || {
    echo "[dns-proxy] WARN: mktemp failed"
    set -e
    set -o pipefail 2>/dev/null || true
    return 0
  }
  {
    echo "# managed by dns panel (install/update) — pull/build via host proxy"
    echo "[Service]"
    [[ -n "${HTTP_PROXY}" ]] && printf 'Environment="HTTP_PROXY=%s"\n' "$HTTP_PROXY"
    [[ -n "${HTTPS_PROXY}" ]] && printf 'Environment="HTTPS_PROXY=%s"\n' "$HTTPS_PROXY"
    printf 'Environment="NO_PROXY=%s"\n' "$NO_PROXY"
    [[ -n "${HTTP_PROXY}" ]] && printf 'Environment="http_proxy=%s"\n' "$HTTP_PROXY"
    [[ -n "${HTTPS_PROXY}" ]] && printf 'Environment="https_proxy=%s"\n' "$HTTPS_PROXY"
    printf 'Environment="no_proxy=%s"\n' "$NO_PROXY"
  } >"$tmp"

  new_hash="$(sha256sum "$tmp" 2>/dev/null | awk '{print $1}')"
  old_hash=""
  [[ -f "$drop_file" ]] && old_hash="$(sha256sum "$drop_file" 2>/dev/null | awk '{print $1}')"

  if [[ -n "$new_hash" && "$new_hash" == "$old_hash" ]]; then
    rm -f "$tmp"
    echo "[dns-proxy] drop-in актуален: ${drop_file}"
    set -e
    set -o pipefail 2>/dev/null || true
    return 0
  fi

  if mv "$tmp" "$drop_file"; then
    chmod 644 "$drop_file" 2>/dev/null || true
    echo "[dns-proxy] записан ${drop_file}"
    need_restart=1
  else
    echo "[dns-proxy] WARN: не смог записать ${drop_file}"
    rm -f "$tmp"
  fi

  if [[ "$need_restart" -eq 1 ]] && command -v systemctl >/dev/null 2>&1; then
    echo "[dns-proxy] daemon-reload…"
    systemctl daemon-reload || echo "[dns-proxy] WARN: daemon-reload failed"
    if systemctl is-active --quiet docker 2>/dev/null; then
      echo "[dns-proxy] restart docker (до 90с)…"
      if command -v timeout >/dev/null 2>&1; then
        timeout 90 systemctl restart docker || echo "[dns-proxy] WARN: docker restart rc=$?"
      else
        systemctl restart docker || echo "[dns-proxy] WARN: docker restart rc=$?"
      fi
      echo "[dns-proxy] docker restart done"
    else
      echo "[dns-proxy] docker не active — restart пропуск"
    fi
  fi

  set -e
  set -o pipefail 2>/dev/null || true
  return 0
}

dns_assert_registry_pull_path() {
  dns_load_host_proxy || true
  if [[ -n "${HTTP_PROXY}${HTTPS_PROXY}" ]]; then
    echo "[dns-proxy] OK proxy=$(dns_proxy_redact "${HTTPS_PROXY:-$HTTP_PROXY}") → compose"
  else
    echo "[dns-proxy] WARN: HTTP(S)_PROXY пуст — compose всё равно"
  fi
  return 0
}
