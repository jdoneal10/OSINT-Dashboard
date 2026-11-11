"""Logging setup with a redaction filter as a last line of defense against leaked secrets."""

from __future__ import annotations

import logging
import re

_REDACTIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),  # Anthropic API keys
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),  # OAuth bearer tokens
    re.compile(r"(?i)((?:password|passwd|secret|token|api_key)\s*[=:]\s*)\S+"),
    re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+(@)"),  # DSN passwords
)

REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    for pattern in _REDACTIONS:
        if pattern.groups == 0:
            text = pattern.sub(REDACTED, text)
        elif pattern.groups == 1:
            text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pattern.sub(lambda m: m.group(1) + REDACTED + m.group(2), text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
    )
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
