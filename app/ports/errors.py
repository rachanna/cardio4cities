"""Typed errors that every adapter raises in place of vendor exceptions."""


class PortError(Exception):
    """Base class for errors raised through a port."""


class ProviderUnavailableError(PortError):
    """The provider could not be reached or returned a server error."""


class LLMOutputValidationError(PortError):
    """The model's output did not validate against the requested schema."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class FetchError(PortError):
    """A fetch failed at the network level (connection, TLS, timeout)."""

    def __init__(self, message: str, timeout: bool = False) -> None:
        super().__init__(message)
        self.timeout = timeout


CERTIFICATE_CAUSES = {
    "expired": "has expired",
    "self_signed": "is self-signed",
    "hostname_mismatch": "does not match the host name",
    "issuer_missing": "chain is incomplete: the server did not send its issuer certificate",
    "untrusted": "could not be verified",
}


class TLSCertificateError(FetchError):
    """Certificate verification failed (BD-15). `cause` is a key of CERTIFICATE_CAUSES;
    `issuer_urls` are the certificate's own issuer (AIA) URLs when its issuer is missing."""

    def __init__(self, cause: str, issuer_urls: tuple[str, ...] = ()) -> None:
        super().__init__(f"TLS certificate {CERTIFICATE_CAUSES.get(cause, cause)}")
        self.cause = cause
        self.issuer_urls = issuer_urls
