"""Fetch a public http(s) URL without reaching this Mac or its network.

Shared by `web_fetch`, the Skills assistant's installer and the chat's click-to-load images.
- Redirects are followed by hand (at most MAX_REDIRECTS) and every hop's host is checked.
- Each hop resolves its host once, refuses it if any address is local or private, and then
  connects to that exact address (the Host header and TLS SNI/certificate check still use the
  name). A rebinding DNS server can't swap in 127.0.0.1 between the check and the connect.
- Proxies from the environment are ignored (they would connect by name again).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass

import httpx

MAX_REDIRECTS = 5
REDIRECTS = {301, 302, 303, 307, 308}
DEFAULT_PORT = {"http": 80, "https": 443}


class UnsafeURL(ValueError):
    """The URL (or a redirect) points somewhere web fetches may not go."""


@dataclass
class FetchResult:
    url: str  # the final URL (after redirects), by name
    status: int
    headers: httpx.Headers
    content: bytes
    truncated: bool

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


# Never public, whatever the running Python's `is_global` table says (it changes between versions):
# CGNAT / Tailscale (100.100.100.100 is its DNS), benchmarking, IETF protocol assignments, "this
# network", class E, the 6to4 relay anycast, documentation ranges, unique-local, link-local and
# site-local IPv6.
_NON_PUBLIC = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/96", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8", "100::/64", "2001:db8::/32",
))
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_global and not ip.is_multicast and not any(
        ip in n for n in _NON_PUBLIC if n.version == ip.version)


def is_public_ip(addr: str) -> bool:
    """True only for a globally routable unicast address. An IPv6 address that carries an IPv4 one
    is judged by that too: mapped (::ffff:a.b.c.d) and NAT64 (64:ff9b::a.b.c.d) must embed a public
    address; 6to4 (2002::/16) and Teredo (2001::/32) are refused outright."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return _is_public(ip.ipv4_mapped)
        if ip.sixtofour or ip.teredo:
            return False
        if ip in _NAT64 and not _is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)):
            return False
    return _is_public(ip)


async def _getaddrinfo(host: str, port: int) -> list[str]:
    """Every address `host` resolves to (tests replace this)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(i[4][0]) for i in infos]


async def resolve_public(host: str, port: int) -> str:
    """One public address for `host`; UnsafeURL when it is (or also resolves to) a local or private one."""
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        addrs = [host]
    except ValueError:
        try:
            addrs = await _getaddrinfo(host, port)
        except (socket.gaierror, UnicodeError) as e:
            raise UnsafeURL(f"Couldn't resolve {host}.") from e
    if not addrs or not all(is_public_ip(a) for a in addrs):
        raise UnsafeURL("That address is local or private.")
    return addrs[0].split("%", 1)[0]


async def safe_fetch(url: str, *, max_bytes: int, timeout: float = 20, user_agent: str = "GameDevWorkstation/0.1",
                     schemes: tuple[str, ...] = ("http", "https"), max_redirects: int = MAX_REDIRECTS,
                     truncate: bool = True, headers: dict[str, str] | None = None,
                     transport: httpx.AsyncBaseTransport | None = None) -> FetchResult:
    """GET a public URL. Bodies over `max_bytes` are cut (truncate=True) or refused (ValueError).
    Raises UnsafeURL for bad schemes and local/private hosts (first hop or any redirect),
    ValueError for too many redirects, and httpx.HTTPError for network failures."""
    try:
        current = httpx.URL(url.strip())
    except httpx.InvalidURL as e:
        raise UnsafeURL(f"Not a valid URL: {e}") from e
    only = " or ".join(schemes)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, trust_env=False,
                                 transport=transport) as client:
        for hop in range(max_redirects + 1):
            if current.scheme not in schemes or not current.host:
                raise UnsafeURL(f"Only {only} URLs." if hop == 0 else f"Redirected to a non-{only} URL; refused.")
            try:
                ip = await resolve_public(current.host, current.port or DEFAULT_PORT[current.scheme])
            except UnsafeURL as e:
                raise UnsafeURL(str(e) if hop == 0 else f"Redirected to a local or private address ({current.host}); "
                                "refused.") from e
            netloc = current.netloc.decode("ascii")
            target = current.copy_with(host=ip)
            ext = {"sni_hostname": current.host} if current.scheme == "https" else {}
            req_headers = {"User-Agent": user_agent, **(headers or {}), "Host": netloc}
            async with client.stream("GET", target, headers=req_headers, extensions=ext) as r:
                if r.status_code in REDIRECTS and r.headers.get("location"):
                    current = current.join(r.headers["location"])
                    continue
                chunks: list[bytes] = []
                size, cut = 0, False
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        if not truncate:
                            raise ValueError(f"{current} is larger than {max_bytes // 1000} KB")
                        chunks.append(chunk[: len(chunk) - (size - max_bytes)])
                        cut = True
                        break
                    chunks.append(chunk)
                return FetchResult(url=str(current), status=r.status_code, headers=r.headers,
                                   content=b"".join(chunks), truncated=cut)
    raise ValueError(f"More than {max_redirects} redirects.")
