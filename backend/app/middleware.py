"""Cross-cutting protections: request ids, size limits, safe errors, security headers, access log."""
import logging
import re
import sqlite3
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.config import Settings
from app.logging_config import request_id_var

log = logging.getLogger("graphguard.access")
error_log = logging.getLogger("graphguard.errors")

_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_API_CSP = "default-src 'none'; frame-ancestors 'none'"
_LIVE_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' ws: wss:; frame-ancestors 'none'"
)
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_QUIET_PATHS = ("/api/health", "/api/ready")


def _security_headers(path: str) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }
    if path == "/live":
        headers["Content-Security-Policy"] = _LIVE_CSP
    elif not path.startswith(_DOC_PATHS):
        headers["Content-Security-Policy"] = _API_CSP
    if path.startswith("/api"):
        headers["Cache-Control"] = "no-store"
    return headers


def _json(status: int, detail: str, request_id: str, extra: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail, "request_id": request_id, **(extra or {})}, status_code=status)


def install_middleware(app: FastAPI, settings: Settings) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Report where and why, but never echo back what the client sent.
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
        return _json(422, "Request validation failed", request_id_var.get(), {"errors": errors})

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        error_log.error("database error on %s %s: %s", request.method, request.url.path, type(exc).__name__, exc_info=exc)
        return _json(503, "The database is unavailable. Please try again.", request_id_var.get())

    @app.middleware("http")
    async def protect(request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_OK.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        path = request.url.path
        try:
            length = request.headers.get("content-length")
            try:
                too_big = length is not None and int(length) > settings.max_request_body_bytes
                bad_length = False
            except ValueError:
                too_big, bad_length = False, True
            if bad_length:
                response: Response = _json(400, "Invalid Content-Length header", request_id)
            elif too_big:
                response = _json(413, "Request body is too large", request_id)
            else:
                try:
                    response = await call_next(request)
                except Exception as exc:  # last resort: log the details, tell the client nothing sensitive
                    error_log.error("unhandled error on %s %s", request.method, path, exc_info=exc)
                    response = _json(500, "Internal server error", request_id)
            response.headers["X-Request-ID"] = request_id
            for key, value in _security_headers(path).items():
                response.headers.setdefault(key, value)
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            log.log(
                level,
                "%s %s -> %s",
                request.method,
                path,  # path only: query strings can contain account ids
                response.status_code,
                extra={"method": request.method, "path": path, "status": response.status_code,
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            return response
        finally:
            request_id_var.reset(token)
