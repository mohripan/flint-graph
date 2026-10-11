"""Owned local TCP/TLS boundary; no third-party network or real credentials."""

from __future__ import annotations

import asyncio
import socket
import ssl
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from flint_graph.domain.errors import BadRequestError
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher


@pytest.fixture
def tls_context(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "report.invalid")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("report.invalid")]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "test-ca.pem", tmp_path / "test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # Substitute only the disposable test trust root, never disable verification.
    monkeypatch.setattr(certifi, "where", lambda: str(cert_path))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


@asynccontextmanager
async def owned_server(*, tls=None, response=None):
    received, sni = [], []
    if tls is not None:
        tls.set_servername_callback(lambda socket, name, context: sni.append(name))

    async def serve(reader, writer):
        try:
            received.append(await reader.readuntil(b"\r\n\r\n"))
            payload = (
                response(writer.get_extra_info("sockname")[1]) if callable(response) else response
            )
            writer.write(payload or b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nPublic report")
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=tls)
    try:
        yield server.sockets[0].getsockname()[1], received, sni
    finally:
        server.close()
        await server.wait_closed()


def owned_dns(monkeypatch):
    async def resolve(host, port, *args, **kwargs):
        assert host in {"report.invalid", "wrong.invalid"}
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)


@pytest.mark.anyio
async def test_owned_https_preserves_host_sni_certificate_verification_and_final_url(
    tls_context, monkeypatch
):
    owned_dns(monkeypatch)
    async with owned_server(tls=tls_context) as (port, received, sni):
        url = f"https://report.invalid:{port}/report"
        fetched = await HTTPURLFetcher(
            timeout_seconds=2, max_bytes=100, allow_private_addresses=True
        ).fetch(url)
    assert fetched.body == b"Public report"
    assert fetched.final_url == url
    assert sni == ["report.invalid"]
    assert len(received) == 1
    assert f"Host: report.invalid:{port}\r\n".encode() in received[0]


@pytest.mark.anyio
async def test_owned_https_rejects_hostname_mismatch_without_http_request(tls_context, monkeypatch):
    owned_dns(monkeypatch)
    async with owned_server(tls=tls_context) as (port, received, sni):
        with pytest.raises(BadRequestError, match="could not be fetched"):
            await HTTPURLFetcher(
                timeout_seconds=2, max_bytes=100, allow_private_addresses=True
            ).fetch(f"https://wrong.invalid:{port}/sentinel")
    assert received == []
    assert sni == ["wrong.invalid"]


@pytest.mark.anyio
async def test_owned_https_redirect_cannot_reuse_tls_for_another_hostname(tls_context, monkeypatch):
    owned_dns(monkeypatch)

    def redirect(port):
        return (
            f"HTTP/1.1 302 Found\r\nLocation: https://wrong.invalid:{port}/sentinel\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()

    async with owned_server(tls=tls_context, response=redirect) as (port, received, sni):
        with pytest.raises(BadRequestError, match="could not be fetched"):
            await HTTPURLFetcher(
                timeout_seconds=2, max_bytes=100, allow_private_addresses=True
            ).fetch(f"https://report.invalid:{port}/report")
    assert len(received) == 1
    assert sni == ["report.invalid", "wrong.invalid"]


@pytest.mark.anyio
async def test_owned_local_server_rejected_outside_private_opt_in(monkeypatch):
    owned_dns(monkeypatch)
    async with owned_server() as (port, received, _):
        with pytest.raises(BadRequestError, match="private or local"):
            await HTTPURLFetcher(timeout_seconds=1, max_bytes=100).fetch(
                f"http://report.invalid:{port}/sentinel"
            )
    assert received == []
