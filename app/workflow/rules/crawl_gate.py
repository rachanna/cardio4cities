"""Crawl gate, pure steps (LLD-2 §9.1 steps 1-3). The I/O steps (resolve, robots
fetch) are run by the collector, which calls these rules on what it gets back."""

import ipaddress
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Step 1: tracking parameters dropped during canonicalisation
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset(
    {"gclid", "fbclid", "msclkid", "dclid", "yclid", "mc_cid", "mc_eid", "_ga", "_gl", "igshid"}
)
DEFAULT_PORTS = {"http": 80, "https": 443}


def canonicalise(url: str) -> str | None:
    """Lower-case scheme and host, drop the fragment and tracking parameters,
    drop a default port. None when the URL is not usable."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".").lower()
    if not scheme or not host:
        return None
    if host.startswith("[") or ":" in host:
        host = f"[{host.strip('[]')}]"
    netloc = host if port in (None, DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith(TRACKING_PREFIXES) and k.lower() not in TRACKING_PARAMS
        ]
    )
    return urlunsplit((scheme, netloc, parts.path or "/", query, ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def effective_port(url: str) -> int | None:
    parts = urlsplit(url)
    return parts.port or DEFAULT_PORTS.get(parts.scheme)


def check_scheme_and_port(url: str, allowed_ports: Iterable[int]) -> str | None:
    """Step 2: None when acceptable, else the reason."""
    parts = urlsplit(url)
    if parts.scheme not in DEFAULT_PORTS:
        return f"unsupported scheme {parts.scheme!r}"
    port = effective_port(url)
    if port not in set(allowed_ports):
        return f"unsupported port {port}"
    return None


def is_public_address(address: str) -> bool:
    """Step 3: only globally routable unicast addresses. Refuses private, loopback,
    link-local (including 169.254.169.254 metadata), shared (100.64/10), multicast,
    reserved and documentation ranges, and IPv4-mapped forms of any of them."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def literal_address(host: str) -> str | None:
    """The address itself when the host is an IP literal, so it is checked, never resolved."""
    try:
        return str(ipaddress.ip_address(host.strip("[]").split("%")[0]))
    except ValueError:
        return None


def check_addresses(addresses: Iterable[str]) -> str | None:
    """Every resolved address must be public; None when they all are."""
    found = list(addresses)
    if not found:
        return "host does not resolve"
    private = [a for a in found if not is_public_address(a)]
    if private:
        return f"resolves to a non-public address ({private[0]})"
    return None
