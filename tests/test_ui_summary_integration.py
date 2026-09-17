"""Integration and UI tests for Gemini summary generation and reader display."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QSettings

from meettrace.storage.models import TranscriptSegment
from meettrace.storage.repository import MeetingRepository
from meettrace.storage.store import MeetingArtifactStore
from meettrace.summary.models import MeetingSummary
from meettrace.ui.views.meeting_reader_view import MeetingReaderView
from meettrace.ui.views.settings_view import SettingsView


def test_settings_view_persists_gemini_api_key_and_model(qtbot, tmp_path: Path) -> None:
    """Verify entering Gemini API key and selecting model in SettingsView updates QSettings."""
    settings = QSettings("MeetTrace", "MeetTrace")
    settings.clear()

    view = SettingsView(storage_root=tmp_path)
    qtbot.addWidget(view)
    view.show()

    # Enter key
    view.gemini_key_input.setText("AIzaSyTestKey999")
    # Change model to gemini-2.5-pro
    idx = view.gemini_model_combo.findText("gemini-2.5-pro")
    if idx >= 0:
        view.gemini_model_combo.setCurrentIndex(idx)

    assert settings.value("gemini_api_key") == "AIzaSyTestKey999"
    assert settings.value("gemini_model") == "gemini-2.5-pro"


def test_reader_view_displays_generate_and_regenerate_states(qtbot, tmp_path: Path) -> None:
    """Verify reader button says 'Generate' without summary and 'Regenerate' when summary exists."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 16, 0, 0, tzinfo=UTC)
    mid = "reader_summary_state_test"

    store.save_raw_transcript(
        meeting_id=mid,
        segments=[TranscriptSegment("Welcome to the session.", 0, 4000, "en")],
        started_at=dt,
        title="State Test Meeting",
    )

    reader = MeetingReaderView(repository=repo)
    qtbot.addWidget(reader)
    reader.show()

    # Load meeting without summary
    reader.load_meeting(mid)
    assert reader.generate_summary_button.text() == "✨ Generate Summary"
    assert reader.generate_summary_button.isEnabled()

    # Add summary
    summary = MeetingSummary(
        summary="Short summary of the session.",
        decisions=("Proceed with release",),
        action_items=("Verify build",),
    )
    store.save_summary(mid, summary)
    repo.refresh()

    # Reload meeting
    reader.load_meeting(mid)
    assert reader.generate_summary_button.text() == "↻ Regenerate Summary"

    # HTML contains summary elements
    html_content = reader.transcript_browser.toHtml()
    assert "AI SUMMARY" in html_content
    assert "Short summary of the session." in html_content
    assert "Proceed with release" in html_content
    assert "Verify build" in html_content
    assert "Transcript" in html_content


def test_reader_view_shows_error_banner_when_no_api_key(qtbot, tmp_path: Path) -> None:
    """Verify clicking generate button without API key displays an error banner without crashing."""
    settings = QSettings("MeetTrace", "MeetTrace")
    settings.clear()

    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 16, 30, 0, tzinfo=UTC)
    mid = "no_key_test"

    store.save_raw_transcript(
        meeting_id=mid,
        segments=[TranscriptSegment("Meeting segment.", 0, 3000, "en")],
        started_at=dt,
        title="No Key Meeting",
    )

    reader = MeetingReaderView(repository=repo)
    qtbot.addWidget(reader)
    reader.show()

    reader.load_meeting(mid)
    assert not reader.error_banner.isVisible()

    with patch.dict("os.environ", {}, clear=True):
        reader.generate_summary_button.click()

    assert reader.error_banner.isVisible()
    assert "API key" in reader.error_label.text()


def test_reader_view_successful_summary_flow(qtbot, tmp_path: Path) -> None:
    """Verify clicking generate button runs worker, persists summary, and renders cards."""
    settings = QSettings("MeetTrace", "MeetTrace")
    settings.setValue("gemini_api_key", "test-valid-key")

    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC)
    mid = "worker_flow_test"

    store.save_raw_transcript(
        meeting_id=mid,
        segments=[TranscriptSegment("Let's summarize this call.", 0, 3500, "en")],
        started_at=dt,
        title="Worker Flow Meeting",
    )

    reader = MeetingReaderView(repository=repo)
    qtbot.addWidget(reader)
    reader.show()

    reader.load_meeting(mid)

    fake_summary = MeetingSummary(
        summary="Automated meeting summary.",
        decisions=("Approved proposal",),
        action_items=("Merge branch",),
        open_questions=(),
        follow_ups=("QA validation",),
    )

    with patch("meettrace.ui.views.meeting_reader_view.GeminiSummaryProvider") as mock_provider_cls:
        mock_instance = MagicMock()
        mock_instance.generate_summary.return_value = fake_summary
        mock_provider_cls.return_value = mock_instance

        reader.generate_summary_button.click()

        # Wait for worker thread to finish and UI to update
        qtbot.waitUntil(
            lambda: reader.generate_summary_button.text() == "↻ Regenerate Summary",
            timeout=5000,
        )

    # After worker finished, reader should have refreshed and rendered the summary
    assert reader.generate_summary_button.text() == "↻ Regenerate Summary"
    html_content = reader.transcript_browser.toHtml()
    assert "Automated meeting summary." in html_content
    assert "Approved proposal" in html_content
    assert "Merge branch" in html_content
    assert "QA validation" in html_content


def test_reader_view_handles_generation_error(qtbot, tmp_path: Path) -> None:
    """Verify summary failure emits error banner and restores button without data corruption."""
    settings = QSettings("MeetTrace", "MeetTrace")
    settings.setValue("gemini_api_key", "test-key")

    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 17, 30, 0, tzinfo=UTC)
    mid = "error_flow_test"

    store.save_raw_transcript(
        meeting_id=mid,
        segments=[TranscriptSegment("Discussion here.", 0, 2000, "en")],
        started_at=dt,
        title="Error Test Meeting",
    )

    reader = MeetingReaderView(repository=repo)
    qtbot.addWidget(reader)
    reader.show()

    reader.load_meeting(mid)

    from meettrace.summary.models import SummaryQuotaError

    with patch("meettrace.ui.views.meeting_reader_view.GeminiSummaryProvider") as mock_provider_cls:
        mock_instance = MagicMock()
        mock_instance.generate_summary.side_effect = SummaryQuotaError(
            "Gemini API rate limit exceeded"
        )
        mock_provider_cls.return_value = mock_instance

        reader.generate_summary_button.click()

        qtbot.waitUntil(lambda: reader.error_banner.isVisible(), timeout=5000)

    assert reader.error_banner.isVisible()
    assert "rate limit exceeded" in reader.error_label.text()
    assert reader.generate_summary_button.isEnabled()
    assert reader.generate_summary_button.text() == "✨ Generate Summary"
