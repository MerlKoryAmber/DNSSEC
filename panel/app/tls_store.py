from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    load_pem_private_key,
    pkcs12,
)


def ssl_dir() -> Path:
    config_dir = Path(os.environ.get("TECHNITIUM_CONFIG_DIR", "/var/lib/dns-config"))
    path = config_dir / "ssl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def technitium_cert_path() -> str:
    return os.environ.get("TECHNITIUM_CERT_PATH", "/etc/dns/ssl/dns-tls.pfx")


def write_pfx(raw: bytes) -> Path:
    dest = ssl_dir() / "dns-tls.pfx"
    dest.write_bytes(raw)
    return dest


def pem_to_pfx(key_pem: bytes, chain_pem: bytes, key_password: str = "") -> bytes:
    """PEM private key + cert chain → PKCS#12 (empty export password)."""
    pwd = key_password.encode("utf-8") if key_password else None
    try:
        key = load_pem_private_key(key_pem, password=pwd)
    except TypeError as exc:
        raise ValueError("Private key is encrypted — provide key password") from exc
    except Exception as exc:
        raise ValueError(f"Invalid private key: {exc}") from exc

    certs: list[x509.Certificate] = []
    for cert in x509.load_pem_x509_certificates(chain_pem):
        certs.append(cert)
    if not certs:
        # older cryptography: single load
        try:
            certs = [x509.load_pem_x509_certificate(chain_pem)]
        except Exception as exc:
            raise ValueError(f"Invalid certificate / chain: {exc}") from exc
    leaf, *cas = certs
    return pkcs12.serialize_key_and_certificates(
        name=b"dns-tls",
        key=key,
        cert=leaf,
        cas=cas or None,
        encryption_algorithm=NoEncryption(),
    )


def save_pem_sidecars(key_pem: bytes, chain_pem: bytes) -> None:
    d = ssl_dir()
    (d / "dns-tls.key").write_bytes(key_pem)
    (d / "dns-tls.crt").write_bytes(chain_pem)


def settings_params_for_pfx(password: str = "") -> dict[str, Any]:
    return {
        "dnsTlsCertificatePath": technitium_cert_path(),
        "dnsTlsCertificatePassword": password or "",
    }
