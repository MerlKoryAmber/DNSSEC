#!/usr/bin/env bash
# dockerd HTTP(S)_PROXY for image pull/build (FROM layers).
# Build RUN (pip/apk): compose build.args — BuildKit не берёт proxy демона.
# Runtime containers: compose x-proxy-guard (пусто).
# shellcheck shell=bash

dns_proxy_redact() {
  # http://user:pass@host:port → http://***@host:port
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
}

dns_proxy_ingest_line() {
  local line="$1" key val
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && return 0
  # Environment="HTTP_PROXY=..." (systemd drop-in)
  if [[ "$line" =~ Environment=\"([A-Za-z0-9_]+)=([^\"]*)\" ]]; then
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
  elif [[ "$line" =~ Environment=([A-Za-z0-9_]+)=(.*) ]]; then
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
    val="${val%\"}"
    val="${val#\"}"
  else
    key="${line%%=*}"
    val="${line#*=}"
    val="${val%\"}"
    val="${val#\"}"
    val="${val%\'}"
    val="${val#\'}"
  fi
  case "$key" in
    HTTP_PROXY|http_proxy) dns_proxy_set_if_empty HTTP "$val" ;;
    HTTPS_PROXY|https_proxy) dns_proxy_set_if_empty HTTPS "$val" ;;
    NO_PROXY|no_proxy) dns_proxy_set_if_empty NO "$val" ;;
    proxy|Proxy)
      dns_proxy_set_if_empty HTTP "$val"
      dns_proxy_set_if_empty HTTPS "$val"
      ;;
  esac
}

dns_load_host_proxy() {
  local f line

  if [[ -f /etc/environment ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      dns_proxy_ingest_line "$line"
    done </etc/environment
  fi

  for f in /etc/systemd/system/docker.service.d/*.conf; do
    [[ -f "$f" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      dns_proxy_ingest_line "$line"
    done <"$f"
  done

  for f in /etc/dnf/dnf.conf /etc/yum.conf; do
    [[ -f "$f" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      dns_proxy_ingest_line "$line"
    done <"$f"
  done

  HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}"
  HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-}}}"
  NO_PROXY="${NO_PROXY:-${no_proxy:-localhost,127.0.0.1,::1}}"
  export HTTP_PROXY HTTPS_PROXY NO_PROXY
  export http_proxy="${HTTP_PROXY}" https_proxy="${HTTPS_PROXY}" no_proxy="${NO_PROXY}"
}

dns_configure_docker_host_proxy() {
  local drop_dir="/etc/systemd/system/docker.service.d"
  local drop_file="${drop_dir}/http-proxy.conf"
  local tmp new_hash old_hash

  dns_load_host_proxy

  if [[ -z "${HTTP_PROXY}" && -z "${HTTPS_PROXY}" ]]; then
    echo "[dns-proxy] HTTP(S)_PROXY не найден (env / /etc/environment / docker.service.d / dnf.conf)"
    echo "[dns-proxy] dockerd без drop-in — pull base images только напрямую"
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
    echo "[dns-proxy] dockerd drop-in актуален: ${drop_file} ($(dns_proxy_redact "${HTTP_PROXY:-${HTTPS_PROXY}}"))"
    return 0
  fi

  mv "$tmp" "$drop_file"
  chmod 644 "$drop_file"
  echo "[dns-proxy] записан ${drop_file} ($(dns_proxy_redact "${HTTP_PROXY:-${HTTPS_PROXY}}"))"

  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  systemctl daemon-reload || echo "[dns-proxy] WARN: daemon-reload failed"
  if systemctl is-active --quiet docker 2>/dev/null; then
    echo "[dns-proxy] restart docker — pull через proxy (краткий рестарт контейнеров)"
    systemctl restart docker || echo "[dns-proxy] WARN: docker restart failed"
  fi
}

dns_registry_http_code() {
  # stdout: numeric code or 000 — never non-zero exit (set -e safe)
  local code
  if ! command -v curl >/dev/null 2>&1; then
    echo "000"
    return 0
  fi
  if command -v timeout >/dev/null 2>&1; then
    code="$(timeout 8 curl -sS -o /dev/null -w '%{http_code}' https://registry-1.docker.io/v2/ 2>/dev/null)" || code="000"
  else
    code="$(curl -sS --connect-timeout 5 --max-time 8 -o /dev/null -w '%{http_code}' https://registry-1.docker.io/v2/ 2>/dev/null)" || code="000"
  fi
  [[ -z "$code" ]] && code="000"
  echo "$code"
  return 0
}

dns_local_base_images_ok() {
  # True if compose can build without registry (bases already local)
  docker image inspect python:3.12-slim >/dev/null 2>&1 || return 1
  return 0
}

# Probe Docker Hub before compose --build.
# Return 0 = continue; 1 = hard stop (print reason to stdout).
dns_assert_registry_pull_path() {
  local code
  dns_load_host_proxy

  if [[ -n "${HTTP_PROXY}${HTTPS_PROXY}" ]]; then
    echo "[dns-proxy] build/pull path: proxy=$(dns_proxy_redact "${HTTPS_PROXY:-$HTTP_PROXY}")"
    return 0
  fi

  code="$(dns_registry_http_code)"
  if [[ "$code" == "200" || "$code" == "401" ]]; then
    echo "[dns-proxy] registry напрямую OK (HTTP ${code}), proxy не задан"
    return 0
  fi

  if dns_local_base_images_ok; then
    echo "[dns-proxy] WARN: Hub недоступен (HTTP ${code}), proxy нет — но python:3.12-slim уже локально, продолжаем"
    return 0
  fi

  echo "[dns-proxy] ERROR: Docker Hub недоступен (HTTP ${code}) и HTTP(S)_PROXY не задан."
  echo "[dns-proxy] UPDATE ОСТАНОВЛЕН до compose — иначе снова вечный 0B на FROM."
  echo "[dns-proxy] Задай proxy и повтори: sudo dns → Update  (или: bash /opt/dns/update.sh --keep-data)"
  echo "[dns-proxy]   /etc/environment:"
  echo "[dns-proxy]     HTTP_PROXY=http://USER:PASS@proxy.example:3128"
  echo "[dns-proxy]     HTTPS_PROXY=http://USER:PASS@proxy.example:3128"
  echo "[dns-proxy]     NO_PROXY=localhost,127.0.0.1,::1"
  echo "[dns-proxy]   или proxy= в /etc/dnf/dnf.conf"
  return 1
}
