"""Automated tests for Google Meet bridge controller and metadata association."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication

from meettrace.bridge.adapter import MeetBridgeQtAdapter
from meettrace.bridge.models import MeetEventPayload, MeetEventType, MeetMetadata
from meettrace.capture.models import CaptureState
from meettrace.capture.protocol import AudioCapture
from meettrace.ui.controller import RecordingSessionController


class FakeAudioCapture(AudioCapture):
    """Fake audio capture engine for deterministic controller testing."""

    def __init__(self, initial_state: CaptureState = CaptureState.IDLE) -> None:
        self._state = initial_state
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
def fake_capture() -> FakeAudioCapture:
    return FakeAudioCapture()


@pytest.fixture
def controller(fake_capture: FakeAudioCapture, qapp) -> RecordingSessionController:
    return RecordingSessionController(fake_capture)


@pytest.fixture
def sample_meet_metadata() -> MeetMetadata:
    return MeetMetadata(
        url="https://meet.google.com/abc-defg-hij",
        title="Weekly Sync",
        meeting_code="abc-defg-hij",
        detected_at="2026-09-17T14:30:00Z",
        browser="chrome",
    )


def test_meeting_detected_sets_pending_context(controller, sample_meet_metadata):
    events: list[MeetMetadata | None] = []
    controller.meet_context_changed.connect(events.append)

    controller.on_meeting_detected(sample_meet_metadata)
    assert len(events) == 1
    assert controller.pending_meet_context == sample_meet_metadata
    assert controller.current_meet_context is None

    # When recording starts, pending metadata is adopted
    controller.start()
    assert controller.state == CaptureState.RECORDING
    assert controller.current_meet_context == sample_meet_metadata
    assert controller.pending_meet_context is None
    assert controller.session_meet_metadata == sample_meet_metadata

    metadata_dict = controller.get_session_metadata()
    assert metadata_dict["title"] == "Weekly Sync"
    assert metadata_dict["source"]["platform"] == "google-meet"
    assert metadata_dict["source"]["meeting_code"] == "abc-defg-hij"


def test_meeting_started_while_recording_attaches_immediately(controller, sample_meet_metadata):
    # Start manual recording first
    controller.start()
    assert controller.state == CaptureState.RECORDING
    assert controller.current_meet_context is None

    # Receive MEETING_STARTED mid-recording
    events = []
    controller.meet_context_changed.connect(events.append)
    controller.on_meeting_started(sample_meet_metadata)

    assert len(events) == 1
    assert controller.current_meet_context == sample_meet_metadata
    assert controller.session_meet_metadata == sample_meet_metadata

    session_data = controller.get_session_metadata()
    assert session_data["title"] == "Weekly Sync"
    assert session_data["source"]["url"] == "https://meet.google.com/abc-defg-hij"


def test_meeting_ended_does_not_abort_recording(controller, sample_meet_metadata):
    # Active recording with Google Meet attached
    controller.start()
    controller.on_meeting_started(sample_meet_metadata)
    assert controller.state == CaptureState.RECORDING

    ended_metadata = MeetMetadata(
        url="https://meet.google.com/abc-defg-hij",
        title="Weekly Sync",
        meeting_code="abc-defg-hij",
        detected_at="2026-09-17T15:00:00Z",
    )

    # Browser signals MEETING_ENDED
    controller.on_meeting_ended(ended_metadata)

    # Invariant: Recording MUST NOT stop automatically solely because Meet ended
    assert controller.state == CaptureState.RECORDING
    assert controller.session_meet_metadata == ended_metadata

    # User manually stops recording when desired
    controller.stop()
    assert controller.state == CaptureState.STOPPED


def test_manual_recording_works_without_bridge(controller):
    # Manual fallback guarantee: no bridge events ever received
    assert controller.bridge_connected is False
    assert controller.current_meet_context is None

    controller.start()
    assert controller.state == CaptureState.RECORDING

    controller.pause()
    assert controller.state == CaptureState.PAUSED

    controller.resume()
    assert controller.state == CaptureState.RECORDING

    controller.stop()
    assert controller.state == CaptureState.STOPPED

    metadata = controller.get_session_metadata()
    assert metadata["title"] == "Meeting"
    assert metadata["source"]["platform"] == "manual"


def test_bridge_qt_adapter_routes_events_to_qt_signals(controller, sample_meet_metadata, qapp):
    adapter = MeetBridgeQtAdapter()
    adapter.meeting_started.connect(controller.on_meeting_started)
    adapter.meeting_ended.connect(controller.on_meeting_ended)

    payload_started = MeetEventPayload(
        event=MeetEventType.MEETING_STARTED,
        meeting=sample_meet_metadata,
    )
    # Simulate HTTP thread passing validated payload to adapter
    adapter.handle_event(payload_started)
    QCoreApplication.processEvents()

    assert controller.current_meet_context == sample_meet_metadata
    assert adapter.last_event_type == MeetEventType.MEETING_STARTED

    payload_ended = MeetEventPayload(
        event=MeetEventType.MEETING_ENDED,
        meeting=sample_meet_metadata,
    )
    adapter.handle_event(payload_ended)
    QCoreApplication.processEvents()

    assert adapter.last_event_type == MeetEventType.MEETING_ENDED
