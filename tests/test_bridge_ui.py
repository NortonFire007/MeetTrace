"""Automated UI tests for the Google Meet bridge chip, Settings card, and App wiring."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from meettrace.bridge.models import MeetMetadata
from meettrace.capture.models import CaptureState
from meettrace.capture.protocol import AudioCapture
from meettrace.storage.repository import MeetingRepository
from meettrace.ui.app import MeetTraceApp
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.toolbar import FloatingRecordingToolbar
from meettrace.ui.views.settings_view import SettingsView


class StubAudioCapture(AudioCapture):
    """Stub AudioCapture implementation for UI tests."""

    def __init__(self) -> None:
        self._state = CaptureState.IDLE
        self._observers: list[Any] = []

    @property
    def state(self) -> CaptureState:
        return self._state

    def start(self) -> None:
        self._state = CaptureState.RECORDING
        for obs in self._observers:
            obs.on_state_changed(CaptureState.RECORDING)

    def stop(self) -> None:
        self._state = CaptureState.STOPPED
        for obs in self._observers:
            obs.on_state_changed(CaptureState.STOPPED)

    def pause(self) -> None:
        self._state = CaptureState.PAUSED
        for obs in self._observers:
            obs.on_state_changed(CaptureState.PAUSED)

    def resume(self) -> None:
        self._state = CaptureState.RECORDING
        for obs in self._observers:
            obs.on_state_changed(CaptureState.RECORDING)

    def add_observer(self, observer: Any) -> None:
        self._observers.append(observer)

    def remove_observer(self, observer: Any) -> None:
        if observer in self._observers:
            self._observers.remove(observer)


@pytest.fixture
def stub_capture() -> StubAudioCapture:
    return StubAudioCapture()


@pytest.fixture
def controller(stub_capture: StubAudioCapture, qapp) -> RecordingSessionController:
    return RecordingSessionController(stub_capture)


@pytest.fixture
def toolbar(controller: RecordingSessionController, qtbot) -> FloatingRecordingToolbar:
    tb = FloatingRecordingToolbar(controller)
    qtbot.addWidget(tb)
    return tb


def test_toolbar_meet_chip_states(
    toolbar: FloatingRecordingToolbar, controller: RecordingSessionController
):
    # Initial state: bridge not connected
    assert toolbar.meet_chip.text() == "Meet: Standby"
    assert "Not detected" in toolbar.meet_chip.toolTip()

    # Bridge status updated to connected
    controller.on_bridge_status_changed(True, "Active on port 38281")
    QCoreApplication.processEvents()
    assert toolbar.meet_chip.text() == "Meet: Ready"
    assert "Connected" in toolbar.meet_chip.toolTip()

    # Meeting metadata arrives
    meta = MeetMetadata(
        url="https://meet.google.com/xyz-uvwx-rst",
        title="Product Review",
        meeting_code="xyz-uvwx-rst",
    )
    controller.on_meeting_started(meta)
    QCoreApplication.processEvents()
    assert "Meet (xyz-uvwx-rst)" in toolbar.meet_chip.text()
    assert "Product Review" in toolbar.meet_chip.toolTip()
    assert "https://meet.google.com/xyz-uvwx-rst" in toolbar.meet_chip.toolTip()


def test_toolbar_collapse_toggles_meet_chip(toolbar: FloatingRecordingToolbar):
    toolbar.show()
    assert toolbar.meet_chip.isVisible() is True
    toolbar.toggle_collapse()
    assert toolbar.is_collapsed is True
    assert toolbar.meet_chip.isVisible() is False
    toolbar.toggle_collapse()
    assert toolbar.is_collapsed is False
    assert toolbar.meet_chip.isVisible() is True


def test_settings_view_bridge_card(tmp_path, qapp, qtbot):
    settings_view = SettingsView(storage_root=tmp_path)
    qtbot.addWidget(settings_view)

    # Token input should be read-only and masked initially
    token_input = settings_view.token_input
    assert token_input.isReadOnly() is True
    assert len(token_input.text()) >= 32

    # Test copy token to clipboard
    clipboard = QApplication.clipboard()
    settings_view._copy_token_to_clipboard()
    assert clipboard.text() == token_input.text()

    # Test status updates
    settings_view.set_bridge_status(True, "Active on 127.0.0.1:38281")
    assert "Active" in settings_view.bridge_status_label.text()

    settings_view.set_bridge_status(False, "Port 38281 unavailable")
    assert "unavailable" in settings_view.bridge_status_label.text()


def test_app_wiring_with_bridge(tmp_path, qapp):
    repo = MeetingRepository(storage_root=tmp_path)
    capture = StubAudioCapture()

    # Initialize app with start_bridge=False for deterministic test isolation
    app = MeetTraceApp(
        capture_service=capture,
        repository=repo,
        start_bridge=False,
        qapp=qapp,
    )

    assert app.bridge_server is not None
    assert app.bridge_adapter is not None
    assert app.controller is not None

    status = app._get_bridge_status()
    assert status["recording_state"] == "idle"
    assert status["has_meet_context"] is False

    # Clean shutdown
    app.exit()
