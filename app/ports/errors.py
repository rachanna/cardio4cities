"""Typed errors that every adapter raises in place of vendor exceptions."""

from typing import Any


class PortError(Exception):
    """Base class for errors raised through a port. `usage`: what a failed model call
    used, when the provider reported it (BD-30), so the cap and the summary count it."""

    usage: Any = None


class ProviderUnavailableError(PortError):
    """The provider could not be reached or returned a server error."""


class LLMOutputValidationError(PortError):
    """The model's output did not validate against the requested schema. `truncated`:
    the output was cut off at the token ceiling (BD-26), so a repair asks for less."""

    def __init__(self, message: str, raw_text: str, truncated: bool = False) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.truncated = truncated


class FetchError(PortError):
    """A fetch failed at the network level (connection, TLS, timeout). `retryable`: a
    connection-level failure worth one more try (LLD-2 §17, BD-21); a timeout, a
    certificate or a body we cannot decode is not."""

    def __init__(self, message: str, timeout: bool = False, retryable: bool = False) -> None:
        super().__init__(message)
        self.timeout = timeout
        self.retryable = retryable


CERTIFICATE_CAUSES = {
    "expired": "has expired",
    "self_signed": "is self-signed",
    "hostname_mismatch": "does not match the host name",
    "issuer_missing": "chain is incomplete: the server did not send its issuer certificate",
    "issuer_untrusted": "chain could not be completed to a trusted root",
    "untrusted": "could not be verified",
}


class TLSCertificateError(FetchError):
    """Certificate verification failed (BD-15). `cause` is a key of CERTIFICATE_CAUSES;
    `issuer_urls` are the certificate's own issuer (AIA) URLs when its issuer is missing."""

    def __init__(self, cause: str, issuer_urls: tuple[str, ...] = ()) -> None:
        super().__init__(f"TLS certificate {CERTIFICATE_CAUSES.get(cause, cause)}")
        self.cause = cause
        self.issuer_urls = issuer_urls
