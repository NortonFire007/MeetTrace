"""Storage package for MeetTrace meeting artifacts.

Provides durable persistence of meeting metadata, ordered timestamped transcripts,
and human-readable Markdown notes.
"""

from __future__ import annotations

from meettrace.storage.markdown import (
    format_duration_ms,
    format_timestamp_ms,
    render_meeting_markdown,
)
from meettrace.storage.models import (
    SCHEMA_VERSION,
    MeetingMetadata,
    PersistedSegment,
    PersistedTranscript,
    PersistedWord,
)
from meettrace.storage.repository import (
    MeetingRepository,
    parse_frontmatter_and_title,
)
from meettrace.storage.store import (
    MeetingArtifactStore,
    get_default_storage_root,
)
from meettrace.storage.writer import (
    atomic_write_json,
    atomic_write_text,
    generate_meeting_id,
    validate_meeting_id,
)

__all__ = [
    "SCHEMA_VERSION",
    "MeetingArtifactStore",
    "MeetingMetadata",
    "MeetingRepository",
    "PersistedSegment",
    "PersistedTranscript",
    "PersistedWord",
    "atomic_write_json",
    "atomic_write_text",
    "format_duration_ms",
    "format_timestamp_ms",
    "generate_meeting_id",
    "get_default_storage_root",
    "parse_frontmatter_and_title",
    "render_meeting_markdown",
    "validate_meeting_id",
]
