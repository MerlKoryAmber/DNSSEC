"""TLS for DNS Panel UI (nginx) — PEM cert+key like squid-panel Panel TLS."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

MAX_PEM = 256 * 1024
DEFAULT_HTTPS_PORT = 9443
# Reserved host ports (radiusproxy / DNS / lab) — HTTPS must not collide
_BLOCKED_PORTS = {53, 80, 443, 8000, 1812, 1813, 5380}


def ssl_dir() -> Path:
    path = Path(os.environ.get("PANEL_TLS_DIR", "/var/lib/nginx-ssl"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cert_path() -> Path:
    return ssl_dir() / "panel.crt"


def key_path() -> Path:
    return ssl_dir() / "panel.key"


def _data_dir() -> Path:
    path = Path(os.environ.get("PANEL_DATA_DIR", "/var/lib/panel"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ui_cfg_path() -> Path:
    return _data_dir() / "ui.yml"


def _env_file() -> Path:
    return Path(os.environ.get("DNS_ENV_FILE", "/var/lib/panel/host.env"))


def generated_dir() -> Path:
    path = Path(os.environ.get("PANEL_NGINX_GEN_DIR", "/var/lib/nginx-generated"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_ui_cfg() -> dict[str, Any]:
    cfg = _ui_cfg_path()
    if not cfg.is_file():
        return {}
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_ui_cfg(data: dict[str, Any]) -> None:
    cfg = _ui_cfg_path()
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def read_https_port() -> int:
    data = _load_ui_cfg()
    try:
        p = int(data.get("httpsPort") or 0)
        if 1 <= p <= 65535:
            return p
    except Exception:
        pass
    try:
        return int(os.environ.get("PANEL_HTTPS_PORT", str(DEFAULT_HTTPS_PORT)))
    except ValueError:
        return DEFAULT_HTTPS_PORT


def read_http_enabled() -> bool:
    data = _load_ui_cfg()
    if "httpEnabled" in data:
        return bool(data.get("httpEnabled"))
    return True


def validate_https_port(port: int) -> int:
    try:
        p = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("Port must be an integer") from exc
    if p < 1 or p > 65535:
        raise ValueError("Port must be 1…65535")
    if p in _BLOCKED_PORTS:
        raise ValueError(f"Port {p} is reserved (HTTP UI / DNS / lab services)")
    return p


def write_http_server_conf(http_enabled: bool | None = None, https_port: int | None = None) -> None:
    """HTTP :80 — serve UI or redirect to HTTPS."""
    enabled = read_http_enabled() if http_enabled is None else bool(http_enabled)
    port = read_https_port() if https_port is None else int(https_port)
    path = generated_dir() / "http.conf"
    if enabled:
        text = (
            "server {\n"
            "    listen 80;\n"
            "    server_name _;\n"
            "    include /etc/nginx/panel_locations.conf;\n"
            "}\n"
        )
    else:
        text = (
            "server {\n"
            "    listen 80;\n"
            "    server_name _;\n"
            f"    return 301 https://$host:{port}$request_uri;\n"
            "}\n"
        )
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def ensure_http_conf() -> None:
    write_http_server_conf()


def write_listen_settings(port: int, http_enabled: bool) -> dict[str, Any]:
    p = validate_https_port(port)
    enabled = bool(http_enabled)
    data = _load_ui_cfg()
    data["httpsPort"] = p
    data["httpEnabled"] = enabled
    _save_ui_cfg(data)

    env_path = _env_file()
    try:
        lines: list[str] = []
        if env_path.is_file():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        found = False
        for line in lines:
            if re.match(r"^\s*DNS_UI_TLS_PORT\s*=", line):
                out.append(f"DNS_UI_TLS_PORT={p}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"DNS_UI_TLS_PORT={p}")
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        pass

    write_http_server_conf(enabled, p)
    return {"httpsPort": p, "httpEnabled": enabled}


def write_https_port(port: int) -> int:
    """Back-compat: keep HTTP flag, change port only."""
    return write_listen_settings(port, read_http_enabled())["httpsPort"]


def present() -> bool:
    c, k = cert_path(), key_path()
    try:
        return c.is_file() and k.is_file() and c.stat().st_size > 64 and k.stat().st_size > 64
    except OSError:
        return False


def _load_cert() -> x509.Certificate | None:
    if not present():
        return None
    try:
        return x509.load_pem_x509_certificate(cert_path().read_bytes())
    except Exception:
        return None


def status() -> dict[str, Any]:
    cert = _load_cert()
    out: dict[str, Any] = {
        "present": present(),
        "selfSigned": False,
        "subject": None,
        "issuer": None,
        "notBefore": None,
        "notAfter": None,
        "httpsPort": read_https_port(),
        "httpPort": int(os.environ.get("PANEL_HTTP_PORT", "9080")),
        "httpEnabled": read_http_enabled(),
    }
    if not cert:
        return out
    try:
        sub = cert.subject.rfc4514_string()
        iss = cert.issuer.rfc4514_string()
        out["subject"] = sub
        out["issuer"] = iss
        out["selfSigned"] = sub == iss
        out["notBefore"] = cert.not_valid_before_utc.isoformat()
        out["notAfter"] = cert.not_valid_after_utc.isoformat()
    except Exception:
        pass
    return out


def assert_pem_cert(raw: bytes) -> None:
    if len(raw) < 64 or len(raw) > MAX_PEM:
        raise ValueError("Certificate must be between 64 bytes and 256 KB")
    text = raw.decode("utf-8", errors="replace")
    if "-----BEGIN CERTIFICATE-----" not in text or "-----END CERTIFICATE-----" not in text:
        raise ValueError("File is not a PEM certificate")
    if "\0" in text:
        raise ValueError("Certificate contains NUL")
    try:
        list(x509.load_pem_x509_certificates(raw))
    except Exception as exc:
        raise ValueError(f"Invalid certificate: {exc}") from exc


def assert_pem_key(raw: bytes) -> None:
    if len(raw) < 64 or len(raw) > MAX_PEM:
        raise ValueError("Private key must be between 64 bytes and 256 KB")
    text = raw.decode("utf-8", errors="replace")
    ok = (
        ("BEGIN PRIVATE KEY" in text and "END PRIVATE KEY" in text)
        or ("BEGIN RSA PRIVATE KEY" in text and "END RSA PRIVATE KEY" in text)
        or ("BEGIN EC PRIVATE KEY" in text and "END EC PRIVATE KEY" in text)
    )
    if not ok:
        raise ValueError("File is not a PEM private key")
    if "\0" in text:
        raise ValueError("Private key contains NUL")
    try:
        serialization.load_pem_private_key(raw, password=None)
    except TypeError as exc:
        raise ValueError("Encrypted private key is not supported — decrypt first") from exc
    except Exception as exc:
        raise ValueError(f"Invalid private key: {exc}") from exc


def write_pem(key_pem: bytes, cert_pem: bytes) -> None:
    assert_pem_key(key_pem)
    assert_pem_cert(cert_pem)
    key = serialization.load_pem_private_key(key_pem, password=None)
    leaf = x509.load_pem_x509_certificates(cert_pem)[0]
    pub1 = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub2 = leaf.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if pub1 != pub2:
        raise ValueError("Private key does not match certificate")

    d = ssl_dir()
    tmp_key = d / "panel.key.tmp"
    tmp_crt = d / "panel.crt.tmp"
    tmp_key.write_bytes(key_pem)
    tmp_crt.write_bytes(cert_pem)
    os.chmod(tmp_key, 0o600)
    os.chmod(tmp_crt, 0o644)
    tmp_key.replace(key_path())
    tmp_crt.replace(cert_path())
    try:
        os.chmod(key_path(), 0o600)
        os.chmod(cert_path(), 0o644)
    except OSError:
        pass


def ensure_self_signed(cn: str = "dns-panel") -> bool:
    """Create lab self-signed cert if missing. Returns True if created."""
    if present():
        return False
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DNS Panel"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName(cn),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    write_pem(key_pem, cert_pem)
    return True


async def _nginx_http_ok() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get("http://nginx/")
            return r.status_code < 500
    except Exception:
        return False


async def reload_nginx() -> dict[str, Any]:
    """Ask stack-watch to HUP dns-nginx (no docker.sock in panel)."""
    from . import signals

    out = signals.request_nginx_hup()
    # HUP is fast; give watcher a moment
    await asyncio.sleep(1.5)
    ok = await _nginx_http_ok()
    return {
        "reloaded": ok,
        "reason": "nginx HUP signaled" if ok else "nginx HUP signaled (probe pending)",
        **out,
    }


async def apply_https_port(port: int, http_enabled: bool | None = None) -> dict[str, Any]:
    """Persist listen settings + signal stack-watch to recreate nginx."""
    from . import signals

    enabled = read_http_enabled() if http_enabled is None else bool(http_enabled)
    saved = write_listen_settings(port, enabled)
    # conf already on disk — recreate picks new host port from .env
    sig = signals.request_nginx_recreate()
    ok = False
    for _ in range(45):
        await asyncio.sleep(1)
        if await _nginx_http_ok():
            ok = True
            break
    return {
        **saved,
        "applied": ok,
        "reason": "nginx recreate signaled" if ok else "nginx recreate signaled — still starting",
        **sig,
    }
