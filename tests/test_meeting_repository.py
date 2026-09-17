"""Unit tests for MeetingRepository indexing, metadata extraction, sorting, and filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meettrace.storage import (
    MeetingArtifactStore,
    MeetingRepository,
    PersistedSegment,
    parse_frontmatter_and_title,
)
from meettrace.transcription.models import TranscriptMetadata, TranscriptSegment


def test_parse_frontmatter_and_title() -> None:
    """Verify parsing frontmatter and title heading from markdown content."""
    md_content = """---
meeting_id: 20260917_103200_abc12345
started_at: 2026-09-17T10:32:00+00:00
ended_at: 2026-09-17T11:14:00+00:00
duration: 00:42:00
languages: [ru, en]
schema_version: 1.0.0
---

# Architecture Discussion

## Transcript

[00:00:12] Good morning everyone...
"""
    fm, title = parse_frontmatter_and_title(md_content)
    assert title == "Architecture Discussion"
    assert fm["meeting_id"] == "20260917_103200_abc12345"
    assert fm["started_at"] == "2026-09-17T10:32:00+00:00"
    assert fm["duration"] == "00:42:00"
    assert fm["languages"] == "ru, en"


def test_repository_empty_storage_root(tmp_path: Path) -> None:
    """Verify repository handles empty or non-existent storage root gracefully."""
    empty_dir = tmp_path / "non_existent"
    repo = MeetingRepository(storage_root=empty_dir)
    assert repo.list_meetings() == []
    assert repo.get_meeting("any_id") is None
    assert repo.get_transcript("any_id") is None
    assert repo.get_meeting_markdown("any_id") is None


def test_repository_discovers_and_sorts_newest_first(tmp_path: Path) -> None:
    """Verify discovery of multiple meetings across date hierarchies sorted newest first."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    # 1. Old meeting: Sep 15, 2026 09:00
    dt1 = datetime(2026, 9, 15, 9, 0, 0, tzinfo=UTC)
    m1_id = "20260915_090000_11111111"
    store.save_raw_transcript(
        meeting_id=m1_id,
        segments=[TranscriptSegment("Old meeting notes.", 0, 3000, "en")],
        transcript_metadata=TranscriptMetadata(
            dominant_language="en",
            detected_languages={"en": 1.0},
            total_duration_ms=3000,
        ),
        started_at=dt1,
        title="Old Discussion",
        source="Google Meet",
    )

    # 2. Recent meeting: Sep 17, 2026 14:00
    dt2 = datetime(2026, 9, 17, 14, 0, 0, tzinfo=UTC)
    m2_id = "20260917_140000_22222222"
    store.save_raw_transcript(
        meeting_id=m2_id,
        segments=[TranscriptSegment("Recent meeting discussion.", 0, 6000, "ru")],
        transcript_metadata=TranscriptMetadata(
            dominant_language="ru",
            detected_languages={"ru": 1.0},
            total_duration_ms=6000,
        ),
        started_at=dt2,
        title="Recent Standup",
        source={"platform": "google-meet"},
    )

    # 3. Very recent meeting: Sep 17, 2026 16:30
    dt3 = datetime(2026, 9, 17, 16, 30, 0, tzinfo=UTC)
    m3_id = "20260917_163000_33333333"
    store.save_raw_transcript(
        meeting_id=m3_id,
        segments=[
            TranscriptSegment("Latest sprint review.", 0, 10000, "uk"),
            TranscriptSegment("Все працює чудово.", 10000, 20000, "uk"),
        ],
        transcript_metadata=TranscriptMetadata(
            dominant_language="uk",
            detected_languages={"uk": 1.0},
            total_duration_ms=20000,
        ),
        started_at=dt3,
        title="Sprint Review",
        source="Zoom",
    )

    meetings = repo.list_meetings()
    assert len(meetings) == 3

    # Sorted newest-first
    assert meetings[0].meeting_id == m3_id
    assert meetings[0].title == "Sprint Review"
    assert meetings[0].dominant_language == "uk"
    assert meetings[0].segment_count == 2

    assert meetings[1].meeting_id == m2_id
    assert meetings[1].title == "Recent Standup"
    assert meetings[1].dominant_language == "ru"

    assert meetings[2].meeting_id == m1_id
    assert meetings[2].title == "Old Discussion"


def test_repository_gracefully_ignores_corrupt_directories(tmp_path: Path) -> None:
    """Verify corrupted JSON and malformed directories do not crash discovery."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    # Valid meeting
    dt = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    store.save_raw_transcript(
        meeting_id="20260917_120000_good",
        segments=[PersistedSegment("Good transcript.", 0, 5000, "en")],
        started_at=dt,
        title="Valid Meeting",
    )

    # Empty directory (no files)
    empty_dir = tmp_path / "2026" / "09" / "17" / "empty_dir"
    empty_dir.mkdir(parents=True, exist_ok=True)

    # Corrupt directory: invalid transcript.json without meeting.md
    corrupt_dir = tmp_path / "2026" / "09" / "17" / "corrupt_dir"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    (corrupt_dir / "transcript.json").write_text("{corrupt json", encoding="utf-8")

    # Corrupt transcript.json BUT valid meeting.md -> should still recover
    semi_corrupt_dir = tmp_path / "2026" / "09" / "17" / "semi_corrupt"
    semi_corrupt_dir.mkdir(parents=True, exist_ok=True)
    (semi_corrupt_dir / "transcript.json").write_text("invalid json", encoding="utf-8")
    (semi_corrupt_dir / "meeting.md").write_text(
        "---\nmeeting_id: semi_corrupt\nstarted_at: 2026-09-17T11:00:00+00:00\n---\n# Recovered Title\n",
        encoding="utf-8",
    )

    meetings = repo.list_meetings()
    meeting_ids = [m.meeting_id for m in meetings]

    assert "20260917_120000_good" in meeting_ids
    assert "semi_corrupt" in meeting_ids
    assert "corrupt_dir" not in meeting_ids
    assert "empty_dir" not in meeting_ids


def test_repository_filtering_and_pagination(tmp_path: Path) -> None:
    """Verify case-insensitive search filtering across title, languages, platform, and pagination."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)

    store.save_raw_transcript(
        meeting_id="20260917_100000_arch",
        segments=[TranscriptSegment("Architecture discussions.", 0, 2000, "ru")],
        transcript_metadata=TranscriptMetadata(dominant_language="ru"),
        started_at=dt,
        title="Architecture Discussion",
        source="Google Meet",
    )

    store.save_raw_transcript(
        meeting_id="20260917_110000_plan",
        segments=[TranscriptSegment("Sprint planning.", 0, 2000, "en")],
        transcript_metadata=TranscriptMetadata(dominant_language="en"),
        started_at=dt,
        title="Sprint Planning",
        source="Slack Huddle",
    )

    store.save_raw_transcript(
        meeting_id="20260917_120000_ukr",
        segments=[TranscriptSegment("Демонстрація функціоналу.", 0, 2000, "uk")],
        transcript_metadata=TranscriptMetadata(dominant_language="uk"),
        started_at=dt,
        title="Демо системи",
        source="Google Meet",
    )

    # Filter by title
    res = repo.list_meetings(search_query="Architecture")
    assert len(res) == 1
    assert res[0].title == "Architecture Discussion"

    # Filter by Cyrillic title
    res_cyrillic = repo.list_meetings(search_query="демо")
    assert len(res_cyrillic) == 1
    assert res_cyrillic[0].title == "Демо системи"

    # Filter by platform
    res_platform = repo.list_meetings(search_query="Google Meet")
    assert len(res_platform) == 2

    # Filter by language
    res_lang = repo.list_meetings(search_query="uk")
    assert len(res_lang) == 1
    assert res_lang[0].dominant_language == "uk"

    # Pagination: limit and offset
    all_three = repo.list_meetings()
    assert len(all_three) == 3

    page1 = repo.list_meetings(limit=2, offset=0)
    assert len(page1) == 2

    page2 = repo.list_meetings(limit=2, offset=2)
    assert len(page2) == 1


def test_repository_get_transcript_and_markdown(tmp_path: Path) -> None:
    """Verify loading structured PersistedTranscript and exact meeting.md content."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    mid = "20260917_100000_detail"

    seg = TranscriptSegment("Exact persisted text.", 12000, 18000, "en")
    store.save_raw_transcript(
        meeting_id=mid,
        segments=[seg],
        transcript_metadata=TranscriptMetadata(dominant_language="en"),
        started_at=dt,
        title="Detail Test",
    )

    # 1. get_meeting metadata
    meta = repo.get_meeting(mid)
    assert meta is not None
    assert meta.title == "Detail Test"

    # 2. get_transcript
    transcript = repo.get_transcript(mid)
    assert transcript is not None
    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "Exact persisted text."
    assert transcript.segments[0].start_ms == 12000

    # 3. get_meeting_markdown
    md = repo.get_meeting_markdown(mid)
    assert md is not None
    assert "# Detail Test" in md
    assert "[00:00:12] Exact persisted text." in md

    # 4. get_meeting_dir
    meeting_dir = repo.get_meeting_dir(mid)
    assert meeting_dir is not None
    assert (meeting_dir / "meeting.md").is_file()
