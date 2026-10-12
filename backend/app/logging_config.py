"""Logging that is safe to ship: one request id per request, JSON option, secrets removed."""
import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Things that look like credentials: API keys and Authorization/Bearer values.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|x-api-key|authorization|password|secret|token)\s*[=:]\s*)\S+"),
]


def redact_text(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub(r"\1[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]", text)
    return text


class ContextFilter(logging.Filter):
    """Stamps every record with the current request id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


_EXTRA_SKIP = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "request_id", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": redact_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _EXTRA_SKIP:
                data[key] = redact_text(value) if isinstance(value, str) else value
        if record.exc_info:
            data["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(data, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def remove_logging_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_graphguard", False):
            root.removeHandler(handler)


def setup_logging(level: str = "INFO", fmt: str = "text", stream=None) -> None:
    remove_logging_handlers()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler._graphguard = True  # type: ignore[attr-defined]
    handler.addFilter(ContextFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    # We write our own access log (path only, no query string), so silence uvicorn's.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs full URLs at INFO, which can include query strings. Keep it quiet.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
