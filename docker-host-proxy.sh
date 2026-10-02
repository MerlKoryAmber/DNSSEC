#!/usr/bin/env bash
# dockerd HTTP(S)_PROXY for image pull/build. Runtime containers: compose x-proxy-guard.
# shellcheck shell=bash

dns_load_host_proxy() {
  # Prefer current env; fill gaps from /etc/environment
  local line key val
  if [[ -f /etc/environment ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      key="${line%%=*}"
      val="${line#*=}"
      val="${val%\"}"
      val="${val#\"}"
      val="${val%\'}"
      val="${val#\'}"
      case "$key" in
        HTTP_PROXY|http_proxy)
          [[ -z "${HTTP_PROXY:-}${http_proxy:-}" ]] && HTTP_PROXY="$val"
          ;;
        HTTPS_PROXY|https_proxy)
          [[ -z "${HTTPS_PROXY:-}${https_proxy:-}" ]] && HTTPS_PROXY="$val"
          ;;
        NO_PROXY|no_proxy)
          [[ -z "${NO_PROXY:-}${no_proxy:-}" ]] && NO_PROXY="$val"
          ;;
      esac
    done </etc/environment
  fi
  HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}"
  HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-}}}"
  NO_PROXY="${NO_PROXY:-${no_proxy:-localhost,127.0.0.1,::1}}"
  export HTTP_PROXY HTTPS_PROXY NO_PROXY
}

dns_configure_docker_host_proxy() {
  local drop_dir="/etc/systemd/system/docker.service.d"
  local drop_file="${drop_dir}/http-proxy.conf"
  local tmp new_hash old_hash

  dns_load_host_proxy

  if [[ -z "${HTTP_PROXY}" && -z "${HTTPS_PROXY}" ]]; then
    echo "[dns-proxy] HTTP(S)_PROXY не задан (env / /etc/environment) — dockerd без proxy drop-in"
    return 0
  fi

  mkdir -p "$drop_dir"
  tmp="$(mktemp)"
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

  new_hash="$(sha256sum "$tmp" | awk '{print $1}')"
  old_hash=""
  [[ -f "$drop_file" ]] && old_hash="$(sha256sum "$drop_file" | awk '{print $1}')"

  if [[ "$new_hash" == "$old_hash" ]]; then
    rm -f "$tmp"
    echo "[dns-proxy] dockerd proxy drop-in уже актуален: ${drop_file}"
    return 0
  fi

  mv "$tmp" "$drop_file"
  chmod 644 "$drop_file"
  echo "[dns-proxy] записан ${drop_file} (HTTP_PROXY=${HTTP_PROXY:-<empty>})"

  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  systemctl daemon-reload
  if systemctl is-active --quiet docker 2>/dev/null; then
    echo "[dns-proxy] restart docker — чтобы pull шёл через proxy (краткий рестарт всех контейнеров)"
    systemctl restart docker
  fi
}
