"""Collection: crawl gate, fetch and parse for one URL (LLD-2 §9; AT-04, AT-05, AT-06, AT-23).

The gate decides before any content request. Content enters the system only through
`Collector.collect`: search snippets are never fetched or stored (AT-06). Every
redirect hop is gated again, and every request dials the address the gate checked.
Persisting sources, decisions and snapshots is the caller's job (the workflow node).
"""

import asyncio
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

from app.domain.vocab import CrawlOutcome, ParseOutcome, SourceKind
from app.ports.errors import FetchError, TLSCertificateError
from app.ports.fetch import FetchLimits, FetchPort, FetchResult
from app.ports.parse import ParsedDocument, ParserPort
from app.ports.robots import RobotsParser
from app.workflow.rules import content_usage
from app.workflow.rules.crawl_gate import (
    canonicalise,
    check_addresses,
    check_scheme_and_port,
    host_of,
    literal_address,
    origin_of,
)
from app.workflow.rules.robots import (
    ROBOTS_MAX_BYTES,
    ROBOTS_MAX_REDIRECTS,
    Availability,
    match_length,
    parse_groups,
    path_matches,
    robots_availability,
    select_rules,
)

MAX_REDIRECTS = 5  # LLD-2 §9.3
RETRY_AFTER_MAX_S = 10.0  # LLD-2 §9.3: honour Retry-After up to 10 s, retry once
MAX_ISSUER_URLS = 2  # AIA URLs tried per certificate (BD-15)
CERTIFICATE_MAX_BYTES = 64 * 1024  # an issuer certificate, DER, PEM or PKCS#7 (BD-15)
MIN_READABLE_CHARS = 200  # LLD-2 §9.4
ALLOWED_TYPES = {
    "text/html": SourceKind.WEB_HTML,
    "application/xhtml+xml": SourceKind.WEB_HTML,
    "text/plain": SourceKind.WEB_HTML,
    "application/pdf": SourceKind.WEB_PDF,
}
PAYWALL_STATUSES = frozenset({401, 402, 403})
# Generic types some servers send for PDFs (spike S-5): sniffed by the PDF signature only
GENERIC_TYPES = frozenset(
    {"", "application/octet-stream", "binary/octet-stream", "application/x-download"}
)
_PASSWORD_FIELD = re.compile(rb"<input[^>]+type\s*=\s*['\"]?password", re.IGNORECASE)

FetchKind = Literal["fetch", "robots", "certificate"]
Outcome = Literal["fetched", "not_fetched", "http_error"]


class FetchBudget(Protocol):
    async def reserve(self, kind: FetchKind) -> None:
        """Called before every request; raises when the budget is spent (LLD-2 §12)."""
        ...

    def time_left_s(self) -> float:
        """Seconds left on the run's wall clock: no spacing wait may go past it."""
        ...


class RateLimitedError(FetchError):
    """The wait a site's spacing needs would run past the run's time left (BD-20)."""


@dataclass(frozen=True)
class CollectionParams:
    user_agent: str  # app.user_agent
    allowed_ports: tuple[int, ...]  # fetch.allowed_ports
    min_interval_s: float  # fetch.min_interval_s
    concurrency: int  # fetch.concurrency
    max_bytes: int  # fetch.max_bytes
    connect_timeout_s: float
    read_timeout_s: float
    robots_timeout_s: float  # fetch.robots_timeout_s
    crawl_delay_cap_s: float  # fetch.crawl_delay_cap_s (BD-20)


@dataclass(frozen=True)
class GateDecision:
    url: str
    domain: str
    outcome: CrawlOutcome
    reason: str
    rule: str | None = None
    robots_http_status: int | None = None
    pinned_ip: str | None = None
    crawl_delay: float | None = None
    usage_preferences: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Collected:
    requested_url: str
    decisions: tuple[GateDecision, ...]  # one per hop, in order
    outcome: Outcome
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    kind: SourceKind | None = None
    raw: bytes = b""  # kept for the snapshot only when parsed or unreadable
    document: ParsedDocument | None = None
    parse_outcome: ParseOutcome | None = None

    @property
    def final_decision(self) -> GateDecision:
        return self.decisions[-1]


@dataclass
class _Robots:
    availability: Availability
    status: int | None
    text: str = ""
    detail: str = ""  # why robots.txt could not be reached, e.g. a certificate cause


@dataclass(frozen=True)
class ApiFetched:
    """One official API call: every gate decision (one per hop) and the 2xx response."""

    decisions: tuple[GateDecision, ...]
    result: FetchResult | None
    http_status: int | None = None


class Collector:
    def __init__(
        self,
        fetcher: FetchPort,
        robots_parser: RobotsParser,
        parser: ParserPort,
        budget: FetchBudget,
        params: CollectionParams,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fetcher, self._robots_parser, self._parser = fetcher, robots_parser, parser
        self._budget, self._params = budget, params
        self._clock, self._sleep = clock, sleep
        self._robots: dict[str, _Robots] = {}  # per origin, for the run
        self._robots_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Certificates (BD-15): issuer certificates fetched from AIA URLs, and the chain
        # completed for each host, so every later request to it verifies at once.
        self._issuers: dict[str, bytes | str] = {}  # AIA URL -> certificate, or why not
        self._issuer_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # host -> intermediates of its verified chain (BD-16), or why it has none
        self._chains: dict[str, tuple[bytes, ...] | str] = {}
        self._chain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._domain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}
        self._global = asyncio.Semaphore(params.concurrency)

    # --- gate (§9.1) --------------------------------------------------------------

    async def _address(self, url: str) -> GateDecision:
        """Steps 1-3 of the gate (§9.1): a usable URL, an allowed scheme and port, and
        public addresses only. Allowed decisions carry the address to pin."""
        canonical = canonicalise(url)
        if canonical is None:
            return GateDecision(url, "", CrawlOutcome.BLOCKED_PRIVATE_ADDRESS, "not a usable URL")
        domain = host_of(canonical)
        problem = check_scheme_and_port(canonical, self._params.allowed_ports)
        if problem:
            return GateDecision(canonical, domain, CrawlOutcome.BLOCKED_PRIVATE_ADDRESS, problem)
        literal = literal_address(domain)
        addresses = [literal] if literal else await self._fetcher.resolve(domain)
        if not addresses:
            return GateDecision(
                canonical, domain, CrawlOutcome.UNREACHABLE_NETWORK, "host does not resolve"
            )
        problem = check_addresses(addresses)
        if problem:
            return GateDecision(canonical, domain, CrawlOutcome.BLOCKED_PRIVATE_ADDRESS, problem)
        return GateDecision(canonical, domain, CrawlOutcome.ALLOWED, "", None, None, addresses[0])

    async def gate(self, url: str) -> GateDecision:
        checked = await self._address(url)
        if checked.outcome is not CrawlOutcome.ALLOWED or checked.pinned_ip is None:
            return checked
        canonical, domain, pinned = checked.url, checked.domain, checked.pinned_ip
        robots = await self._robots_for(canonical, pinned)
        base = GateDecision(
            canonical, domain, CrawlOutcome.ALLOWED, "", None, robots.status, pinned
        )
        if robots.availability == "unreachable_server_error":
            answer = (
                "asked us to slow down (429)" if robots.status == 429 else "returned a server error"
            )
            return replace(
                base,
                outcome=CrawlOutcome.UNREACHABLE_SERVER_ERROR,
                reason=f"robots.txt {answer}: the whole site is treated as disallowed",
            )
        if robots.availability == "unreachable_network":
            cause = f" ({robots.detail})" if robots.detail else ""
            return replace(
                base,
                outcome=CrawlOutcome.UNREACHABLE_NETWORK,
                reason=f"robots.txt could not be reached{cause}: the whole site is treated"
                " as disallowed",
            )
        if robots.availability == "unavailable":
            return replace(base, reason="no robots.txt (4xx): no restrictions apply")
        rules = self._robots_parser.parse(robots.text)
        ua = self._params.user_agent
        if not rules.can_fetch(canonical, ua):
            return replace(
                base,
                outcome=CrawlOutcome.BLOCKED_ROBOTS,
                rule=_disallow_line(robots.text, ua, canonical),
                reason="robots.txt disallows this path for our user agent",
            )
        usage = content_usage.from_robots(parse_groups(robots.text), ua, canonical)
        if usage.blocked:
            return replace(
                base,
                outcome=CrawlOutcome.BLOCKED_CONTENT_USAGE,
                rule=usage.rule,
                reason="robots.txt opts this content out of use by AI systems",
                usage_preferences=usage.preferences,
            )
        delay = rules.crawl_delay(ua)
        if delay is not None and delay > self._params.crawl_delay_cap_s:
            return replace(
                base,
                outcome=CrawlOutcome.RATE_LIMITED,
                rule=f"Crawl-delay: {delay:g}",
                reason=f"robots.txt asks for {delay:g} s between requests, longer than the"
                f" {self._params.crawl_delay_cap_s:g} s a run can wait",
            )
        return replace(
            base,
            reason="allowed by robots.txt",
            crawl_delay=delay,
            rule=usage.rule,
            usage_preferences=usage.preferences,
        )

    async def _robots_for(self, url: str, pinned: str) -> _Robots:
        """One robots.txt request per origin per run, even when slots ask at once."""
        origin = origin_of(url)
        async with self._robots_locks[origin]:
            if origin not in self._robots:
                self._robots[origin] = await self._fetch_robots(origin, pinned)
        return self._robots[origin]

    async def _fetch_robots(self, origin: str, pinned: str) -> _Robots:
        limits = FetchLimits(
            max_bytes=ROBOTS_MAX_BYTES,
            connect_timeout_s=self._params.robots_timeout_s,
            read_timeout_s=self._params.robots_timeout_s,
            user_agent=self._params.user_agent,
            keep_partial=True,
        )
        url, ip = f"{origin}/robots.txt", pinned
        for _ in range(ROBOTS_MAX_REDIRECTS + 1):
            try:
                result = await self._request(url, ip, limits, "robots", crawl_delay=None)
            except FetchError as exc:
                return _Robots("unreachable_network", None, detail=str(exc))
            location = result.headers.get("location")
            if 300 <= result.status < 400 and location:
                target = canonicalise(urljoin(url, location))
                if target is None or check_scheme_and_port(target, self._params.allowed_ports):
                    # Not "no robots.txt": a file we cannot read is unreachable (BD-20)
                    return _Robots(
                        "unreachable_network",
                        result.status,
                        detail="it redirects where we never dial",
                    )
                literal = literal_address(host_of(target))
                addresses = [literal] if literal else await self._fetcher.resolve(host_of(target))
                if check_addresses(addresses):  # never follow robots.txt to a private address
                    return _Robots("unreachable_network", result.status)
                url, ip = target, addresses[0]
                continue
            availability = robots_availability(result.status)
            # Only the first 500 KiB is parsed (RFC 9309 §2.5): a cut-off file is still used.
            # A byte order mark is dropped, or it would hide the first group (BD-20).
            text = result.content.decode("utf-8-sig", errors="replace") if result.content else ""
            return _Robots(availability, result.status, text)
        return _Robots("unavailable", None)  # too many redirects: treated as unavailable

    # --- requests (§9.3) ------------------------------------------------------------

    async def _request(
        self, url: str, ip: str, limits: FetchLimits, kind: FetchKind, crawl_delay: float | None
    ) -> FetchResult:
        """`_send`, completing a certificate chain the server left incomplete (BD-15, BD-16):
        the certificate's own issuer (AIA) URLs are gated like any request (public address,
        pinned IP, budget, spacing) and the issuer certificates fetched; the fetcher then
        verifies the whole chain in code against the trusted roots, with the fetched
        certificates as untrusted intermediates, and only that verified chain is used for
        the request. Verification itself never relaxes: expired, self-signed and mismatched
        certificates, and chains that end at no trusted root, stay refused with their cause
        in the decision."""
        host = host_of(url)
        chain = self._chains.get(host)
        if isinstance(chain, str):
            raise FetchError(chain)  # this host's chain was already found wanting
        try:
            return await self._send(url, ip, limits, kind, crawl_delay, chain or ())
        except TLSCertificateError as exc:
            if exc.cause != "issuer_missing" or chain is not None or not exc.issuer_urls:
                raise
            verified = await self._complete_chain(host, url, ip, exc)
            return await self._send(url, ip, limits, kind, crawl_delay, verified)

    async def _complete_chain(
        self, host: str, url: str, ip: str, exc: TLSCertificateError
    ) -> tuple[bytes, ...]:
        """The verified intermediates for `host`, worked out once per host per run."""
        async with self._chain_locks[host]:
            if host not in self._chains:
                self._chains[host] = await self._verified_chain(url, ip, exc)
        chain = self._chains[host]
        if isinstance(chain, str):
            raise FetchError(chain) from exc
        return chain

    async def _verified_chain(
        self, url: str, ip: str, exc: TLSCertificateError
    ) -> tuple[bytes, ...] | str:
        found, why = await self._issuer_certificates(exc.issuer_urls)
        if not found:
            return f"{exc}; {why}"
        await self._budget.reserve("certificate")  # the handshake that reads the chain
        try:
            async with self._global:
                verified = await self._fetcher.complete_chain(url, ip, self._limits(), found)
        except FetchError as failure:
            return f"{exc}; {failure}"
        return verified or f"{exc}; its issuer certificate did not complete the chain"

    async def _issuer_certificates(self, urls: tuple[str, ...]) -> tuple[tuple[bytes, ...], str]:
        """The issuer certificates behind `urls`, or why none could be had."""
        found: list[bytes] = []
        why = "its issuer certificate could not be fetched"
        for url in urls[:MAX_ISSUER_URLS]:
            async with self._issuer_locks[url]:  # one download per URL, even across slots
                if url not in self._issuers:
                    self._issuers[url] = await self._issuer(url)
            got = self._issuers[url]
            if isinstance(got, bytes):
                found.append(got)
            else:
                why = got
        return tuple(found), why

    async def _issuer(self, url: str) -> bytes | str:
        checked = await self._address(url)
        if checked.outcome is not CrawlOutcome.ALLOWED or checked.pinned_ip is None:
            return f"its issuer certificate URL was refused ({checked.reason})"
        limits = FetchLimits(
            max_bytes=CERTIFICATE_MAX_BYTES,
            connect_timeout_s=self._params.connect_timeout_s,
            read_timeout_s=self._params.read_timeout_s,
            user_agent=self._params.user_agent,
        )
        try:
            result = await self._send(checked.url, checked.pinned_ip, limits, "certificate", None)
        except FetchError as exc:
            return f"its issuer certificate could not be fetched ({exc})"
        if result.status != 200 or not result.content or result.truncated:
            return f"its issuer certificate could not be fetched (HTTP {result.status})"
        return result.content

    async def _send(
        self,
        url: str,
        ip: str,
        limits: FetchLimits,
        kind: FetchKind,
        crawl_delay: float | None,
        intermediates: tuple[bytes, ...] = (),
    ) -> FetchResult:
        """One request, spaced per domain at max(crawl-delay, min interval), one at a
        time per domain, within the global concurrency limit (BD-20): the budget is
        reserved before any wait, a wait past the run's time left is refused, and only
        the domain lock is held while waiting, so one slow site never holds the global
        permits other sites need."""
        domain = host_of(url)
        spacing = max(crawl_delay or 0.0, self._params.min_interval_s)
        async with self._domain_locks[domain]:
            wait = 0.0
            if domain in self._last_request:
                wait = max(self._last_request[domain] + spacing - self._clock(), 0.0)
            if wait > self._budget.time_left_s():
                raise RateLimitedError(
                    f"the site's spacing needs {wait:.0f} s more, past the run's time left"
                )
            await self._budget.reserve(kind)
            if wait > 0:
                await self._sleep(wait)
            try:
                async with self._global:
                    return await self._fetcher.fetch(url, ip, limits, intermediates)
            finally:
                self._last_request[domain] = self._clock()

    def _limits(self) -> FetchLimits:
        p = self._params
        return FetchLimits(
            max_bytes=p.max_bytes,
            connect_timeout_s=p.connect_timeout_s,
            read_timeout_s=p.read_timeout_s,
            user_agent=p.user_agent,
        )

    # --- official APIs (Wave 0, BD-13) -------------------------------------------------

    async def gate_api(self, url: str, provider: str) -> GateDecision:
        """An official API used under its published terms: the same address checks and
        pinning as any page; robots.txt does not govern it, its terms do."""
        checked = await self._address(url)
        if checked.outcome is not CrawlOutcome.ALLOWED:
            return replace(checked, rule=f"api_terms:{provider}")
        return replace(
            checked,
            rule=f"api_terms:{provider}",
            reason=f"official {provider} API, used under its published terms",
        )

    async def fetch_api(self, url: str, provider: str) -> ApiFetched:
        """One API call, following up to five redirects, each gated again. A block is
        recorded, never worked around: 401-403 as login or paywall, 429 as rate limited."""
        decisions: list[GateDecision] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            decision = await self.gate_api(current, provider)
            decisions.append(decision)
            if decision.outcome is not CrawlOutcome.ALLOWED or decision.pinned_ip is None:
                return ApiFetched(tuple(decisions), None)
            try:
                result = await self._fetch_with_retry(decision)
            except FetchError as exc:
                decisions[-1] = _failed(decision, exc)
                return ApiFetched(tuple(decisions), None)
            if result is None:
                decisions[-1] = replace(
                    decision,
                    outcome=CrawlOutcome.RATE_LIMITED,
                    reason="the API asked us to slow down (429) for longer than we wait",
                )
                return ApiFetched(tuple(decisions), None)
            location = result.headers.get("location")
            if 300 <= result.status < 400 and location:
                current = urljoin(decision.url, location)
                continue
            if result.status in PAYWALL_STATUSES:
                decisions[-1] = replace(
                    decision,
                    outcome=CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL,
                    reason=f"the API refused the request ({result.status})",
                )
                return ApiFetched(tuple(decisions), None)
            if result.status >= 500:
                decisions[-1] = replace(
                    decision,
                    outcome=CrawlOutcome.UNREACHABLE_SERVER_ERROR,
                    reason=f"the API returned a server error ({result.status})",
                )
                return ApiFetched(tuple(decisions), None)
            if not 200 <= result.status < 300 or result.truncated:
                return ApiFetched(tuple(decisions), None, result.status)
            return ApiFetched(tuple(decisions), result, result.status)
        return ApiFetched(tuple(decisions), None)

    # --- collect ----------------------------------------------------------------------

    async def collect(self, url: str, table_keywords: list[str]) -> Collected:
        """Gate, fetch and parse `url`, following up to five redirects, each gated again."""
        decisions: list[GateDecision] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            decision = await self.gate(current)
            decisions.append(decision)
            if decision.outcome is not CrawlOutcome.ALLOWED or decision.pinned_ip is None:
                return Collected(url, tuple(decisions), "not_fetched")
            try:
                result = await self._fetch_with_retry(decision)
            except FetchError as exc:
                decisions[-1] = _failed(decision, exc)
                return Collected(url, tuple(decisions), "not_fetched")
            if result is None:
                decisions[-1] = replace(
                    decision,
                    outcome=CrawlOutcome.RATE_LIMITED,
                    reason="the site asked us to slow down (429) for longer than we wait",
                )
                return Collected(url, tuple(decisions), "not_fetched")
            location = result.headers.get("location")
            if 300 <= result.status < 400 and location:
                current = urljoin(decision.url, location)
                continue
            return self._finish(url, decisions, result, table_keywords)
        return Collected(url, tuple(decisions), "http_error", http_status=None)

    async def _fetch_with_retry(self, decision: GateDecision) -> FetchResult | None:
        pinned = decision.pinned_ip
        if pinned is None:  # an allowed decision always carries the checked address
            raise FetchError("no checked address to dial")
        for attempt in range(2):
            result = await self._request(
                decision.url, pinned, self._limits(), "fetch", decision.crawl_delay
            )
            if result.status != 429:
                return result
            retry_after = _retry_after(result.headers.get("retry-after"))
            if attempt == 1 or retry_after is None or retry_after > RETRY_AFTER_MAX_S:
                return None
            await self._sleep(retry_after)
        return None

    def _finish(
        self,
        url: str,
        decisions: list[GateDecision],
        result: FetchResult,
        keywords: list[str],
    ) -> Collected:
        decision = decisions[-1]

        def blocked(outcome: CrawlOutcome, reason: str, rule: str | None = None) -> Collected:
            decisions[-1] = replace(decision, outcome=outcome, reason=reason, rule=rule)
            return Collected(url, tuple(decisions), "not_fetched", http_status=result.status)

        if result.status in PAYWALL_STATUSES:
            return blocked(
                CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL,
                f"the page requires a login or payment ({result.status}); body discarded unread",
            )
        usage = content_usage.from_header(result.headers)
        if usage.blocked:
            return blocked(
                CrawlOutcome.BLOCKED_CONTENT_USAGE,
                "the response opts its content out of use by AI systems; body discarded unread",
                usage.rule,
            )
        common = {
            "final_url": decision.url,
            "http_status": result.status,
            "content_type": result.content_type,
        }
        if not 200 <= result.status < 300:
            return Collected(url, tuple(decisions), "http_error", **common)  # type: ignore[arg-type]
        mime = (result.content_type or "").split(";")[0].strip().lower()
        if mime in GENERIC_TYPES and result.content.startswith(b"%PDF-"):
            mime = "application/pdf"
        kind = ALLOWED_TYPES.get(mime)
        if result.truncated:
            return Collected(url, tuple(decisions), "fetched", kind=kind,
                             parse_outcome=ParseOutcome.TOO_LARGE, **common)  # type: ignore[arg-type]  # fmt: skip
        if kind is None:
            return Collected(url, tuple(decisions), "fetched",
                             parse_outcome=ParseOutcome.UNSUPPORTED_TYPE, **common)  # type: ignore[arg-type]  # fmt: skip
        if mime == "application/pdf":
            document = self._parser.parse_pdf(result.content, keywords)
        elif mime == "text/plain":
            document = ParsedDocument(text=result.content.decode("utf-8", errors="replace"))
        else:
            document = self._parser.parse_html(result.content, decision.url)
        readable = len(document.text.strip()) >= MIN_READABLE_CHARS
        if kind is SourceKind.WEB_HTML and not readable and _PASSWORD_FIELD.search(result.content):
            return blocked(
                CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL,
                "the page is a login form with almost no text; body discarded",
            )
        return Collected(
            url,
            tuple(decisions),
            "fetched",
            kind=kind,
            raw=result.content,
            document=document,
            parse_outcome=ParseOutcome.PARSED if readable else ParseOutcome.UNREADABLE,
            **common,  # type: ignore[arg-type]
        )


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        return None  # HTTP-date forms are treated as too long to wait


def _failed(decision: GateDecision, exc: FetchError) -> GateDecision:
    """A request that was not made, or failed: rate limited when the site's spacing would
    outlast the run (BD-20), otherwise unreachable."""
    outcome = (
        CrawlOutcome.RATE_LIMITED
        if isinstance(exc, RateLimitedError)
        else CrawlOutcome.UNREACHABLE_NETWORK
    )
    return replace(decision, outcome=outcome, reason=str(exc))


def _disallow_line(text: str, user_agent: str, url: str) -> str | None:
    """The longest Disallow line in our group that matches the path, for the record."""
    path = urlsplit(url).path or "/"
    if urlsplit(url).query:
        path += "?" + urlsplit(url).query
    best: tuple[int, str] | None = None
    for name, value in select_rules(parse_groups(text), user_agent):
        longer = best is None or match_length(value) > best[0]
        if name == "disallow" and value and path_matches(value, path) and longer:
            best = (match_length(value), f"Disallow: {value}")
    return best[1] if best else None
