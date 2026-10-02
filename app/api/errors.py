"""One error envelope for every failure (LLD-4 §6). Messages are written for the City Lead."""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return JSONResponse(envelope(exc.code, exc.message, exc.details), status_code=exc.status)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields = [".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()]
    return JSONResponse(
        envelope(
            "invalid_request", "The request was not in the expected form.", {"fields": fields}
        ),
        status_code=400,
    )


async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
    request_id = uuid.uuid4().hex
    log.exception("unhandled error request_id=%s", request_id, exc_info=exc)
    return JSONResponse(
        envelope(
            "internal_error",
            "Something went wrong on our side. Try again in a minute.",
            {"request_id": request_id},
        ),
        status_code=500,
    )


def install(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected)
