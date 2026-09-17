"""Unit tests for RecordingSessionController and AudioCaptureQtBridge."""

from __future__ import annotations

from meettrace.capture.models import (
    CaptureError,
    CaptureErrorCategory,
    CaptureState,
    DeviceChangeEvent,
)
from meettrace.capture.protocol import AudioCapture, AudioCaptureObserver
from meettrace.ui.controller import RecordingSessionController, format_duration


class DummyAudioCapture(AudioCapture):
    """Mock AudioCapture protocol implementation for controller tests."""

    def __init__(self, initial_state: CaptureState = CaptureState.IDLE) -> None:
        self._state = initial_state
        self.observers: list[AudioCaptureObserver] = []
        self.start_called = 0
        self.stop_called = 0
        self.pause_called = 0
        self.resume_called = 0
        self.fail_start_with: Exception | None = None

    @property
    def state(self) -> CaptureState:
        return self._state

    def add_observer(self, observer: AudioCaptureObserver) -> None:
        self.observers.append(observer)

    def remove_observer(self, observer: AudioCaptureObserver) -> None:
        if observer in self.observers:
            self.observers.remove(observer)

    def start(self) -> None:
        self.start_called += 1
        if self.fail_start_with is not None:
            raise self.fail_start_with
        self.emit_state(CaptureState.RECORDING)

    def stop(self) -> None:
        self.stop_called += 1
        self.emit_state(CaptureState.STOPPED)

    def pause(self) -> None:
        self.pause_called += 1
        self.emit_state(CaptureState.PAUSED)

    def resume(self) -> None:
        self.resume_called += 1
        self.emit_state(CaptureState.RECORDING)

    def emit_state(self, new_state: CaptureState) -> None:
        self._state = new_state
        for obs in list(self.observers):
            obs.on_state_changed(new_state)

    def emit_error(self, error: CaptureError) -> None:
        for obs in list(self.observers):
            obs.on_error(error)

    def emit_device_change(self, event: DeviceChangeEvent) -> None:
        for obs in list(self.observers):
            obs.on_device_changed(event)


def test_format_duration() -> None:
    """Verify meeting duration string formatting for seconds, minutes, and hours."""
    assert format_duration(0) == "00:00"
    assert format_duration(9) == "00:09"
    assert format_duration(59) == "00:59"
    assert format_duration(60) == "01:00"
    assert format_duration(65) == "01:05"
    assert format_duration(3599) == "59:59"
    assert format_duration(3600) == "01:00:00"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(-10) == "00:00"


def test_controller_start_pause_resume_stop() -> None:
    """Verify standard recording session lifecycle transitions and observer synchronization."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)

    state_transitions: list[CaptureState] = []
    controller.state_changed.connect(state_transitions.append)

    # 1. Start
    assert controller.state == CaptureState.IDLE
    controller.start()
    assert capture.start_called == 1
    assert controller.state == CaptureState.RECORDING

    # 2. Pause
    controller.pause()
    assert capture.pause_called == 1
    assert controller.state == CaptureState.PAUSED

    # 3. Resume via toggle_pause
    controller.toggle_pause()
    assert capture.resume_called == 1
    assert controller.state == CaptureState.RECORDING

    # 4. Stop
    controller.stop()
    assert capture.stop_called == 1
    assert controller.state == CaptureState.STOPPED
    assert controller.elapsed_seconds == 0

    assert state_transitions == [
        CaptureState.RECORDING,
        CaptureState.PAUSED,
        CaptureState.RECORDING,
        CaptureState.STOPPED,
    ]
    controller.cleanup()


def test_controller_elapsed_timer_ticks(qtbot) -> None:
    """Verify 1-second elapsed timer ticks and time formatting emissions."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)

    times: list[tuple[int, str]] = []
    controller.elapsed_time_changed.connect(lambda sec, fmt: times.append((sec, fmt)))

    controller.start()
    assert controller.state == CaptureState.RECORDING
    assert controller.elapsed_seconds == 0

    # Simulate timer tick manually
    controller._on_timer_tick()
    assert controller.elapsed_seconds == 1
    assert controller.formatted_elapsed_time == "00:01"

    controller._on_timer_tick()
    assert controller.elapsed_seconds == 2
    assert controller.formatted_elapsed_time == "00:02"

    assert (1, "00:01") in times
    assert (2, "00:02") in times

    controller.cleanup()


def test_controller_invalid_actions_guarded() -> None:
    """Verify invalid user actions are ignored gracefully without exceptions."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)

    # In IDLE: pause, resume, stop should be ignored
    controller.pause()
    assert capture.pause_called == 0

    controller.resume()
    assert capture.resume_called == 0

    controller.stop()
    assert capture.stop_called == 0

    # Start recording
    controller.start()
    assert capture.start_called == 1

    # While RECORDING: calling start again should be ignored
    controller.start()
    assert capture.start_called == 1

    controller.cleanup()


def test_controller_error_propagation() -> None:
    """Verify backend errors propagate to Qt signals and controller properties."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)

    received_errors: list[CaptureError] = []
    controller.error_occurred.connect(received_errors.append)

    err = CaptureError(
        message="Device disconnected unexpectedly",
        fatal=True,
        category=CaptureErrorCategory.DEVICE_UNAVAILABLE,
    )
    capture.emit_error(err)

    assert len(received_errors) == 1
    assert received_errors[0].message == "Device disconnected unexpectedly"
    assert controller.last_error == err

    controller.cleanup()


def test_controller_start_exception_handling() -> None:
    """Verify start() exceptions transition to ERROR state and emit error_occurred."""
    capture = DummyAudioCapture()
    capture.fail_start_with = OSError("No audio devices detected")
    controller = RecordingSessionController(capture)

    received_errors: list[CaptureError] = []
    controller.error_occurred.connect(received_errors.append)

    controller.start()

    assert controller.state == CaptureState.ERROR
    assert len(received_errors) == 1
    assert "No audio devices detected" in received_errors[0].message

    controller.cleanup()
