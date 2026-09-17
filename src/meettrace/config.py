"""Environment and configuration loader for MeetTrace.

Safely loads secrets and environment variables from .env files without exposing
credentials in version control or logging.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def load_dotenv(
    dotenv_path: Path | str | None = None,
    override: bool = False,
) -> bool:
    """Load key-value pairs from a .env file into os.environ.

    Searches in the following order if dotenv_path is not specified:
    1. Current working directory: ./.env
    2. Parent directories up to git root or filesystem root
    3. User configuration directory: ~/.meettrace/.env

    Args:
        dotenv_path: Optional explicit path to .env file.
        override: If True, overwrite existing os.environ variables.

    Returns:
        True if a .env file was located and parsed, False otherwise.
    """
    candidate_paths: list[Path] = []
    if dotenv_path is not None:
        candidate_paths.append(Path(dotenv_path))
    else:
        # Check current working directory and walk upwards
        cwd = Path.cwd().resolve()
        for p in [cwd, *cwd.parents]:
            candidate_paths.append(p / ".env")
            if (p / ".git").is_dir():
                break

        # Check user home
        candidate_paths.append(Path.home() / ".meettrace" / ".env")

    found_path: Path | None = None
    for p in candidate_paths:
        if p.is_file():
            found_path = p
            break

    if found_path is None:
        return False

    try:
        content = found_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read .env file at %s: %s", found_path, exc)
        return False

    loaded_count = 0
    for line in content.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        if "=" not in trimmed:
            continue

        key, val = trimmed.split("=", 1)
        clean_key = key.strip()
        clean_val = val.strip()

        # Remove surrounding quotes if present
        if (clean_val.startswith('"') and clean_val.endswith('"')) or (
            clean_val.startswith("'") and clean_val.endswith("'")
        ):
            clean_val = clean_val[1:-1]

        if clean_key and (override or clean_key not in os.environ):
            os.environ[clean_key] = clean_val
            loaded_count += 1

    logger.debug("Loaded %d environment variable(s) from %s", loaded_count, found_path)
    return True
