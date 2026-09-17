"""Recording session controller coordinating audio capture, state, and timer.

Provides high-level actions (start, pause, resume, stop, toggle), maintains
elapsed meeting time, guards against invalid user actions, and synchronizes UI
state with AudioCaptureService events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import QObject, QTimer, Signal

from meettrace.bridge.models import MeetMetadata
from meettrace.capture.models import (
    CaptureError,
    CaptureErrorCategory,
    CaptureState,
    DeviceChangeEvent,
)
from meettrace.capture.protocol import AudioCapture
from meettrace.storage.writer import generate_meeting_id
from meettrace.ui.bridge import AudioCaptureQtBridge
from meettrace.ui.state import (
    can_pause_recording,
    can_resume_recording,
    can_start_recording,
    can_stop_recording,
)

if TYPE_CHECKING:
    from meettrace.storage.repository import MeetingRepository
    from meettrace.storage.store import MeetingArtifactStore
    from meettrace.transcription.models import TranscriptMetadata, TranscriptSegment
    from meettrace.transcription.service import TranscriptionService

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
    meet_context_changed = Signal(object)  # MeetMetadata | None
    bridge_status_changed = Signal(bool, str)  # (is_connected, message)
    meeting_saved = Signal(str)  # Emits meeting_id when artifacts are durably persisted

    def __init__(
        self,
        capture_service: AudioCapture,
        transcription_service: TranscriptionService | None = None,
        artifact_store: MeetingArtifactStore | None = None,
        repository: MeetingRepository | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture_service = capture_service
        self._transcription_service = transcription_service
        self._artifact_store = artifact_store
        self._repository = repository
        self._session_start_time: datetime | None = None

        self._state: CaptureState = capture_service.state
        self._elapsed_seconds: int = 0
        self._last_error: CaptureError | None = None

        # Google Meet bridge and context tracking
        self._current_meet_context: MeetMetadata | None = None
        self._pending_meet_context: MeetMetadata | None = None
        self._session_meet_metadata: MeetMetadata | None = None
        self._bridge_connected: bool = False
        self._bridge_status_message: str = "Not detected"

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
        self._session_start_time = datetime.now(UTC)

        # Associate pending or existing Meet metadata with this recording session
        if self._pending_meet_context is not None and self._current_meet_context is None:
            self._current_meet_context = self._pending_meet_context
            self._pending_meet_context = None

        if self._current_meet_context is not None:
            self._session_meet_metadata = self._current_meet_context
            self.meet_context_changed.emit(self._current_meet_context)

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
        """Stop the active recording session and persist meeting artifacts."""
        if not can_stop_recording(self._state):
            logger.warning("Ignoring stop() action; current state is %s", self._state.value)
            return

        try:
            self._capture_service.stop()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Failed to stop audio capture")
            self._handle_action_exception("Failed to stop audio recording.", exc)

        if self._artifact_store is not None:
            self._save_session_artifacts()

    def _save_session_artifacts(self) -> str | None:
        """Persist transcript and markdown artifacts for the completed session."""
        if self._artifact_store is None:
            return None

        try:
            started_at = self._session_start_time or datetime.now(UTC)
            ended_at = datetime.now(UTC)
            mid = generate_meeting_id(started_at)
            session_meta = self.get_session_metadata()

            segments: list[TranscriptSegment] = []
            meta: TranscriptMetadata | None = None
            if self._transcription_service is not None:
                self._transcription_service.stop()
                segments = self._transcription_service.segments
                meta = getattr(self._transcription_service, "last_metadata", None)

            json_path, md_path = self._artifact_store.save_raw_transcript(
                meeting_id=mid,
                segments=segments,
                transcript_metadata=meta,
                started_at=started_at,
                ended_at=ended_at,
                title=session_meta["title"],
                source=session_meta["source"],
            )
            logger.info("Session artifacts saved cleanly [%s]: %s, %s", mid, json_path, md_path)

            if self._repository is not None:
                self._repository.refresh()

            self.meeting_saved.emit(mid)
            return mid
        except Exception:
            logger.exception("Failed to persist session artifacts")
            return None

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

    # -------------------------------------------------------------------------
    # Google Meet Bridge Lifecycle & Metadata
    # -------------------------------------------------------------------------
    @property
    def current_meet_context(self) -> MeetMetadata | None:
        """Active Google Meet metadata or None."""
        return self._current_meet_context

    @property
    def pending_meet_context(self) -> MeetMetadata | None:
        """Pending Google Meet metadata awaiting recording start or None."""
        return self._pending_meet_context

    @property
    def session_meet_metadata(self) -> MeetMetadata | None:
        """Meeting metadata associated with the current or last session."""
        return self._session_meet_metadata

    @property
    def bridge_connected(self) -> bool:
        """True if the local bridge is active and accepting connections."""
        return self._bridge_connected

    @property
    def bridge_status_message(self) -> str:
        """Human-readable bridge connectivity status."""
        return self._bridge_status_message

    def on_meeting_detected(self, metadata: MeetMetadata) -> None:
        """Handle Google Meet page detection."""
        logger.info(
            "Controller received meeting detected: %s (%s)",
            metadata.title,
            metadata.meeting_code,
        )
        self._pending_meet_context = metadata
        if self._state in (CaptureState.RECORDING, CaptureState.PAUSED, CaptureState.REBINDING):
            self._current_meet_context = metadata
            self._session_meet_metadata = metadata
        self.meet_context_changed.emit(self._current_meet_context or self._pending_meet_context)

    def on_meeting_started(self, metadata: MeetMetadata) -> None:
        """Handle active call entry."""
        logger.info(
            "Controller received meeting started: %s (%s)",
            metadata.title,
            metadata.meeting_code,
        )
        self._current_meet_context = metadata
        self._session_meet_metadata = metadata
        if self._state not in (CaptureState.RECORDING, CaptureState.PAUSED, CaptureState.REBINDING):
            self._pending_meet_context = metadata
        self.meet_context_changed.emit(metadata)

    def on_meeting_ended(self, metadata: MeetMetadata) -> None:
        """Handle call termination or page exit.

        Safe MVP behavior: Never stop recording automatically purely because
        the browser emitted MEETING_ENDED. Recording remains user-directed.
        """
        logger.info(
            "Controller received meeting ended: %s (%s)",
            metadata.title,
            metadata.meeting_code,
        )
        if self._current_meet_context is not None:
            self._session_meet_metadata = metadata
        self._pending_meet_context = None
        self.meet_context_changed.emit(self._current_meet_context)

    def on_bridge_status_changed(self, is_connected: bool, message: str) -> None:
        """Handle updates to bridge server connectivity status."""
        self._bridge_connected = is_connected
        self._bridge_status_message = message
        self.bridge_status_changed.emit(is_connected, message)

    def clear_meet_context(self) -> None:
        """Clear active and pending Google Meet context."""
        self._current_meet_context = None
        self._pending_meet_context = None
        self.meet_context_changed.emit(None)

    def get_session_metadata(self) -> dict[str, Any]:
        """Return metadata dictionary for the current or last completed recording session."""
        if self._session_meet_metadata is not None:
            return {
                "title": self._session_meet_metadata.title,
                "source": {
                    "platform": "google-meet",
                    "url": self._session_meet_metadata.url,
                    "meeting_code": self._session_meet_metadata.meeting_code,
                    "detected_at": self._session_meet_metadata.detected_at,
                    "browser": self._session_meet_metadata.browser,
                },
            }
        return {
            "title": "Meeting",
            "source": {"platform": "manual"},
        }
