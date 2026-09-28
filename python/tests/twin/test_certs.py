from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path

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
