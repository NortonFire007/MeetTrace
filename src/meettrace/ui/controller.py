"""Recording session controller coordinating audio capture, state, and timer.

Provides high-level actions (start, pause, resume, stop, toggle), maintains
elapsed meeting time, guards against invalid user actions, and synchronizes UI
state with AudioCaptureService events.
"""

from __future__ import annotations

import logging
from typing import Final

from PySide6.QtCore import QObject, QTimer, Signal

from meettrace.capture.models import (
    CaptureError,
    CaptureErrorCategory,
    CaptureState,
    DeviceChangeEvent,
)
from meettrace.capture.protocol import AudioCapture
from meettrace.ui.bridge import AudioCaptureQtBridge
from meettrace.ui.state import (
    can_pause_recording,
    can_resume_recording,
    can_start_recording,
    can_stop_recording,
)

logger = logging.getLogger(__name__)

TIMER_INTERVAL_MS: Final[int] = 1000


def format_duration(total_seconds: int) -> str:
    """Format total seconds into MM:SS or HH:MM:SS for longer sessions."""
    total_seconds = max(total_seconds, 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class RecordingSessionController(QObject):
    """Coordinates recording lifecycle actions and provides UI-ready Qt signals."""

    state_changed = Signal(CaptureState)
    elapsed_time_changed = Signal(int, str)  # (seconds, formatted_string)
    error_occurred = Signal(CaptureError)
    device_changed = Signal(DeviceChangeEvent)

    def __init__(
        self,
        capture_service: AudioCapture,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture_service = capture_service
        self._state: CaptureState = capture_service.state
        self._elapsed_seconds: int = 0
        self._last_error: CaptureError | None = None

        # Elapsed time timer
        self._timer = QTimer(self)
        self._timer.setInterval(TIMER_INTERVAL_MS)
        self._timer.timeout.connect(self._on_timer_tick)

        # Thread-safe Qt bridge connecting to capture observer
        self._bridge = AudioCaptureQtBridge(self)
        self._bridge.state_changed.connect(self._on_backend_state_changed)
        self._bridge.error_occurred.connect(self._on_backend_error_occurred)
        self._bridge.device_changed.connect(self.device_changed.emit)

        self._capture_service.add_observer(self._bridge)

    @property
    def state(self) -> CaptureState:
        """Current operational state of the recording session."""
        return self._state

    @property
    def elapsed_seconds(self) -> int:
        """Elapsed meeting time in seconds."""
        return self._elapsed_seconds

    @property
    def formatted_elapsed_time(self) -> str:
        """Formatted meeting time string (MM:SS or HH:MM:SS)."""
        return format_duration(self._elapsed_seconds)

    @property
    def last_error(self) -> CaptureError | None:
        """Most recent capture error or None."""
        return self._last_error

    def start(self) -> None:
        """Start audio recording session.

        Guards against invalid invocation if session is already active.
        """
        if not can_start_recording(self._state):
            logger.warning(
                "Ignoring start() action; current state is %s",
                self._state.value,
            )
            return

        self._last_error = None
        try:
            self._capture_service.start()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Failed to start audio capture service")
            error = CaptureError(
                message=str(exc) or "Failed to start audio recording.",
                fatal=True,
                category=CaptureErrorCategory.INITIALIZATION,
                underlying_exception=exc,
            )
            self._on_backend_error_occurred(error)
            self._set_state(CaptureState.ERROR)

    def pause(self) -> None:
        """Pause the ongoing recording session."""
        if not can_pause_recording(self._state):
            logger.warning("Ignoring pause() action; current state is %s", self._state.value)
            return

        try:
            self._capture_service.pause()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Failed to pause audio capture")
            self._handle_action_exception("Failed to pause audio recording.", exc)

    def resume(self) -> None:
        """Resume the paused recording session."""
        if not can_resume_recording(self._state):
            logger.warning("Ignoring resume() action; current state is %s", self._state.value)
            return

        try:
            self._capture_service.resume()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Failed to resume audio capture")
            self._handle_action_exception("Failed to resume audio recording.", exc)

    def toggle_pause(self) -> None:
        """Toggle between paused and recording states."""
        if self._state == CaptureState.PAUSED:
            self.resume()
        elif self._state in (CaptureState.RECORDING, CaptureState.REBINDING):
            self.pause()

    def stop(self) -> None:
        """Stop the active recording session."""
        if not can_stop_recording(self._state):
            logger.warning("Ignoring stop() action; current state is %s", self._state.value)
            return

        try:
            self._capture_service.stop()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Failed to stop audio capture")
            self._handle_action_exception("Failed to stop audio recording.", exc)

    def cleanup(self) -> None:
        """Unregister observers and stop active timers."""
        self._timer.stop()
        try:
            self._capture_service.remove_observer(self._bridge)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("Error unregistering observer during cleanup: %s", exc)

    def _on_timer_tick(self) -> None:
        """Handle 1-second timer tick while recording is active."""
        self._elapsed_seconds += 1
        self.elapsed_time_changed.emit(
            self._elapsed_seconds,
            format_duration(self._elapsed_seconds),
        )

    def _set_state(self, new_state: CaptureState) -> None:
        """Update internal state, manage timer, and emit state_changed signal."""
        if self._state == new_state:
            return

        previous_state = self._state
        self._state = new_state
        logger.info(
            "RecordingSessionController state transition: %s -> %s", previous_state, new_state
        )

        # Manage timer lifecycle according to new state
        if new_state == CaptureState.RECORDING:
            if previous_state != CaptureState.PAUSED and previous_state != CaptureState.REBINDING:
                self._elapsed_seconds = 0
                self.elapsed_time_changed.emit(0, format_duration(0))
            if not self._timer.isActive():
                self._timer.start()

        elif new_state == CaptureState.REBINDING:
            # Temporary audio handover sub-state: keep timer ticking
            if not self._timer.isActive():
                self._timer.start()

        elif new_state == CaptureState.PAUSED:
            # Freeze timer while paused
            if self._timer.isActive():
                self._timer.stop()

        elif new_state in (CaptureState.STOPPED, CaptureState.IDLE):
            # Stop and reset timer
            if self._timer.isActive():
                self._timer.stop()
            self._elapsed_seconds = 0
            self.elapsed_time_changed.emit(0, format_duration(0))

        elif new_state == CaptureState.ERROR:
            if self._timer.isActive():
                self._timer.stop()

        self.state_changed.emit(new_state)

    def _on_backend_state_changed(self, state: CaptureState) -> None:
        """Receive state changes from the capture service via Qt bridge."""
        self._set_state(state)

    def _on_backend_error_occurred(self, error: CaptureError) -> None:
        """Receive capture errors and emit to UI."""
        self._last_error = error
        logger.error("Capture error received in controller: %s", error)
        self.error_occurred.emit(error)

    def _handle_action_exception(self, message: str, exc: Exception) -> None:
        """Create structured error for user action failure and notify UI."""
        error = CaptureError(
            message=f"{message} ({exc})",
            fatal=False,
            category=CaptureErrorCategory.GENERAL,
            underlying_exception=exc,
        )
        self._on_backend_error_occurred(error)
