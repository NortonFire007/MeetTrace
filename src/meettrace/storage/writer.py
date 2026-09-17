"""Atomic filesystem writer and path safety utilities for MeetTrace.

Guarantees atomic file persistence using a write-flush-fsync-replace pattern
to prevent partially written or corrupted meeting artifacts during process termination.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# Allow only alphanumeric characters, underscores, and hyphens in meeting IDs.
_SAFE_MEETING_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_meeting_id(meeting_id: str) -> None:
    """Validate that a meeting_id is safe from directory traversal and illegal characters.

    Args:
        meeting_id: The identifier string to validate.

    Raises:
        ValueError: If meeting_id is empty, contains path separators, or illegal characters.
    """
    if not meeting_id or not isinstance(meeting_id, str):
        raise ValueError("meeting_id must be a non-empty string.")

    if meeting_id in (".", ".."):
        raise ValueError(f"Invalid meeting_id: {meeting_id!r} cannot be a relative directory name.")

    if not _SAFE_MEETING_ID_PATTERN.match(meeting_id):
        raise ValueError(
            f"Invalid meeting_id: {meeting_id!r}. "
            "Meeting IDs must contain only alphanumeric characters, underscores, and hyphens."
        )


def generate_meeting_id(dt: datetime | None = None) -> str:
    """Generate a collision-safe, path-safe meeting ID.

    Format: YYYYMMDD_HHMMSS_<short_uuid> (e.g., '20260917_153000_a1b2c3d4').

    Args:
        dt: Optional datetime for the timestamp prefix. Defaults to current UTC time.

    Returns:
        A unique, path-safe string identifier.
    """
    timestamp = dt or datetime.now(UTC)
    date_prefix = timestamp.strftime("%Y%m%d_%H%M%S")
    unique_suffix = uuid4().hex[:8]
    return f"{date_prefix}_{unique_suffix}"


def atomic_write_text(
    path: Path | str,
    content: str,
    encoding: str = "utf-8",
) -> Path:
    """Atomically write text content to a destination path.

    Writes to a hidden temporary file in the same target directory, forces an fsync
    to disk, and atomically renames the temporary file to the destination path.

    Args:
        path: Destination target path.
        content: String content to write.
        encoding: File character encoding (default: 'utf-8').

    Returns:
        The resolved Path of the successfully written file.
    """
    dest = Path(path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    temp_path = dest.parent / f".{dest.name}.tmp.{uuid4().hex}"
    try:
        with open(temp_path, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, dest)
        return dest
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_json(
    path: Path | str,
    data: Any,
    indent: int = 2,
    encoding: str = "utf-8",
) -> Path:
    """Atomically serialize data to a JSON file.

    Ensures UTF-8 formatting with unescaped Unicode characters (such as Cyrillic)
    and ends with a newline.

    Args:
        path: Destination target path.
        data: JSON-serializable Python data structure.
        indent: Indentation level for formatting.
        encoding: File character encoding (default: 'utf-8').

    Returns:
        The resolved Path of the successfully written file.
    """
    json_text = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    return atomic_write_text(path, json_text, encoding=encoding)
