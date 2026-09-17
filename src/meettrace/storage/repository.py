"""Meeting repository and catalog service for MeetTrace.

Provides discovery, indexing, metadata extraction, sorting, filtering,
and retrieval of persisted meetings from the archive storage hierarchy.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meettrace.storage.models import (
    MeetingMetadata,
    PersistedTranscript,
)
from meettrace.storage.store import MeetingArtifactStore, get_default_storage_root

logger = logging.getLogger(__name__)


def parse_frontmatter_and_title(markdown_text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-style frontmatter and top heading from meeting Markdown text.

    Args:
        markdown_text: The complete UTF-8 content of meeting.md.

    Returns:
        A tuple of (frontmatter_dict, title_string).
    """
    frontmatter: dict[str, str] = {}
    title = "Meeting"

    lines = markdown_text.splitlines()
    in_frontmatter = False
    fm_lines: list[str] = []

    for i, line in enumerate(lines):
        trimmed = line.strip()
        if i == 0 and trimmed == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if trimmed == "---":
                in_frontmatter = False
                continue
            fm_lines.append(trimmed)
        else:
            # Look for top title heading (# Title)
            if trimmed.startswith("# ") and title == "Meeting":
                title = trimmed[2:].strip()

    for fm_line in fm_lines:
        if ":" in fm_line:
            key, val = fm_line.split(":", 1)
            clean_key = key.strip()
            clean_val = val.strip()
            # Strip brackets if list like [en, ru]
            if clean_val.startswith("[") and clean_val.endswith("]"):
                clean_val = clean_val[1:-1].strip()
            frontmatter[clean_key] = clean_val

    return frontmatter, title


def parse_duration_to_ms(duration_str: str) -> int:
    """Parse HH:MM:SS string to milliseconds.

    Args:
        duration_str: Formatted duration e.g. '00:42:00'.

    Returns:
        Duration in milliseconds.
    """
    parts = duration_str.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return ((h * 3600) + (m * 60) + s) * 1000
        if len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            return ((m * 60) + s) * 1000
    except (ValueError, TypeError):
        pass
    return 0


def parse_datetime_safe(dt_str: str) -> datetime | None:
    """Safely parse an ISO datetime string into UTC datetime."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


class MeetingRepository:
    """Catalog service managing discovery and access to saved meetings."""

    def __init__(
        self,
        store: MeetingArtifactStore | None = None,
        storage_root: Path | str | None = None,
    ) -> None:
        """Initialize repository with store or storage root.

        Args:
            store: Optional pre-configured MeetingArtifactStore.
            storage_root: Optional custom storage root path.
        """
        if store is not None:
            self._store = store
        elif storage_root is not None:
            self._store = MeetingArtifactStore(storage_root=storage_root)
        else:
            self._store = MeetingArtifactStore(storage_root=get_default_storage_root())

        self._storage_root = self._store.storage_root
        self._cached_meetings: dict[str, tuple[MeetingMetadata, Path]] = {}
        self._is_indexed: bool = False

    @property
    def store(self) -> MeetingArtifactStore:
        """Return the underlying storage service."""
        return self._store

    @property
    def storage_root(self) -> Path:
        """Return the archive storage root."""
        return self._storage_root

    def refresh(self) -> None:
        """Clear cache and force re-indexing on next access."""
        self._cached_meetings.clear()
        self._is_indexed = False

    def _ensure_indexed(self) -> None:
        """Scan archive root and populate memory cache if not indexed."""
        if self._is_indexed:
            return

        self._cached_meetings.clear()
        if not self._storage_root.exists() or not self._storage_root.is_dir():
            self._is_indexed = True
            return

        # Scan filesystem for directories containing transcript.json or meeting.md
        candidate_dirs: list[Path] = []
        try:
            for root, _dirs, files in os.walk(self._storage_root):
                if "transcript.json" in files or "meeting.md" in files:
                    candidate_dirs.append(Path(root))
        except OSError as exc:
            logger.warning("Error scanning storage root %s: %s", self._storage_root, exc)
            self._is_indexed = True
            return

        for meeting_dir in candidate_dirs:
            try:
                metadata = self._load_directory_metadata(meeting_dir)
                if metadata is not None:
                    self._cached_meetings[metadata.meeting_id] = (metadata, meeting_dir)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Gracefully ignoring corrupt meeting directory %s: %s", meeting_dir, exc
                )

        self._is_indexed = True

    def _load_directory_metadata(self, meeting_dir: Path) -> MeetingMetadata | None:
        """Extract metadata from meeting directory artifacts.

        Combines transcript.json metadata with meeting.md frontmatter and title.
        """
        transcript_path = meeting_dir / "transcript.json"
        markdown_path = meeting_dir / "meeting.md"

        has_transcript = transcript_path.is_file()
        has_markdown = markdown_path.is_file()

        if not has_transcript and not has_markdown:
            return None

        meeting_id = meeting_dir.name
        title = "Meeting"
        started_at = ""
        ended_at = ""
        duration_ms = 0
        dominant_language: str | None = None
        detected_languages: dict[str, float] = {}
        source: dict[str, Any] = {}
        model_name = "faster-whisper:base"
        segment_count = 0
        schema_version = "1.0.0"
        created_at = ""

        # 1. Parse meeting.md if present
        if has_markdown:
            try:
                md_text = markdown_path.read_text(encoding="utf-8")
                frontmatter, parsed_title = parse_frontmatter_and_title(md_text)
                title = parsed_title
                if frontmatter.get("meeting_id"):
                    meeting_id = frontmatter["meeting_id"]
                started_at = frontmatter.get("started_at", "")
                ended_at = frontmatter.get("ended_at", "")
                schema_version = frontmatter.get("schema_version", schema_version)
                if "duration" in frontmatter:
                    duration_ms = parse_duration_to_ms(frontmatter["duration"])
                if frontmatter.get("platform"):
                    source = {"platform": frontmatter["platform"]}
                if "languages" in frontmatter:
                    lang_items = [
                        l.strip() for l in frontmatter["languages"].split(",") if l.strip()
                    ]
                    if lang_items and lang_items[0] != "unknown":
                        dominant_language = lang_items[0]
                        for l in lang_items:
                            detected_languages[l] = detected_languages.get(l, 1.0)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not parse meeting.md in %s: %s", meeting_dir, exc)

        # 2. Parse transcript.json if present
        if has_transcript:
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    t_data = json.load(f)

                if t_data.get("meeting_id"):
                    meeting_id = str(t_data["meeting_id"])

                schema_version = str(t_data.get("schema_version", schema_version))
                t_meta = t_data.get("metadata", {})
                if isinstance(t_meta, dict):
                    if t_meta.get("dominant_language"):
                        dominant_language = str(t_meta["dominant_language"])
                    if isinstance(t_meta.get("detected_languages"), dict):
                        detected_languages.update(
                            {str(k): float(v) for k, v in t_meta["detected_languages"].items()}
                        )
                    if t_meta.get("model_name"):
                        model_name = str(t_meta["model_name"])
                    if t_meta.get("total_duration_ms"):
                        duration_ms = int(t_meta["total_duration_ms"])
                    if t_meta.get("segment_count"):
                        segment_count = int(t_meta["segment_count"])
                    if t_meta.get("created_at"):
                        created_at = str(t_meta["created_at"])

                segments = t_data.get("segments", [])
                if isinstance(segments, list):
                    if not segment_count:
                        segment_count = len(segments)
                    if duration_ms <= 0 and segments:
                        last_seg = segments[-1]
                        if isinstance(last_seg, dict) and "end_ms" in last_seg:
                            duration_ms = int(last_seg["end_ms"])
            except Exception as exc:
                logger.debug("Could not parse transcript.json in %s: %s", meeting_dir, exc)
                if not has_markdown:
                    raise

        # Fallback for started_at if not populated
        if not started_at:
            if created_at:
                started_at = created_at
            else:
                # Try parsing timestamp prefix from meeting_id (e.g. 20260917_153000_...)
                match = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", meeting_id)
                if match:
                    y, m, d, hh, mm, ss = map(int, match.groups())
                    started_at = datetime(y, m, d, hh, mm, ss, tzinfo=UTC).isoformat()
                else:
                    # Last fallback: directory modification time
                    mtime = meeting_dir.stat().st_mtime
                    started_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()

        return MeetingMetadata(
            meeting_id=meeting_id,
            title=title,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            dominant_language=dominant_language,
            detected_languages=detected_languages,
            source=source,
            model_name=model_name,
            segment_count=segment_count,
            schema_version=schema_version,
            created_at=created_at or started_at,
        )

    def _sort_key(self, item: tuple[MeetingMetadata, Path]) -> tuple[float, str]:
        """Compute sort key for ordering meetings newest first."""
        meta, _ = item
        dt = parse_datetime_safe(meta.started_at)
        ts = dt.timestamp() if dt is not None else 0.0
        return (ts, meta.meeting_id)

    def list_meetings(
        self,
        search_query: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MeetingMetadata]:
        """List all discovered meetings sorted newest first, with optional search and pagination.

        Args:
            search_query: Optional case-insensitive text filter.
            limit: Optional maximum number of records to return.
            offset: Optional offset for pagination.

        Returns:
            List of MeetingMetadata records sorted newest-first.
        """
        self._ensure_indexed()

        # Sort newest-first (descending)
        sorted_items = sorted(
            self._cached_meetings.values(),
            key=self._sort_key,
            reverse=True,
        )

        all_meetings = [meta for meta, _dir in sorted_items]

        if search_query:
            q = search_query.strip().lower()
            filtered: list[MeetingMetadata] = []
            for m in all_meetings:
                # Match title
                if q in m.title.lower():
                    filtered.append(m)
                    continue
                # Match dominant or detected language
                if m.dominant_language and q in m.dominant_language.lower():
                    filtered.append(m)
                    continue
                if any(q in lang.lower() for lang in m.detected_languages):
                    filtered.append(m)
                    continue
                # Match platform
                platform = str(m.source.get("platform", "")).lower()
                if platform and q in platform:
                    filtered.append(m)
                    continue
                # Match meeting id or started date
                if q in m.meeting_id.lower() or q in m.started_at.lower():
                    filtered.append(m)
                    continue
            all_meetings = filtered

        if offset > 0 or limit is not None:
            end = (offset + limit) if limit is not None else None
            return all_meetings[offset:end]

        return all_meetings

    def get_meeting(self, meeting_id: str) -> MeetingMetadata | None:
        """Retrieve metadata for a specific meeting by ID."""
        self._ensure_indexed()
        entry = self._cached_meetings.get(meeting_id)
        return entry[0] if entry else None

    def get_meeting_dir(self, meeting_id: str) -> Path | None:
        """Get the filesystem directory path for a specific meeting by ID."""
        self._ensure_indexed()
        entry = self._cached_meetings.get(meeting_id)
        return entry[1] if entry else None

    def get_transcript(self, meeting_id: str) -> PersistedTranscript | None:
        """Load the structured PersistedTranscript for a meeting.

        Returns None if transcript.json is missing or corrupted.
        """
        meeting_dir = self.get_meeting_dir(meeting_id)
        if meeting_dir is None:
            return None
        try:
            return self._store.load_transcript(meeting_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load transcript for %s: %s", meeting_id, exc)
            return None

    def get_meeting_markdown(self, meeting_id: str) -> str | None:
        """Read exact meeting.md content directly from disk.

        Returns None if meeting.md does not exist.
        """
        meeting_dir = self.get_meeting_dir(meeting_id)
        if meeting_dir is None:
            return None
        md_file = meeting_dir / "meeting.md"
        if not md_file.is_file():
            return None
        try:
            return md_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read markdown for %s: %s", meeting_id, exc)
            return None

    def get_summary(self, meeting_id: str) -> Any:
        """Retrieve persisted MeetingSummary for a meeting if available."""
        from meettrace.summary.models import MeetingSummary

        transcript = self.get_transcript(meeting_id)
        if transcript is None or not transcript.summary:
            return None
        try:
            return MeetingSummary.from_dict(transcript.summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse summary for %s: %s", meeting_id, exc)
            return None
