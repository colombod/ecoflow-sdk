"""A private CA and a server certificate for the twin (EC P-256).

Generated once per state directory. Clients trust the twin by trusting
``ca.pem`` (``ECOFLOW_CA_FILE``, ``curl --cacert``, ``mosquitto_sub --cafile``).
The EcoFlow hostnames are included so the same certificate serves Twin 3
(DNS rewriting for unmodified apps).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SERVER_NAMES = (
    "localhost",
    "api-e.ecoflow.com",
    "api.ecoflow.com",
    "mqtt-e.ecoflow.com",
    "mqtt.ecoflow.com",
)
SERVER_IPS = ("127.0.0.1", "::1")


@dataclass(frozen=True)
class TwinCerts:
    ca_file: Path
    cert_file: Path
    key_file: Path

    def server_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.cert_file, self.key_file)
        return ctx

    def client_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=str(self.ca_file))


def ensure_certs(state_dir: Path) -> TwinCerts:
    """Create (or reuse) ``ca.pem``, ``server.pem`` and ``server.key``."""
    state_dir.mkdir(parents=True, exist_ok=True)
    certs = TwinCerts(
        state_dir / "ca.pem", state_dir / "server.pem", state_dir / "server.key"
    )
    files = (certs.ca_file, certs.cert_file, certs.key_file)
    for path in files:
        # A symlink here (e.g. planted in a shared state dir) would make us
        # write, chmod or serve someone else's file. Never follow one.
        if path.is_symlink():
            raise PermissionError(f"{path} is a symlink; refusing to use it")
    if all(p.exists() for p in files):
        _restrict(certs.key_file)  # tighten keys written by older versions
        return certs
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "EcoFlow twin local CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = [x509.DNSName(n) for n in SERVER_NAMES]
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in SERVER_IPS]
    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ecoflow-twin")])
        )
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    _write_new(certs.ca_file, ca_cert.public_bytes(pem), 0o644)
    _write_new(certs.cert_file, cert.public_bytes(pem), 0o644)
    key_pem = key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    # The server certificate is valid for EcoFlow's real host names (so apps can
    # be pointed at the twin by DNS). Anyone who can read this key and whose
    # machine trusts ca.pem could impersonate EcoFlow, so it is owner-only.
    _write_new(certs.key_file, key_pem, 0o600)
    _restrict(certs.key_file)
    return certs


def _write_new(path: Path, data: bytes, mode: int) -> None:
    """Write *data* to a freshly created *path*, never through a symlink.

    Any leftover file is removed first; ``O_EXCL`` then refuses a name that
    reappeared in between (a symlink included) instead of following it.
    """
    path.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags | getattr(os, "O_BINARY", 0), mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _restrict(path: Path) -> None:
    """Make *path* readable by its owner only, or refuse to use it.

    On POSIX a key that stays group/world-accessible (e.g. on a read-only
    mount where chmod fails) must not be served. Windows has no POSIX modes,
    so there the best effort is kept.
    """
    try:
        path.chmod(0o600)
    except OSError:
        if sys.platform == "win32":  # pragma: no cover - no POSIX modes
            return
    if sys.platform == "win32":  # pragma: no cover - no POSIX modes
        return
    st = path.lstat()
    if st.st_uid != os.getuid():
        raise PermissionError(
            f"{path} belongs to another user; use a --state-dir only you can write"
        )
    if st.st_mode & 0o077:
        raise PermissionError(
            f"{path} is accessible by other users and could not be made "
            "owner-only; fix its permissions or use a fresh --state-dir"
        )
