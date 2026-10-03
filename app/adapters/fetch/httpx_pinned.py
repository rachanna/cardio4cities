"""Pinned-IP fetcher (LLD-2 §9.3, AT-23; httpx chosen over httpx2 in BD-07).

The connection is dialled to the address the crawl gate checked, never to a fresh DNS
answer, so DNS rebinding cannot redirect a request to a private address. The hostname
is still used for the Host header, TLS SNI and certificate verification. One request,
no redirects: the collector re-gates every hop.

Certificates (BD-15, BD-16): verification is always on. A failure is reported with its
cause (expired, self-signed, host name mismatch, issuer missing). When the issuer is
missing, the certificate is read on a separate connection that sends no request, and its
issuer (AIA) URLs are reported so the collector can fetch the missing intermediate
through the gate. `complete_chain` then verifies the whole chain in code, with every
fetched certificate an untrusted intermediate, against the trusted roots and the host
name, and returns only the intermediates on that verified chain. Only those are ever
added to a TLS context, as chain-building certificates: self-issued and non-CA
certificates are refused there too, and partial chains stay refused, so OpenSSL verifies
the connection to a trusted root again.
"""

import asyncio
import contextlib
import ipaddress
import socket
import ssl
from collections.abc import Callable, Iterable
from typing import Any

import certifi
import httpcore
import httpx
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from cryptography.x509.oid import AuthorityInformationAccessOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from app.ports.errors import FetchError, TLSCertificateError
from app.ports.fetch import FetchLimits, FetchResult
from app.settings import Settings

Dial = Callable[[str, int], tuple[str, int]]
Resolver = Callable[[str], "asyncio.Future[list[str]] | Any"]
ContextFactory = Callable[[], ssl.SSLContext]
RootsFactory = Callable[[], list[x509.Certificate]]

# OpenSSL verify codes -> cause (TLSCertificateError)
VERIFY_CAUSES = {
    2: "issuer_missing",  # unable to get issuer certificate
    10: "expired",
    18: "self_signed",  # the server's own certificate is self-signed
    19: "self_signed",  # a self-signed certificate in the chain
    20: "issuer_missing",  # unable to get local issuer certificate
    21: "issuer_missing",  # unable to verify the first certificate
    62: "hostname_mismatch",
}


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Ignores the host httpcore asks for and dials the pinned address."""

    def __init__(self, pinned_ip: str, dial: Dial | None) -> None:
        self._ip, self._dial = pinned_ip, dial
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        target, target_port = self._dial(self._ip, port) if self._dial else (self._ip, port)
        return await self._inner.connect_tcp(
            target, target_port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.AsyncNetworkStream:
        raise FetchError("unix sockets are never used")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, pinned_ip: str, ssl_context: ssl.SSLContext, dial: Dial | None) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            network_backend=_PinnedBackend(pinned_ip, dial),
            max_connections=1,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        core_response = await self._pool.handle_async_request(core_request)
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_Stream(core_response),
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class _Stream(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self._response = response

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        async for part in self._response.aiter_stream():
            yield part

    async def aclose(self) -> None:
        await self._response.aclose()


async def _getaddrinfo(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted({str(info[4][0]) for info in infos})


class PinnedFetcher:
    """FetchPort. `resolver` and `dial` exist for tests: a fake DNS and a route from
    fictional public addresses to a local test server. Production uses neither."""

    def __init__(
        self,
        resolver: Callable[[str], Any] | None = None,
        dial: Dial | None = None,
        context_factory: ContextFactory = ssl.create_default_context,
        trusted_roots: RootsFactory | None = None,
    ) -> None:
        self._resolver = resolver or _getaddrinfo
        self._dial = dial
        self._contexts = context_factory
        self._ssl = context_factory()
        self._roots_factory = trusted_roots or _certifi_roots
        self._roots: list[x509.Certificate] | None = None

    def _context(self, intermediates: tuple[bytes, ...]) -> ssl.SSLContext:
        """The default context, or a fresh one that also knows the given intermediates,
        for chain building only. Self-issued and non-CA certificates are never added, and
        partial chains stay refused, so the chain must still end at a trusted root."""
        pems = [
            c.public_bytes(Encoding.PEM).decode("ascii")
            for raw in intermediates
            for c in _certificates(raw)
            if _is_intermediate(c)
        ]
        if not pems:
            return self._ssl
        context = self._contexts()
        context.load_verify_locations(cadata="".join(pems))
        context.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
        return context

    async def complete_chain(
        self, url: str, pinned_ip: str, limits: FetchLimits, issuers: tuple[bytes, ...]
    ) -> tuple[bytes, ...]:
        """Verify the server's certificate chain in code: the server's own certificate,
        `issuers` (fetched from its AIA URLs) as untrusted intermediates, the trusted roots
        and the host name. Returns the DER intermediates of the verified chain. Raises
        TLSCertificateError when no chain to a trusted root exists."""
        leaf_der = await self._peer_certificate(url, pinned_ip, limits)
        if not leaf_der:
            raise TLSCertificateError("issuer_missing")
        try:
            leaf = x509.load_der_x509_certificate(leaf_der)
        except ValueError as exc:
            raise TLSCertificateError("untrusted") from exc
        candidates = [c for raw in issuers for c in _certificates(raw)]
        if self._roots is None:
            self._roots = self._roots_factory()
        host = httpx.URL(url).host
        try:
            subject: x509.verification.Subject = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            subject = x509.DNSName(host)
        verifier = PolicyBuilder().store(Store(self._roots)).build_server_verifier(subject)
        try:
            chain = verifier.verify(leaf, candidates)
        except VerificationError as exc:
            raise TLSCertificateError("issuer_untrusted") from exc
        return tuple(c.public_bytes(Encoding.DER) for c in chain[1:-1])

    async def resolve(self, host: str) -> list[str]:
        return list(await self._resolver(host))

    async def fetch(
        self,
        url: str,
        pinned_ip: str,
        limits: FetchLimits,
        intermediates: tuple[bytes, ...] = (),
    ) -> FetchResult:
        try:
            return await self._fetch(url, pinned_ip, limits, intermediates)
        except FetchError as exc:
            verify = _verify_error(exc)
            if verify is None:
                raise
            cause = VERIFY_CAUSES.get(verify.verify_code, "untrusted")
            urls: tuple[str, ...] = ()
            if cause == "issuer_missing" and not intermediates:
                urls = await self._issuer_urls(url, pinned_ip, limits)
            raise TLSCertificateError(cause, urls) from exc

    async def _issuer_urls(self, url: str, pinned_ip: str, limits: FetchLimits) -> tuple[str, ...]:
        """The CA Issuers (AIA) URLs of the server's certificate. Nothing read is trusted."""
        der = await self._peer_certificate(url, pinned_ip, limits)
        return _aia_urls(der) if der else ()

    async def _peer_certificate(self, url: str, pinned_ip: str, limits: FetchLimits) -> bytes:
        """The server's certificate, read without verifying it on a connection that sends
        nothing. Used only to find its issuer and to verify its chain in code."""
        parsed = httpx.URL(url)
        port = parsed.port or 443
        target, target_port = self._dial(pinned_ip, port) if self._dial else (pinned_ip, port)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    target, target_port, ssl=context, server_hostname=parsed.host
                ),
                limits.connect_timeout_s,
            )
        except (OSError, TimeoutError, ssl.SSLError):
            return b""
        try:
            der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        finally:
            writer.close()
            with contextlib.suppress(OSError, ssl.SSLError):
                await writer.wait_closed()
        return der or b""

    async def _fetch(
        self, url: str, pinned_ip: str, limits: FetchLimits, intermediates: tuple[bytes, ...]
    ) -> FetchResult:
        timeout = httpx.Timeout(
            limits.read_timeout_s, connect=limits.connect_timeout_s, pool=limits.connect_timeout_s
        )
        headers = {
            "user-agent": limits.user_agent,
            "accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.1",
        }
        transport = _PinnedTransport(pinned_ip, self._context(intermediates), self._dial)
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport, timeout=timeout, follow_redirects=False, headers=headers
                ) as client,
                client.stream("GET", url) as response,
            ):
                body = bytearray()
                truncated = False
                async for part in response.aiter_raw():
                    body += part
                    if len(body) > limits.max_bytes:
                        truncated = True
                        break
                content = b"" if truncated else _decode(bytes(body), response.headers)
                return FetchResult(
                    url=url,
                    status=response.status_code,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    content=content,
                    content_type=response.headers.get("content-type"),
                    truncated=truncated,
                )
        # The custom transport bypasses httpx's own error mapping, so httpcore errors are
        # caught here too; every network failure surfaces as FetchError, never a crash.
        except (httpx.TimeoutException, httpcore.TimeoutException) as exc:
            raise FetchError(f"timeout: {type(exc).__name__}", timeout=True) from exc
        except (
            httpx.HTTPError,
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.UnsupportedProtocol,
            OSError,
            ssl.SSLError,
        ) as exc:
            raise FetchError(f"network error: {type(exc).__name__}") from exc


def _verify_error(exc: BaseException) -> ssl.SSLCertVerificationError | None:
    """The certificate verification error behind a fetch failure, if that was the cause."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return current
        for arg in getattr(current, "args", ()):
            if isinstance(arg, ssl.SSLCertVerificationError):
                return arg
        current = current.__cause__ or current.__context__
    return None


def _aia_urls(der: bytes) -> tuple[str, ...]:
    try:
        cert = x509.load_der_x509_certificate(der)
        aia = cert.extensions.get_extension_for_class(x509.AuthorityInformationAccess).value
    except (ValueError, x509.ExtensionNotFound):
        return ()
    return tuple(
        str(d.access_location.value)
        for d in aia
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS
        and isinstance(d.access_location, x509.UniformResourceIdentifier)
    )


def _certifi_roots() -> list[x509.Certificate]:
    """The trusted roots for verifying a completed chain: the Mozilla root store."""
    with open(certifi.where(), "rb") as bundle:
        return x509.load_pem_x509_certificates(bundle.read())


def _is_intermediate(cert: x509.Certificate) -> bool:
    """A certificate that may only build a chain: a CA that is not self-issued."""
    if cert.subject == cert.issuer:
        return False
    try:
        constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    except x509.ExtensionNotFound:
        return False
    return constraints.ca


def _certificates(raw: bytes) -> list[x509.Certificate]:
    """An issuer certificate as served at an AIA URL: DER, PEM or PKCS#7. Anything else
    gives nothing, and verification then fails as before."""
    loaders: tuple[Callable[[bytes], list[x509.Certificate]], ...] = (
        lambda b: [x509.load_der_x509_certificate(b)],
        x509.load_pem_x509_certificates,
        pkcs7.load_der_pkcs7_certificates,
        pkcs7.load_pem_pkcs7_certificates,
    )
    for load in loaders:
        try:
            certs = load(raw)
        except ValueError:
            continue
        return list(certs)
    return []


def _decode(raw: bytes, headers: httpx.Headers) -> bytes:
    """Undo Content-Encoding (gzip, deflate, br) after the size check on the raw bytes."""
    encoding = headers.get("content-encoding", "").lower()
    if not encoding or encoding == "identity" or not raw:
        return raw
    try:
        response = httpx.Response(200, headers={"content-encoding": encoding}, content=raw)
        return response.content
    except httpx.DecodingError as exc:
        raise FetchError("could not decode the response body") from exc


def make(settings: Settings) -> PinnedFetcher:
    return PinnedFetcher()
