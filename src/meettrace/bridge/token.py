"""Secure token generation and verification for the localhost bridge."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_FILENAME = "bridge_token.txt"


def get_default_token_path() -> Path:
    """Return the default path for the bridge authentication token file."""
    base_dir = Path.home() / ".meettrace"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / DEFAULT_TOKEN_FILENAME


def get_or_create_bridge_token(token_path: Path | str | None = None) -> str:
    """Retrieve existing bridge authentication token or generate and persist a new one.

    Ensures the secret is stored locally and never exposed in version control or logs.

    Args:
        token_path: Optional explicit file path for token storage (useful for isolated tests).

    Returns:
        Secure random token string.
    """
    path = Path(token_path).resolve() if token_path is not None else get_default_token_path()

    if path.is_file():
        try:
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError as exc:
            logger.warning("Failed to read bridge token from %s: %s", path, exc)

    # Generate cryptographically secure token (32 random bytes -> 43 url-safe chars)
    token = secrets.token_urlsafe(32)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write token file
        path.write_text(token, encoding="utf-8")
        # Restrict permissions to user-only where supported (POSIX)
        if os.name != "nt":
            path.chmod(0o600)
        logger.info("Generated new bridge authentication token at %s", path)
    except OSError as exc:
        logger.error("Could not persist bridge authentication token: %s", exc)

    return token


def verify_bridge_token(candidate: str | None, expected_token: str) -> bool:
    """Verify an incoming candidate token against the expected token in constant time.

    Never logs token values to prevent leaking credentials.

    Args:
        candidate: Candidate token string provided by client.
        expected_token: Trusted secret token.

    Returns:
        True if tokens match exactly, False otherwise.
    """
    if not candidate or not expected_token:
        return False

    # Strip any surrounding whitespace or Bearer prefix if passed raw
    cleaned = candidate.strip()
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()

    return hmac.compare_digest(cleaned, expected_token.strip())
