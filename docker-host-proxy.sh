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
  # strip CR (Windows-edited files), comments, export, spaces
  line="${line%$'\r'}"
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && return 0
  line="${line#"${line%%[![:space:]]*}"}"  # ltrim
  # skip non-assignments
  [[ "$line" == *=* ]] || return 0

  # systemd: Environment="HTTP_PROXY=http://..."
  if [[ "$line" =~ ^Environment=\"([A-Za-z0-9_]+)=([^\"]*)\" ]]; then
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
  elif [[ "$line" =~ ^Environment=([A-Za-z0-9_]+)=(.*) ]]; then
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
  else
    # export HTTP_PROXY=... | HTTP_PROXY = ...
    line="${line#export }"
    line="${line#export	}"
    key="${line%%=*}"
    val="${line#*=}"
  fi
  key="${key%"${key##*[![:space:]]}"}"  # rtrim key
  key="${key#"${key%%[![:space:]]*}"}"  # ltrim key
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
}

dns_proxy_ingest_file() {
  local f="$1" line
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    dns_proxy_ingest_line "$line"
  done <"$f"
}

dns_load_host_proxy() {
  local f dir="${DNS_INSTALL_DIR:-${DNS_DIR:-/opt/dns}}"

  # shell env already wins (set_if_empty only fills gaps)

  dns_proxy_ingest_file /etc/environment
  for f in /etc/systemd/system/docker.service.d/*.conf; do
    dns_proxy_ingest_file "$f"
  done
  dns_proxy_ingest_file /etc/dnf/dnf.conf
  dns_proxy_ingest_file /etc/yum.conf
  # panel .env (часто сюда же кладут HTTP_PROXY на корп)
  dns_proxy_ingest_file "${dir}/.env"
  dns_proxy_ingest_file /opt/dns/.env

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
    echo "[dns-proxy] HTTP(S)_PROXY не найден (shell /etc/environment docker.d dnf /opt/dns/.env)"
    echo "[dns-proxy] dockerd без drop-in — pull base images только напрямую"
    echo "[dns-proxy] debug: env HTTP_PROXY=${HTTP_PROXY:-<empty>} http_proxy=${http_proxy:-<empty>}"
    return 0
  fi
  echo "[dns-proxy] using $(dns_proxy_redact "${HTTPS_PROXY:-$HTTP_PROXY}")"

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
  echo "[dns-proxy] daemon-reload…"
  systemctl daemon-reload || echo "[dns-proxy] WARN: daemon-reload failed"
  if systemctl is-active --quiet docker 2>/dev/null; then
    echo "[dns-proxy] restart docker (1–2 мин, контейнеры dns-* кратко упадут)…"
    systemctl restart docker || echo "[dns-proxy] WARN: docker restart failed"
    echo "[dns-proxy] docker снова up"
  fi
}

# No network probe — curl→Hub на корп без proxy (или с долгим timeout) зависает
# на «[3c/4]» и выглядит как поломка. Только load + drop-in + статус.
dns_assert_registry_pull_path() {
  dns_load_host_proxy
  if [[ -n "${HTTP_PROXY}${HTTPS_PROXY}" ]]; then
    echo "[dns-proxy] OK proxy=$(dns_proxy_redact "${HTTPS_PROXY:-$HTTP_PROXY}") → compose"
    return 0
  fi
  echo "[dns-proxy] WARN: HTTP(S)_PROXY пуст после load (shell/environment/docker.d/dnf/.env)"
  echo "[dns-proxy] продолжаем compose — если FROM повиснет 0B, проверь dockerd drop-in:"
  echo "[dns-proxy]   systemctl show docker -p Environment | tr ' ' '\\n' | grep -i proxy"
  return 0
}
