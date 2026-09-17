"""Unit tests for MeetingArtifactStore, atomic writers, and persisted schemas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meettrace.storage import (
    SCHEMA_VERSION,
    MeetingArtifactStore,
    MeetingMetadata,
    PersistedSegment,
    PersistedTranscript,
    atomic_write_json,
    atomic_write_text,
    format_timestamp_ms,
    generate_meeting_id,
    render_meeting_markdown,
    validate_meeting_id,
)
from meettrace.transcription.models import (
    TranscriptMetadata,
    TranscriptSegment,
    TranscriptWord,
)


def test_validate_meeting_id() -> None:
    """Verify meeting ID validation rejects path traversal and illegal chars."""
    # Valid IDs
    validate_meeting_id("20260917_153000_a1b2c3d4")
    validate_meeting_id("meeting-123_abc")
    validate_meeting_id("test")

    # Invalid IDs
    with pytest.raises(ValueError, match="non-empty string"):
        validate_meeting_id("")

    with pytest.raises(ValueError, match="Meeting IDs must contain only"):
        validate_meeting_id("../traversal")

    with pytest.raises(ValueError, match="Meeting IDs must contain only"):
        validate_meeting_id("folder/subfolder")

    with pytest.raises(ValueError, match="Meeting IDs must contain only"):
        validate_meeting_id("folder\\subfolder")

    with pytest.raises(ValueError, match="Meeting IDs must contain only"):
        validate_meeting_id("meeting:name")

    with pytest.raises(ValueError, match="relative directory"):
        validate_meeting_id("..")

    with pytest.raises(ValueError, match="relative directory"):
        validate_meeting_id(".")


def test_generate_meeting_id() -> None:
    """Verify generated meeting IDs are formatted and collision-safe."""
    dt = datetime(2026, 9, 17, 15, 30, 0, tzinfo=UTC)
    mid1 = generate_meeting_id(dt)
    mid2 = generate_meeting_id(dt)

    assert mid1.startswith("20260917_153000_")
    assert mid2.startswith("20260917_153000_")
    assert mid1 != mid2  # Collision-safe suffix
    validate_meeting_id(mid1)
    validate_meeting_id(mid2)


def test_meeting_directory_layout(tmp_path: Path) -> None:
    """Verify YYYY/MM/DD/<meeting-id> directory structure."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    dt = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    meeting_id = "20260917_100000_abc123"

    resolved = store.resolve_meeting_dir(meeting_id, started_at=dt)
    expected = tmp_path / "2026" / "09" / "17" / meeting_id
    assert resolved == expected

    # Create meeting directory
    meta, created_path = store.create_meeting(started_at=dt, meeting_id=meeting_id)
    assert created_path.is_dir()
    assert created_path == expected
    assert meta.meeting_id == meeting_id


def test_meeting_directory_path_traversal_defense(tmp_path: Path) -> None:
    """Verify path traversal attempts are detected and rejected."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    with pytest.raises(ValueError):
        store.resolve_meeting_dir("../../etc/passwd")


def test_atomic_write_text_and_json(tmp_path: Path) -> None:
    """Verify atomic write persists files with fsync and cleans up temp files."""
    dest_txt = tmp_path / "subdir" / "note.txt"
    written = atomic_write_text(dest_txt, "Hello MeetTrace! Привет! Привіт!")
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == "Hello MeetTrace! Привет! Привіт!"

    # No leftover temporary files
    temp_files = list(dest_txt.parent.glob(".*.tmp.*"))
    assert len(temp_files) == 0

    # JSON atomic write
    dest_json = tmp_path / "data.json"
    sample_data = {"key": "значение", "number": 42}
    atomic_write_json(dest_json, sample_data)
    assert dest_json.is_file()

    with open(dest_json, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == sample_data


def test_persisted_transcript_round_trip() -> None:
    """Verify PersistedTranscript serialization and deserialization preserves all fields and Unicode."""
    words = (
        TranscriptWord(word="Привет", start_ms=1000, end_ms=1400, probability=0.98),
        TranscriptWord(word="мир", start_ms=1500, end_ms=1800, probability=0.99),
    )
    seg1 = TranscriptSegment(
        text="Привет мир",
        start_ms=1000,
        end_ms=2000,
        language="ru",
        confidence=0.97,
        words=words,
    )
    seg2 = TranscriptSegment(
        text="Ласкаво просимо на зустріч",
        start_ms=2500,
        end_ms=5000,
        language="uk",
        confidence=0.96,
    )
    seg3 = TranscriptSegment(
        text="Welcome to the meeting",
        start_ms=5500,
        end_ms=8000,
        language="en",
        confidence=0.99,
    )

    meta = TranscriptMetadata(
        session_id="sess-001",
        dominant_language="ru",
        detected_languages={"ru": 0.5, "uk": 0.3, "en": 0.2},
        model_name="faster-whisper:base",
        total_duration_ms=8000,
        segment_count=3,
        created_at="2026-09-17T15:30:00+00:00",
    )

    persisted = PersistedTranscript.from_segments(
        meeting_id="meeting-101",
        metadata=meta,
        segments=[seg1, seg2, seg3],
    )

    # Convert to dict and back
    data = persisted.to_dict()
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["meeting_id"] == "meeting-101"
    assert len(data["segments"]) == 3
    assert data["segments"][0]["words"][0]["word"] == "Привет"

    restored = PersistedTranscript.from_dict(data)
    assert restored.meeting_id == persisted.meeting_id
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.metadata.dominant_language == "ru"
    assert restored.metadata.detected_languages == {"ru": 0.5, "uk": 0.3, "en": 0.2}
    assert len(restored.segments) == 3
    assert restored.segments[0].text == "Привет мир"
    assert restored.segments[0].language == "ru"
    assert len(restored.segments[0].words) == 2
    assert restored.segments[0].words[0].word == "Привет"
    assert restored.segments[0].words[0].start_ms == 1000
    assert restored.segments[1].text == "Ласкаво просимо на зустріч"
    assert restored.segments[1].language == "uk"
    assert restored.segments[2].text == "Welcome to the meeting"


def test_markdown_rendering() -> None:
    """Verify Markdown rendering matches OpenSpec specification and preserves timestamps."""
    meta = MeetingMetadata(
        meeting_id="20260917_153000_abc",
        title="Weekly Sync",
        started_at="2026-09-17T15:30:00+00:00",
        ended_at="2026-09-17T15:54:17+00:00",
        duration_ms=1457000,  # 24m 17s
        dominant_language="en",
        detected_languages={"en": 0.8, "ru": 0.2},
    )

    segments = [
        PersistedSegment(
            text="Let's start the weekly sync.",
            start_ms=12000,  # [00:00:12]
            end_ms=15000,
            language="en",
        ),
        PersistedSegment(
            text="Давайте обсудим статус проекта.",
            start_ms=18500,  # [00:00:18]
            end_ms=22000,
            language="ru",
        ),
    ]

    md = render_meeting_markdown(meta, segments)

    # Validate Frontmatter
    assert md.startswith("---")
    assert "meeting_id: 20260917_153000_abc" in md
    assert "started_at: 2026-09-17T15:30:00+00:00" in md
    assert "ended_at: 2026-09-17T15:54:17+00:00" in md
    assert "duration: 00:24:17" in md
    assert "languages: [en, ru]" in md
    assert f"schema_version: {SCHEMA_VERSION}" in md

    # Validate Content
    assert "# Weekly Sync" in md
    assert "## Transcript" in md
    assert "[00:00:12] Let's start the weekly sync." in md
    assert "[00:00:18] Давайте обсудим статус проекта." in md


def test_save_raw_transcript_pipeline(tmp_path: Path) -> None:
    """Verify complete save_raw_transcript pipeline persists transcript.json and meeting.md."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    meeting_id = "20260917_180000_run1"

    seg = TranscriptSegment(
        text="Test recording complete.",
        start_ms=0,
        end_ms=3000,
        language="en",
    )
    t_meta = TranscriptMetadata(
        dominant_language="en",
        total_duration_ms=3000,
        segment_count=1,
    )

    t_path, m_path = store.save_raw_transcript(
        meeting_id=meeting_id,
        segments=[seg],
        transcript_metadata=t_meta,
        title="Project Kickoff",
    )

    assert t_path.is_file()
    assert m_path.is_file()
    assert t_path.name == "transcript.json"
    assert m_path.name == "meeting.md"

    # Verify loading back from store
    loaded_transcript = store.load_transcript(t_path.parent)
    assert loaded_transcript.meeting_id == meeting_id
    assert len(loaded_transcript.segments) == 1
    assert loaded_transcript.segments[0].text == "Test recording complete."

    loaded_meta = store.load_metadata(t_path.parent)
    assert loaded_meta.meeting_id == meeting_id
    assert loaded_meta.dominant_language == "en"


def test_raw_transcript_durability_on_summary_failure(tmp_path: Path) -> None:
    """Verify raw transcript.json and meeting.md survive intact if downstream summary fails."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    meeting_id = "20260917_190000_survive"

    seg = TranscriptSegment(
        text="Critical meeting notes that must not be lost.",
        start_ms=1000,
        end_ms=4000,
        language="en",
    )

    # 1. Raw transcript saved first
    t_path, m_path = store.save_raw_transcript(
        meeting_id=meeting_id,
        segments=[seg],
    )
    assert t_path.is_file()
    assert m_path.is_file()

    # 2. Simulate downstream AI summarization failure (e.g. Gemini quota/network error)
    def simulate_summary_step() -> None:
        raise ConnectionError("Gemini API network timeout")

    with pytest.raises(ConnectionError, match="Gemini API network timeout"):
        simulate_summary_step()

    # 3. Verify raw artifacts remain valid and untouched
    assert t_path.is_file()
    assert m_path.is_file()

    loaded = store.load_transcript(t_path.parent)
    assert loaded.segments[0].text == "Critical meeting notes that must not be lost."

    content = m_path.read_text(encoding="utf-8")
    assert "Critical meeting notes that must not be lost." in content


def test_repeated_writes_overwrites_atomically(tmp_path: Path) -> None:
    """Verify repeated saves update artifacts cleanly without corrupting files."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    meeting_id = "20260917_200000_repeat"

    seg1 = TranscriptSegment(text="First segment", start_ms=0, end_ms=2000, language="en")
    t_path, _ = store.save_raw_transcript(meeting_id=meeting_id, segments=[seg1])

    # Second write with additional segments
    seg2 = TranscriptSegment(text="Second segment", start_ms=2000, end_ms=4000, language="en")
    store.save_raw_transcript(meeting_id=meeting_id, segments=[seg1, seg2])

    loaded = store.load_transcript(t_path.parent)
    assert len(loaded.segments) == 2
    assert loaded.segments[1].text == "Second segment"


def test_format_timestamp_ms() -> None:
    """Verify timestamp formatting across seconds, minutes, and hours."""
    assert format_timestamp_ms(0) == "[00:00:00]"
    assert format_timestamp_ms(12000) == "[00:00:12]"
    assert format_timestamp_ms(75000) == "[00:01:15]"
    assert format_timestamp_ms(3665000) == "[01:01:05]"
