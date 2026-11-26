"""Public HTTP access with DNS/IP and redirect checks to limit SSRF."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit


class UnsafeURLError(ValueError):
    pass


def validate_http_url(url: str) -> tuple[str, int, str, str]:
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii")
        port = parts.port or (443 if scheme == "https" else 80)
    except (ValueError, UnicodeError) as exc:
        raise UnsafeURLError("URL tidak valid.") from exc
    if scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise UnsafeURLError("Gunakan URL HTTP/HTTPS publik tanpa kredensial.")
    if port not in {80, 443}:
        raise UnsafeURLError("Port URL tidak diizinkan.")
    path = parts.path or "/"
    request_target = urlunsplit(("", "", path, parts.query, ""))
    return scheme, port, host, request_target


def validate_public_url(url: str) -> tuple[str, int, list[str], str]:
    scheme, port, host, request_target = validate_http_url(url)
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        addresses = [str(literal)]
    except ValueError:
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        except OSError as exc:
            raise UnsafeURLError("Host sumber tidak dapat ditemukan.") from exc
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise UnsafeURLError("Alamat privat atau jaringan internal tidak diizinkan.")
    return scheme, port, addresses, request_target


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, target_ip: str, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self.target_ip = target_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self.target_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, target_ip: str, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.target_ip = target_ip

    def connect(self) -> None:
        raw = socket.create_connection((self.target_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def open_public_response(url: str, method: str = "GET", headers: dict[str, str] | None = None):
    """Open a response pinned to a validated public IP; validate every redirect."""
    current = url.strip()
    request_headers = {"User-Agent": "VideoToTranscript/1.0 (local downloader)", **(headers or {})}
    for _ in range(6):
        scheme, port, addresses, target = validate_public_url(current)
        parts = urlsplit(current)
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        host_header = host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"
        request_headers["Host"] = host_header
        last_error: OSError | None = None
        connection = None
        response = None
        for address in addresses:
            try:
                cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
                connection = cls(parts.hostname or "", port, address, 20)
                connection.request(method, target, headers=request_headers)
                response = connection.getresponse()
                break
            except OSError as exc:
                last_error = exc
                if connection:
                    connection.close()
        if response is None or connection is None:
            raise OSError("Tidak dapat terhubung ke sumber video.") from last_error
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            response.close()
            connection.close()
            if not location:
                raise OSError("Sumber mengirim redirect tanpa tujuan.")
            current = urljoin(current, location)
            continue
        return connection, response, current
    raise OSError("Terlalu banyak redirect saat mengakses sumber.")
