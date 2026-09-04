"""Structured logging (structlog) configured once at app boot."""

from __future__ import annotations

import logging
import sys
import re

import structlog

# Keys/patterns that must be redacted
REDACT_KEYS = {
    "api_key", "runpod_api_key", "authorization", "token", "password", "secret",
    "jwt", "bearer", "s3_secret_key", "s3_access_key", "capture_ref", "output_ref",
    "storage_signing_secret", "kiosk_token", "operator_jwt_secret",
}
REDACT_PATTERN = re.compile(r"(api[_-]?key|token|password|secret|authorization|bearer)\s*[:=]\s*\S+", re.IGNORECASE)


def _redact_processor(logger, method_name, event_dict):
    """Redact secrets from log event_dict."""
    for key in list(event_dict.keys()):
        low = key.lower()
        # Exact key match or substring
        if any(rk in low for rk in REDACT_KEYS):
            event_dict[key] = "[REDACTED]"
        elif isinstance(event_dict[key], str):
            # Regex for embedded secrets in string values
            val = event_dict[key]
            if REDACT_PATTERN.search(val):
                event_dict[key] = REDACT_PATTERN.sub(r"\1=[REDACTED]", val)
            # Never log raw image/video bytes or data urls
            if val.startswith("data:image") or val.startswith("data:video") or len(val) > 2000:
                # Truncate large blobs
                if len(val) > 500:
                    event_dict[key] = val[:200] + f"...[TRUNCATED {len(val)} chars]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for JSON-friendly structured logs."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)