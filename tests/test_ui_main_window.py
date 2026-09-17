"""Unit and UI tests for MainWindow navigation, lifecycle, and shell integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication

from meettrace.capture.models import CaptureState
from meettrace.capture.protocol import AudioCapture, AudioCaptureObserver
from meettrace.storage import MeetingArtifactStore, MeetingRepository
from meettrace.transcription.models import TranscriptMetadata, TranscriptSegment
from meettrace.ui.app import MeetTraceApp
from meettrace.ui.main_window import MainWindow


class DummyAudioCapture(AudioCapture):
    """Self-contained mock AudioCapture for main window integration tests."""

    def __init__(self, initial_state: CaptureState = CaptureState.IDLE) -> None:
        self._state = initial_state
        self.observers: list[AudioCaptureObserver] = []

    @property
    def state(self) -> CaptureState:
        return self._state

    def add_observer(self, observer: AudioCaptureObserver) -> None:
        self.observers.append(observer)

    def remove_observer(self, observer: AudioCaptureObserver) -> None:
        if observer in self.observers:
            self.observers.remove(observer)

    def start(self) -> None:
        self._state = CaptureState.RECORDING
        for obs in self.observers:
            obs.on_state_changed(CaptureState.RECORDING)

    def stop(self) -> None:
        self._state = CaptureState.STOPPED
        for obs in self.observers:
            obs.on_state_changed(CaptureState.STOPPED)

    def pause(self) -> None:
        self._state = CaptureState.PAUSED
        for obs in self.observers:
            obs.on_state_changed(CaptureState.PAUSED)

    def resume(self) -> None:
        self._state = CaptureState.RECORDING
        for obs in self.observers:
            obs.on_state_changed(CaptureState.RECORDING)


def test_main_window_sidebar_navigation(qtbot, tmp_path: Path) -> None:
    """Verify switching between Home, Meetings, and Settings tabs via sidebar buttons."""
    repo = MeetingRepository(storage_root=tmp_path)
    window = MainWindow(repository=repo)
    qtbot.addWidget(window)
    window.show()

    # Initially on Meetings (index 1)
    assert window._content_stack.currentIndex() == 1
    assert window._meetings_btn.isChecked()

    # Click Home
    window._home_btn.click()
    assert window._content_stack.currentIndex() == 0
    assert window._home_btn.isChecked()

    # Click Settings
    window._settings_btn.click()
    assert window._content_stack.currentIndex() == 2
    assert window._settings_btn.isChecked()

    # Click Meetings again
    window._meetings_btn.click()
    assert window._content_stack.currentIndex() == 1
    assert window._meetings_stack.currentIndex() == 0  # Should return to list


def test_main_window_flow_list_to_reader_and_back(qtbot, tmp_path: Path) -> None:
    """Verify clicking meeting opens reader, and back button returns to list."""
    store = MeetingArtifactStore(storage_root=tmp_path)
    repo = MeetingRepository(store=store)

    dt = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    mid = "flow_test_meeting"

    store.save_raw_transcript(
        meeting_id=mid,
        segments=[TranscriptSegment("Flow testing line.", 0, 3000, "en")],
        transcript_metadata=TranscriptMetadata(dominant_language="en"),
        started_at=dt,
        title="Flow Test Title",
    )

    window = MainWindow(repository=repo)
    qtbot.addWidget(window)
    window.show()

    # Initially on Meetings list
    assert window._meetings_stack.currentIndex() == 0

    # Open reader
    window.open_meeting_reader(mid)
    assert window._meetings_stack.currentIndex() == 1
    assert window.meeting_reader_view._title_label.text() == "Flow Test Title"

    # Click Back to Meetings
    window.meeting_reader_view.back_button.click()
    assert window._meetings_stack.currentIndex() == 0


def test_main_window_lifecycle_and_close(qtbot, tmp_path: Path) -> None:
    """Verify closing main window does not crash or quit application."""
    repo = MeetingRepository(storage_root=tmp_path)
    window = MainWindow(repository=repo)
    qtbot.addWidget(window)
    window.show()

    assert window.isVisible()

    # Close window
    window.close()
    assert not window.isVisible()


def test_meettrace_app_integration_with_main_window(qtbot, tmp_path: Path) -> None:
    """Verify Tray and Toolbar can open MainWindow, and recording remains available while open."""
    qapp = QApplication.instance() or QApplication([])
    capture = DummyAudioCapture()
    repo = MeetingRepository(storage_root=tmp_path)

    app = MeetTraceApp(capture_service=capture, repository=repo, qapp=qapp)

    try:
        # Initially toolbar is visible, main window is hidden
        app.show_toolbar()
        assert app.toolbar.isVisible()
        assert not app.main_window.isVisible()

        # 1. Open MainWindow via Tray action
        app.tray_manager.open_action.trigger()
        assert app.main_window.isVisible()

        # 2. Main window remains usable while recording starts
        app.controller.start()
        assert app.controller.state == CaptureState.RECORDING
        assert app.main_window.isVisible()
        assert app.toolbar.isVisible()

        # 3. Stop recording while main window is open
        app.controller.stop()
        assert app.controller.state == CaptureState.STOPPED
        assert app.main_window.isVisible()

        # 4. Open MainWindow via Toolbar open history button
        app.main_window.hide()
        assert not app.main_window.isVisible()
        app.toolbar.open_history_button.click()
        assert app.main_window.isVisible()

        # 5. Closing main window leaves toolbar and tray alive
        app.main_window.close()
        assert not app.main_window.isVisible()
        assert app.toolbar.isVisible()
        assert app.tray_manager.tray_icon.isVisible()

    finally:
        app.exit()
