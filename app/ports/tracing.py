from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol


class TracingPort(Protocol):
    def span(self, name: str, **attrs: Any) -> AbstractAsyncContextManager[None]: ...

    def event(self, name: str, **attrs: Any) -> None: ...
