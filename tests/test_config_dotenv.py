"""Tests for meettrace.config.load_dotenv and environment variable resolution."""

from __future__ import annotations

import os
from pathlib import Path

from meettrace.config import load_dotenv
from meettrace.summary.gemini import GeminiConfig


def test_load_dotenv_parses_key_values_and_quotes(tmp_path: Path) -> None:
    """Verify load_dotenv reads comments, keys, and values with various quotation styles."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        """# This is a comment
GEMINI_TEST_KEY_PLAIN=plain_value123
GEMINI_TEST_KEY_DOUBLE="double_quoted_value"
GEMINI_TEST_KEY_SINGLE='single_quoted_value'
INVALID_LINE_NO_EQUALS
# Another comment
EMPTY_VALUE=
""",
        encoding="utf-8",
    )

    # Clear test variables
    for k in (
        "GEMINI_TEST_KEY_PLAIN",
        "GEMINI_TEST_KEY_DOUBLE",
        "GEMINI_TEST_KEY_SINGLE",
        "EMPTY_VALUE",
    ):
        os.environ.pop(k, None)

    loaded = load_dotenv(env_file)
    assert loaded is True

    assert os.environ.get("GEMINI_TEST_KEY_PLAIN") == "plain_value123"
    assert os.environ.get("GEMINI_TEST_KEY_DOUBLE") == "double_quoted_value"
    assert os.environ.get("GEMINI_TEST_KEY_SINGLE") == "single_quoted_value"
    assert os.environ.get("EMPTY_VALUE") == ""


def test_load_dotenv_does_not_override_by_default(tmp_path: Path) -> None:
    """Verify load_dotenv preserves existing environment variables unless override=True."""
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_VAR=new_value\n", encoding="utf-8")

    os.environ["EXISTING_VAR"] = "original_value"
    load_dotenv(env_file, override=False)
    assert os.environ["EXISTING_VAR"] == "original_value"

    load_dotenv(env_file, override=True)
    assert os.environ["EXISTING_VAR"] == "new_value"

    os.environ.pop("EXISTING_VAR", None)


def test_load_dotenv_nonexistent_file(tmp_path: Path) -> None:
    """Verify load_dotenv returns False safely if path does not exist."""
    missing = tmp_path / "nonexistent" / ".env"
    assert load_dotenv(missing) is False


def test_gemini_config_resolves_key_from_dotenv(tmp_path: Path) -> None:
    """Verify GeminiConfig.resolve_api_key picks up key from .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=AIzaSyDotEnvTestKey456\n", encoding="utf-8")

    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GOOGLE_API_KEY", None)

    # Pass dotenv explicitly via load_dotenv
    load_dotenv(env_file)

    config = GeminiConfig()
    assert config.resolve_api_key() == "AIzaSyDotEnvTestKey456"
