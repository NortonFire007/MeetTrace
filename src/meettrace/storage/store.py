"""Meeting artifact storage service for MeetTrace.

Responsible for date-based meeting directory hierarchies (YYYY/MM/DD/<meeting-id>),
collision-safe ID generation, path traversal defense, and durable atomic persistence
of transcript.json and meeting.md.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meettrace.storage.markdown import render_meeting_markdown
from meettrace.storage.models import (
    MeetingMetadata,
    PersistedSegment,
    PersistedTranscript,
)
from meettrace.storage.writer import (
    atomic_write_json,
    atomic_write_text,
    generate_meeting_id,
    validate_meeting_id,
)
from meettrace.transcription.models import TranscriptMetadata, TranscriptSegment

logger = logging.getLogger(__name__)


def get_default_storage_root() -> Path:
    """Resolve the default meeting archive root: %USERPROFILE%\\MeetTrace\\meetings.

    Returns:
        Absolute Path to the default meeting archive root directory.
    """
    user_profile = os.environ.get("USERPROFILE")
    base = Path(user_profile) if user_profile else Path.home()
    return (base / "MeetTrace" / "meetings").resolve()


class MeetingArtifactStore:
    """Service managing persisted meeting artifacts on the local filesystem."""

    def __init__(self, storage_root: Path | str | None = None) -> None:
        """Initialize the storage service with a resolved storage root.

        Args:
            storage_root: Optional custom storage root path. Defaults to
                          %USERPROFILE%\\MeetTrace\\meetings.
        """
        self._storage_root = (
            Path(storage_root).resolve() if storage_root is not None else get_default_storage_root()
        )

    @property
    def storage_root(self) -> Path:
        """Return the base archive directory path."""
        return self._storage_root

    def resolve_meeting_dir(
        self,
        meeting_id: str,
        started_at: datetime | str | None = None,
    ) -> Path:
        """Resolve the date-based directory path for a meeting.

        Layout: <storage_root>/YYYY/MM/DD/<meeting-id>/

        Args:
            meeting_id: Unique meeting identifier.
            started_at: Optional start datetime or ISO string to extract date components.

        Returns:
            The resolved Path for the meeting directory.

        Raises:
            ValueError: If meeting_id is invalid or attempts path traversal.
        """
        validate_meeting_id(meeting_id)

        dt = self._extract_datetime(started_at, meeting_id)
        rel_path = Path(f"{dt.year:04d}") / f"{dt.month:02d}" / f"{dt.day:02d}" / meeting_id
        resolved = (self._storage_root / rel_path).resolve()

        # Prevent directory traversal: must be strictly within storage_root
        try:
            resolved.relative_to(self._storage_root)
        except ValueError as exc:
            raise ValueError(
                f"Resolved meeting path {resolved} is outside storage root {self._storage_root}."
            ) from exc

        return resolved

    def create_meeting(
        self,
        started_at: datetime | None = None,
        meeting_id: str | None = None,
        title: str = "Meeting",
        source: dict[str, Any] | str | None = None,
    ) -> tuple[MeetingMetadata, Path]:
        """Create a new date-based meeting directory and initial metadata.

        Args:
            started_at: Optional meeting start timestamp. Defaults to UTC now.
            meeting_id: Optional custom meeting ID. Defaults to generated unique ID.
            title: Meeting title.
            source: Source platform metadata.

        Returns:
            Tuple of (initial MeetingMetadata, created meeting directory Path).
        """
        dt = started_at or datetime.now(UTC)
        mid = meeting_id or generate_meeting_id(dt)
        validate_meeting_id(mid)

        meeting_dir = self.resolve_meeting_dir(mid, started_at=dt)
        meeting_dir.mkdir(parents=True, exist_ok=True)

        source_dict: dict[str, Any] = (
            {"platform": source} if isinstance(source, str) else (source or {})
        )

        metadata = MeetingMetadata(
            meeting_id=mid,
            title=title,
            started_at=dt.isoformat(),
            source=source_dict,
        )

        logger.info("Created meeting directory: %s", meeting_dir)
        return metadata, meeting_dir

    def save_raw_transcript(
        self,
        meeting_id: str,
        segments: Sequence[TranscriptSegment | PersistedSegment],
        transcript_metadata: TranscriptMetadata | None = None,
        started_at: datetime | str | None = None,
        ended_at: datetime | str | None = None,
        title: str = "Meeting",
        source: dict[str, Any] | str | None = None,
        meeting_dir: Path | None = None,
    ) -> tuple[Path, Path]:
        """Durably and atomically persist transcript.json and meeting.md.

        In accordance with durability requirements, raw transcript artifacts are
        persisted before any optional downstream operations (such as AI summarization).

        Args:
            meeting_id: Unique meeting identifier.
            segments: Ordered sequence of transcript segments.
            transcript_metadata: Aggregated metadata from transcription engine.
            started_at: Optional start timestamp.
            ended_at: Optional completion timestamp.
            title: Meeting title.
            source: Platform/source metadata.
            meeting_dir: Optional pre-resolved meeting directory.

        Returns:
            Tuple of (Path to transcript.json, Path to meeting.md).
        """
        validate_meeting_id(meeting_id)
        target_dir = meeting_dir or self.resolve_meeting_dir(meeting_id, started_at=started_at)
        target_dir.mkdir(parents=True, exist_ok=True)

        now_utc = datetime.now(UTC)
        start_iso = (
            started_at.isoformat()
            if isinstance(started_at, datetime)
            else (started_at or now_utc.isoformat())
        )
        end_iso = (
            ended_at.isoformat()
            if isinstance(ended_at, datetime)
            else (ended_at or now_utc.isoformat())
        )

        meta = transcript_metadata or TranscriptMetadata()

        # Calculate duration if available
        duration_ms = meta.total_duration_ms
        if duration_ms <= 0 and segments:
            duration_ms = max(s.end_ms for s in segments)

        # Build domain models
        persisted_transcript = PersistedTranscript.from_segments(
            meeting_id=meeting_id,
            metadata=meta,
            segments=segments,
        )

        source_dict: dict[str, Any] = (
            {"platform": source} if isinstance(source, str) else (source or {})
        )

        meeting_meta = MeetingMetadata(
            meeting_id=meeting_id,
            title=title,
            started_at=start_iso,
            ended_at=end_iso,
            duration_ms=duration_ms,
            dominant_language=meta.dominant_language,
            detected_languages=meta.detected_languages,
            source=source_dict,
            model_name=meta.model_name,
            segment_count=len(segments),
        )

        # 1. Atomically save transcript.json
        transcript_path = target_dir / "transcript.json"
        atomic_write_json(transcript_path, persisted_transcript.to_dict(), indent=2)
        logger.info("Saved transcript JSON: %s", transcript_path)

        # 2. Atomically save meeting.md
        markdown_content = render_meeting_markdown(
            metadata=meeting_meta,
            segments=persisted_transcript.segments,
        )
        markdown_path = target_dir / "meeting.md"
        atomic_write_text(markdown_path, markdown_content, encoding="utf-8")
        logger.info("Saved meeting Markdown: %s", markdown_path)

        return transcript_path, markdown_path

    def load_transcript(self, meeting_dir: Path | str) -> PersistedTranscript:
        """Load and parse transcript.json from a meeting directory.

        Args:
            meeting_dir: Path to the meeting directory.

        Returns:
            Deserialized PersistedTranscript model.

        Raises:
            FileNotFoundError: If transcript.json does not exist.
            ValueError: If JSON is corrupted or invalid.
        """
        path = Path(meeting_dir) / "transcript.json"
        if not path.is_file():
            raise FileNotFoundError(f"Transcript file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return PersistedTranscript.from_dict(data)

    def load_metadata(self, meeting_dir: Path | str) -> MeetingMetadata:
        """Load metadata for a meeting from transcript.json.

        Args:
            meeting_dir: Path to the meeting directory.

        Returns:
            Constructed MeetingMetadata model.
        """
        transcript = self.load_transcript(meeting_dir)
        meta = transcript.metadata
        return MeetingMetadata(
            meeting_id=transcript.meeting_id,
            dominant_language=meta.dominant_language,
            detected_languages=meta.detected_languages,
            model_name=meta.model_name,
            duration_ms=meta.total_duration_ms,
            segment_count=meta.segment_count or len(transcript.segments),
            schema_version=transcript.schema_version,
            created_at=meta.created_at,
        )

    def _extract_datetime(
        self,
        started_at: datetime | str | None,
        meeting_id: str,
    ) -> datetime:
        """Extract a datetime for directory partitioning."""
        if isinstance(started_at, datetime):
            return started_at

        if isinstance(started_at, str):
            try:
                return datetime.fromisoformat(started_at)
            except ValueError:
                pass

        # Try parsing date prefix from meeting_id (e.g. 20260917_...)
        if len(meeting_id) >= 8 and meeting_id[:8].isdigit():
            try:
                year = int(meeting_id[:4])
                month = int(meeting_id[4:6])
                day = int(meeting_id[6:8])
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                pass

        return datetime.now(UTC)
