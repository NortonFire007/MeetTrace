"""Tests for persisting and retrieving AI meeting summaries without altering raw transcripts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from meettrace.storage.models import TranscriptSegment
from meettrace.storage.repository import MeetingRepository
from meettrace.storage.store import MeetingArtifactStore
from meettrace.summary.models import MeetingSummary


def test_save_summary_persists_json_and_markdown_without_mutating_raw_transcript(
    tmp_path: Path,
) -> None:
    """Verify save_summary adds summary to transcript.json and meeting.md while preserving raw segments."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 14, 30, 0, tzinfo=UTC)
    mid = "meeting_summary_persist_test"

    segments = [
        TranscriptSegment(
            text="First speaker: We need to agree on the database schema.",
            start_ms=0,
            end_ms=4500,
            language="en",
        ),
        TranscriptSegment(
            text="Second speaker: Yes, we will use JSON and SQLite.",
            start_ms=5000,
            end_ms=10000,
            language="en",
        ),
    ]

    # 1. Initial raw save
    json_path, md_path = store.save_raw_transcript(
        meeting_id=mid,
        segments=segments,
        started_at=dt,
        title="Architecture Discussion",
        source="Google Meet",
    )

    with open(json_path, "r", encoding="utf-8") as f:
        initial_json = json.load(f)

    assert "summary" not in initial_json or initial_json["summary"] is None
    assert len(initial_json["segments"]) == 2

    # 2. Persist AI Summary
    summary_obj = MeetingSummary(
        summary="Team aligned on database design using SQLite and JSON.",
        decisions=("Adopt SQLite for local cache",),
        action_items=("Write schema migration", "Implement store tests"),
        open_questions=("Do we need Postgres later?",),
        follow_ups=("Review benchmark on Friday",),
    )

    res_json_path, res_md_path = store.save_summary(mid, summary_obj)
    assert res_json_path == json_path
    assert res_md_path == md_path

    # 3. Verify transcript.json integrity
    with open(json_path, "r", encoding="utf-8") as f:
        updated_json = json.load(f)

    assert "summary" in updated_json
    assert updated_json["summary"]["summary"] == summary_obj.summary
    assert updated_json["summary"]["decisions"] == ["Adopt SQLite for local cache"]
    assert updated_json["summary"]["action_items"] == [
        "Write schema migration",
        "Implement store tests",
    ]

    # Verify raw segments were NOT mutated or reordered
    assert updated_json["segments"] == initial_json["segments"]
    assert updated_json["metadata"]["segment_count"] == 2

    # 4. Verify meeting.md contains summary sections before ## Transcript
    md_content = md_path.read_text(encoding="utf-8")
    assert "## Summary" in md_content
    assert "Team aligned on database design" in md_content
    assert "## Decisions" in md_content
    assert "- Adopt SQLite for local cache" in md_content
    assert "## Action Items" in md_content
    assert "## Open Questions" in md_content
    assert "## Follow-ups" in md_content
    assert "## Transcript" in md_content

    # Check order: Summary occurs BEFORE Transcript
    summary_idx = md_content.index("## Summary")
    transcript_idx = md_content.index("## Transcript")
    assert summary_idx < transcript_idx

    # Raw transcript content intact
    assert "[00:00:00] First speaker: We need to agree on the database schema." in md_content
    assert "[00:00:05] Second speaker: Yes, we will use JSON and SQLite." in md_content

    # 5. Verify repository retrieval
    repo.refresh()
    retrieved_summary = repo.get_summary(mid)
    assert retrieved_summary is not None
    assert retrieved_summary.summary == summary_obj.summary
    assert retrieved_summary.decisions == summary_obj.decisions
    assert retrieved_summary.action_items == summary_obj.action_items


def test_regenerate_summary_replaces_old_summary_cleanly(tmp_path: Path) -> None:
    """Verify regenerating a summary overwrites previous summary without duplicates in meeting.md."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    dt = datetime(2026, 9, 17, 15, 0, 0, tzinfo=UTC)
    mid = "meeting_regenerate_test"

    store.save_raw_transcript(
        meeting_id=mid,
        segments=[TranscriptSegment("Discussion item.", 0, 3000, "en")],
        started_at=dt,
        title="Regen Meeting",
    )

    # First summary
    sum1 = MeetingSummary(
        summary="First version of summary.",
        decisions=("Initial decision",),
    )
    store.save_summary(mid, sum1)

    # Second summary (regeneration)
    sum2 = MeetingSummary(
        summary="Updated second version of summary.",
        decisions=("Revised decision",),
        action_items=("New action",),
    )
    _, md_path = store.save_summary(mid, sum2)

    md_content = md_path.read_text(encoding="utf-8")
    # Must only have one ## Summary and one ## Decisions
    assert md_content.count("## Summary") == 1
    assert md_content.count("## Decisions") == 1
    assert "Updated second version of summary." in md_content
    assert "First version of summary." not in md_content
    assert "- Revised decision" in md_content
    assert "- Initial decision" not in md_content
    assert "## Transcript" in md_content
