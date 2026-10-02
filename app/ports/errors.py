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
