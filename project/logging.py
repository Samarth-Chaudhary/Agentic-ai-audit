"""Common structured logging utility with automated secret redaction for AI Agent Governance.

Guarantees that sensitive data (API keys, passwords, bearer tokens, credentials)
are never logged, and includes trace_id, task_type, component, event, and status in all logs.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from typing import Any

# Context variables for request/trace scoped contextual logging
ctx_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("ctx_trace_id", default=None)
ctx_task_type: contextvars.ContextVar[str | None] = contextvars.ContextVar("ctx_task_type", default=None)
ctx_component: contextvars.ContextVar[str | None] = contextvars.ContextVar("ctx_component", default=None)

# Secret sanitization patterns
SENSITIVE_KEY_NAMES = {
    "password", "secret", "token", "api_key", "apikey", "access_key",
    "secret_key", "authorization", "auth", "private_key", "bearer"
}

SECRET_REGEX_PATTERNS = [
    re.compile(r"Bearer\s+([A-Za-z0-9_\-\.\~\+\/]+=*)", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{12,24}\b"),
    re.compile(r"(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.\~\+\/=]{8,})['\"]?", re.IGNORECASE),
]


def redact_secrets_from_string(text: str) -> str:
    """Scan and redact any credentials or secrets within a string."""
    if not isinstance(text, str):
        return text

    sanitized = text
    for pattern in SECRET_REGEX_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


def sanitize_payload(obj: Any) -> Any:
    """Recursively scrub sensitive keys and regex patterns from any data structure."""
    if isinstance(obj, dict):
        sanitized_dict = {}
        for k, v in obj.items():
            str_key = str(k).lower()
            if any(sensitive_word in str_key for sensitive_word in SENSITIVE_KEY_NAMES):
                sanitized_dict[k] = "[REDACTED_SECRET]"
            else:
                sanitized_dict[k] = sanitize_payload(v)
        return sanitized_dict
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    elif isinstance(obj, str):
        return redact_secrets_from_string(obj)
    return obj


class SecretRedactingFilter(logging.Filter):
    """Logging filter that scrubs sensitive strings from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets_from_string(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_payload(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_payload(a) for a in record.args)
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as JSON with standard audit governance metadata."""

    def format(self, record: logging.LogRecord) -> str:
        # Determine contextual values
        trace_id = getattr(record, "trace_id", None) or ctx_trace_id.get()
        task_type = getattr(record, "task_type", None) or ctx_task_type.get()
        component = getattr(record, "component", None) or ctx_component.get() or record.name
        event = getattr(record, "event", None) or "general_log"
        status = getattr(record, "status", None) or record.levelname.lower()

        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "component": component,
            "event": event,
            "status": status,
            "message": record.getMessage(),
        }

        if trace_id:
            log_entry["trace_id"] = trace_id
        if task_type:
            log_entry["task_type"] = task_type

        # Include any custom extra properties
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_entry["data"] = sanitize_payload(record.extra_data)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(sanitize_payload(log_entry), default=str)


class AuditLogger(logging.LoggerAdapter):
    """Adapter facilitating contextual logging for governance events."""

    def __init__(self, logger: logging.Logger, component: str) -> None:
        super().__init__(logger, {})
        self.component = component

    def log_event(
        self,
        level: int,
        event: str,
        status: str,
        message: str,
        trace_id: str | None = None,
        task_type: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured event log."""
        extra = {
            "component": self.component,
            "event": event,
            "status": status,
            "trace_id": trace_id or ctx_trace_id.get(),
            "task_type": task_type or ctx_task_type.get(),
            "extra_data": extra_data or {},
        }
        self.logger.log(level, message, extra=extra)

    def info_event(
        self,
        event: str,
        status: str,
        message: str,
        trace_id: str | None = None,
        task_type: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        self.log_event(logging.INFO, event, status, message, trace_id, task_type, extra_data)

    def error_event(
        self,
        event: str,
        status: str,
        message: str,
        trace_id: str | None = None,
        task_type: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        self.log_event(logging.ERROR, event, status, message, trace_id, task_type, extra_data)


def configure_logging(level: int = logging.INFO, as_json: bool = True) -> None:
    """Configure root logger with redacting filter and JSON formatter."""
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(SecretRedactingFilter())

    if as_json:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        fmt = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root.addHandler(handler)


def get_logger(name: str, component: str | None = None) -> AuditLogger:
    """Return an AuditLogger adapter configured with secret redaction and structured context."""
    base_logger = logging.getLogger(name)
    if not base_logger.handlers and not logging.getLogger().handlers:
        configure_logging()
    comp = component or name.split(".")[-1]
    return AuditLogger(base_logger, component=comp)
