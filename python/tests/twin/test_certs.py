from __future__ import annotations

import asyncio
import ipaddress
import os
import sys
from pathlib import Path

import pytest
from cryptography import x509

from ecoflow_twin.certs import SERVER_IPS, SERVER_NAMES, ensure_certs


def test_creates_and_reuses(tmp_path: Path) -> None:
    first = ensure_certs(tmp_path)
    ca_bytes = first.ca_file.read_bytes()
    second = ensure_certs(tmp_path)
    assert second.ca_file.read_bytes() == ca_bytes


def test_server_cert_covers_local_and_ecoflow_names(tmp_path: Path) -> None:
    cert = x509.load_pem_x509_certificate(ensure_certs(tmp_path).cert_file.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(san.get_values_for_type(x509.DNSName)) == set(SERVER_NAMES)
    ips = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    assert ips == {str(ipaddress.ip_address(i)) for i in SERVER_IPS}


async def test_tls_handshake_with_strict_client(tmp_path: Path) -> None:
    """Python 3.13+ verifies strictly (AKI/SKI required): a real handshake."""
    certs = ensure_certs(tmp_path)

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(await reader.readexactly(4))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(
        echo, "127.0.0.1", 0, ssl=certs.server_context()
    )
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", port, ssl=certs.client_context()
    )
    writer.write(b"ping")
    assert await reader.readexactly(4) == b"ping"
    writer.close()
    server.close()
    await server.wait_closed()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_server_key_is_owner_only(tmp_path: Path) -> None:
    certs = ensure_certs(tmp_path)
    assert certs.key_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_reused_key_is_tightened(tmp_path: Path) -> None:
    certs = ensure_certs(tmp_path)
    certs.key_file.chmod(0o644)  # as written by older versions
    ensure_certs(tmp_path)
    assert certs.key_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_refuses_shared_key_that_cannot_be_tightened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    certs = ensure_certs(tmp_path)
    certs.key_file.chmod(0o644)

    def fail_chmod(self: Path, mode: int) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "chmod", fail_chmod)
    with pytest.raises(PermissionError, match="owner-only"):
        ensure_certs(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_chmod_failure_is_fine_when_key_already_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_certs(tmp_path)  # key is 0600

    def fail_chmod(self: Path, mode: int) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "chmod", fail_chmod)
    ensure_certs(tmp_path)  # must not raise


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
@pytest.mark.parametrize("name", ["server.key", "server.pem", "ca.pem"])
def test_refuses_symlink_in_state_dir(tmp_path: Path, name: str) -> None:
    """A planted link would make the twin write its key where others can read it."""
    target = tmp_path / "elsewhere"
    target.write_bytes(b"not ours")
    state = tmp_path / "state"
    state.mkdir()
    (state / name).symlink_to(target)
    with pytest.raises(PermissionError, match="symlink"):
        ensure_certs(state)
    assert target.read_bytes() == b"not ours"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_refuses_symlinked_key_on_reuse(tmp_path: Path) -> None:
    certs = ensure_certs(tmp_path)
    moved = tmp_path / "moved.key"
    certs.key_file.rename(moved)
    certs.key_file.symlink_to(moved)
    with pytest.raises(PermissionError, match="symlink"):
        ensure_certs(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX ownership")
def test_refuses_key_owned_by_another_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    certs = ensure_certs(tmp_path)
    certs.key_file.chmod(0o644)
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)
    with pytest.raises(PermissionError, match="another user"):
        ensure_certs(tmp_path)
    # Refused before any chmod: someone else's file is left as it was.
    assert certs.key_file.stat().st_mode & 0o777 == 0o644


def test_regenerates_leftovers_without_following_them(tmp_path: Path) -> None:
    """A partial state dir is rebuilt from scratch (stale files are replaced)."""
    (tmp_path / "server.pem").write_bytes(b"stale")
    certs = ensure_certs(tmp_path)
    assert certs.cert_file.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
