"""Unit and UI tests for MeetingListView and MeetingReaderView."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication

from meettrace.storage import MeetingArtifactStore, MeetingRepository
from meettrace.transcription.models import TranscriptMetadata, TranscriptSegment
from meettrace.ui.views.meeting_list_view import (
    MeetingListView,
    format_meeting_duration,
    get_date_group_key,
)
from meettrace.ui.views.meeting_reader_view import (
    MeetingReaderView,
    format_meeting_date_long,
)


def test_format_meeting_duration() -> None:
    """Verify meeting duration formatting for various millisecond durations."""
    assert format_meeting_duration(0) == "0 min"
    assert format_meeting_duration(30000) == "1 min"  # <60s rounded to min
    assert format_meeting_duration(2520000) == "42 min"  # 42 * 60 * 1000
    assert format_meeting_duration(3600000) == "1h"  # exactly 1h
    assert format_meeting_duration(4320000) == "1h 12m"  # 1h 12m


def test_get_date_group_key() -> None:
    """Verify date grouping into Today, Yesterday, and Older."""
    now_utc = datetime.now(UTC)
    today_iso = now_utc.isoformat()
    yesterday_iso = (now_utc - timedelta(days=1)).isoformat()
    older_iso = (now_utc - timedelta(days=5)).isoformat()

    assert get_date_group_key(today_iso) == "Today"
    assert get_date_group_key(yesterday_iso) == "Yesterday"
    assert get_date_group_key(older_iso) == "Older"
    assert get_date_group_key("") == "Older"


def test_format_meeting_date_long() -> None:
    """Verify date formatting to 'Month Day, Year'."""
    dt_str = "2026-09-17T15:30:00+00:00"
    formatted = format_meeting_date_long(dt_str)
    assert "Sep" in formatted
    assert "2026" in formatted


def test_meeting_list_view_empty_state(qtbot, tmp_path: Path) -> None:
    """Verify empty state is displayed when no meetings exist."""
    repo = MeetingRepository(storage_root=tmp_path)
    view = MeetingListView(repository=repo)
    qtbot.addWidget(view)
    view.show()

    # The layout should contain the empty state container
    assert view._list_layout.count() == 1


def test_meeting_list_view_rendering_and_selection(qtbot, tmp_path: Path) -> None:
    """Verify meeting cards rendering, date grouping, and selection signal emission."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    now_utc = datetime.now(UTC)
    yesterday_utc = now_utc - timedelta(days=1)

    # 1. Today meeting
    store.save_raw_transcript(
        meeting_id="today_meeting_1",
        segments=[TranscriptSegment("Architecture discussion today.", 0, 10000, "ru")],
        transcript_metadata=TranscriptMetadata(dominant_language="ru"),
        started_at=now_utc,
        title="Architecture Discussion",
        source="Google Meet",
    )

    # 2. Yesterday meeting
    store.save_raw_transcript(
        meeting_id="yesterday_meeting_2",
        segments=[TranscriptSegment("Design review yesterday.", 0, 5000, "en")],
        transcript_metadata=TranscriptMetadata(dominant_language="en"),
        started_at=yesterday_utc,
        title="Design Review",
        source="Zoom",
    )

    view = MeetingListView(repository=repo)
    qtbot.addWidget(view)
    view.show()

    # Layout should contain 2 section headers + 2 meeting cards = 4 items
    assert view._list_layout.count() == 4

    # Test selection signal
    selected_ids: list[str] = []
    view.meeting_selected.connect(selected_ids.append)

    # Find first MeetingCardWidget
    card = None
    for i in range(view._list_layout.count()):
        item = view._list_layout.itemAt(i)
        w = item.widget()
        if hasattr(w, "_metadata") and w._metadata.meeting_id == "today_meeting_1":
            card = w
            break

    assert card is not None
    # Simulate clicking card
    card.clicked.emit("today_meeting_1")
    assert selected_ids == ["today_meeting_1"]


def test_meeting_list_view_search_filtering(qtbot, tmp_path: Path) -> None:
    """Verify searching filters the meetings dynamically in real time."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    store.save_raw_transcript(
        meeting_id="m_arch",
        segments=[TranscriptSegment("Architecture notes.", 0, 1000, "en")],
        title="Architecture Discussion",
    )
    store.save_raw_transcript(
        meeting_id="m_retro",
        segments=[TranscriptSegment("Sprint retrospective.", 0, 1000, "en")],
        title="Sprint Retrospective",
    )

    view = MeetingListView(repository=repo)
    qtbot.addWidget(view)
    view.show()

    # Initially both meetings displayed
    meetings = repo.list_meetings()
    assert len(meetings) == 2

    # Filter for 'Retro'
    view.search_input.setText("Retro")
    # Should only show Sprint Retrospective
    matching = repo.list_meetings(search_query="Retro")
    assert len(matching) == 1
    assert matching[0].title == "Sprint Retrospective"

    # Filter with non-matching query
    view.search_input.setText("NonExistentMeeting")
    # Empty search state should be shown
    assert view._list_layout.count() == 1


def test_meeting_reader_view_transcript_and_unicode(qtbot, tmp_path: Path) -> None:
    """Verify reader loads meeting, renders timestamps and preserves exact Unicode (RU/EN/UK)."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    mid = "unicode_multilingual_meeting"

    segments = [
        TranscriptSegment("Good morning everyone, let's start.", 0, 4500, "en"),
        TranscriptSegment("Давайте начнем с архитектуры и хранилища данных.", 4500, 12000, "ru"),
        TranscriptSegment(
            "Доброго дня! Обговоримо підтримку української мови та реліз.",
            12000,
            24000,
            "uk",
        ),
    ]

    store.save_raw_transcript(
        meeting_id=mid,
        segments=segments,
        transcript_metadata=TranscriptMetadata(
            dominant_language="ru",
            detected_languages={"en": 1.0, "ru": 1.0, "uk": 1.0},
            total_duration_ms=24000,
        ),
        started_at=dt,
        title="Multilingual Tech Review",
        source="Google Meet",
    )

    reader = MeetingReaderView(repository=repo)
    qtbot.addWidget(reader)
    reader.show()

    reader.load_meeting(mid)

    # Check header title & subtitle
    assert reader._title_label.text() == "Multilingual Tech Review"
    assert "Google Meet" in reader._subtitle_label.text()
    assert "Sep 17, 2026" in reader._subtitle_label.text()

    # Check rendered HTML in QTextBrowser
    html_text = reader.transcript_browser.toHtml()
    assert "[00:00:00]" in html_text
    assert "Good morning everyone, let's start." in html_text

    # Russian Cyrillic
    assert "[00:00:04]" in html_text
    assert "Давайте начнем с архитектуры и хранилища данных." in html_text

    # Ukrainian Cyrillic
    assert "[00:00:12]" in html_text
    assert "Доброго дня! Обговоримо підтримку української мови та реліз." in html_text


def test_meeting_reader_view_copy_markdown_and_open_folder(qtbot, tmp_path: Path) -> None:
    """Verify copy markdown copies exact meeting.md content and open folder operates safely."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    mid = "copy_action_meeting"

    seg = TranscriptSegment("Verifying clipboard copy.", 0, 5000, "en")
    _, md_path = store.save_raw_transcript(
        meeting_id=mid,
        segments=[seg],
        started_at=dt,
        title="Copy Action Test",
    )

    reader = MeetingReaderView(repository=repo)
    qtbot.addWidget(reader)
    reader.show()

    reader.load_meeting(mid)

    # Trigger Copy Markdown
    reader.copy_button.click()

    clipboard = QApplication.clipboard()
    copied_text = clipboard.text()

    expected_md = md_path.read_text(encoding="utf-8")
    assert copied_text == expected_md
    assert "# Copy Action Test" in copied_text
    assert "[00:00:00] Verifying clipboard copy." in copied_text
    assert reader.copy_button.text() == "✓ Copied!"

    # Trigger Open Folder (should not raise any exception)
    reader.open_folder_button.click()

    # Trigger Back button
    back_emitted = False

    def on_back() -> None:
        nonlocal back_emitted
        back_emitted = True

    reader.back_requested.connect(on_back)
    reader.back_button.click()
    assert back_emitted
