"""Automated tests for application-wide structured logging and secret redaction."""

from __future__ import annotations

import logging

from meettrace.logging import SecretRedactingFilter, get_logger, setup_logging


def test_secret_redacting_filter():
    filt = SecretRedactingFilter()

    # Test Bearer token redaction
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Sent request with Bearer secret-token-1234567890-abcdef",
        args=(),
        exc_info=None,
    )
    filt.filter(rec)
    assert "secret-token-1234567890-abcdef" not in rec.msg
    assert "[REDACTED_TOKEN]" in rec.msg

    # Test Gemini API key redaction
    rec2 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Using key AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
        args=(),
        exc_info=None,
    )
    filt.filter(rec2)
    assert "AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q" not in rec2.msg
    assert "[REDACTED_KEY]" in rec2.msg

    # Test redaction in format args
    rec3 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Configured token: %s",
        args=("Bearer my-super-secret-auth-token-99999",),
        exc_info=None,
    )
    filt.filter(rec3)
    assert "my-super-secret-auth-token-99999" not in str(rec3.args)
    assert "[REDACTED_TOKEN]" in str(rec3.args)


def test_setup_logging_file_and_console(tmp_path):
    log_dir = tmp_path / "logs"
    log_file = setup_logging(log_dir=log_dir, log_level=logging.DEBUG)

    assert log_file.is_file() or log_file.parent.is_dir()
    assert log_file.name == "meettrace.log"

    logger = get_logger("meettrace.test")
    logger.info("Test message for file verification with Bearer secret-token-xyz123456789")

    # Force flush
    for h in logging.getLogger().handlers:
        h.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "Test message for file verification" in content
    assert "secret-token-xyz123456789" not in content
    assert "[REDACTED_TOKEN]" in content
