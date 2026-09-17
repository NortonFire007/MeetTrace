"""Structured application-wide logging subsystem with secret redaction and rotation.

Provides safe, performant local logging to stderr and rotating file destinations
while strictly redacting API keys and bridge authentication secrets.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_FILENAME = "meettrace.log"
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5

# Regex patterns for redacting sensitive secrets
BEARER_TOKEN_PATTERN = re.compile(r"Bearer\s+([A-Za-z0-9_\-=+]{16,})", re.IGNORECASE)
GEMINI_KEY_PATTERN = re.compile(r"(AIzaSy[A-Za-z0-9_\-]{33})", re.IGNORECASE)
GENERIC_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-=+]{16,})['\"]?",
    re.IGNORECASE,
)


class SecretRedactingFilter(logging.Filter):
    """Logging filter that redacts API keys and secret bearer tokens from messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Inspect and sanitize log record message."""
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._redact(str(a)) if isinstance(a, str) else a for a in record.args
                )

        return True

    @staticmethod
    def _redact(text: str) -> str:
        """Replace discovered secret substrings with masked tokens."""
        if not text:
            return text

        # Redact Bearer tokens
        text = BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED_TOKEN]", text)
        # Redact Gemini API keys (mask except first 6 chars 'AIzaSy')
        text = GEMINI_KEY_PATTERN.sub(lambda m: m.group(1)[:6] + "...[REDACTED_KEY]", text)
        # Redact key=value pairs
        text = GENERIC_SECRET_PATTERN.sub(r"\1=[REDACTED_SECRET]", text)
        return text


def get_default_log_dir() -> Path:
    """Return default application logging directory in user home."""
    base_dir = Path.home() / ".meettrace" / "logs"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def setup_logging(
    log_dir: Path | str | None = None,
    log_level: int | str = logging.INFO,
    enable_console: bool = True,
    enable_file: bool = True,
) -> Path:
    """Configure structured application-wide logging.

    Args:
        log_dir: Directory where rotating log files will be saved.
        log_level: Base logging level (e.g. logging.INFO or logging.DEBUG).
        enable_console: Whether to attach stderr console handler.
        enable_file: Whether to attach rotating file handler.

    Returns:
        Path to the primary log file.
    """
    target_dir = Path(log_dir).resolve() if log_dir is not None else get_default_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / DEFAULT_LOG_FILENAME

    # Respect environment variable override if set
    env_level = os.environ.get("MEETTRACE_LOG_LEVEL", "").upper().strip()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        effective_level: int | str = env_level
    else:
        effective_level = log_level

    root_logger = logging.getLogger()
    root_logger.setLevel(effective_level)

    # Remove existing handlers to avoid duplicate log entries
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redacting_filter = SecretRedactingFilter()

    if enable_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redacting_filter)
        root_logger.addHandler(console_handler)

    if enable_file:
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=MAX_LOG_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(redacting_filter)
            root_logger.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger(__name__).warning("Failed to initialize file logger: %s", exc)

    return log_file


def get_logger(name: str) -> logging.Logger:
    """Convenience helper to obtain a named logger."""
    return logging.getLogger(name)
