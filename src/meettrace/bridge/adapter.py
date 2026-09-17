"""Thread-safe Qt adapter bridging HTTP server worker threads to PySide6 signals."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from meettrace.bridge.models import MeetEventPayload, MeetEventType, MeetMetadata

logger = logging.getLogger(__name__)


class MeetBridgeQtAdapter(QObject):
    """Bridges HTTP worker thread events to Qt's event loop via signals.

    Guarantees that UI widgets and Qt controllers are never touched directly
    from HTTP server worker threads.
    """

    meeting_detected = Signal(object)  # MeetMetadata
    meeting_started = Signal(object)  # MeetMetadata
    meeting_ended = Signal(object)  # MeetMetadata
    heartbeat_received = Signal(object)  # MeetMetadata
    bridge_status_changed = Signal(bool, str)  # (is_active, status_message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._last_metadata: MeetMetadata | None = None
        self._last_event_type: MeetEventType | None = None
        self._is_active: bool = False

    @property
    def last_metadata(self) -> MeetMetadata | None:
        """Return the most recently received meeting metadata."""
        return self._last_metadata

    @property
    def last_event_type(self) -> MeetEventType | None:
        """Return the most recent event type."""
        return self._last_event_type

    def handle_event(self, payload: MeetEventPayload) -> None:
        """Receive validated event from HTTP server thread and emit queued Qt signal.

        Args:
            payload: Validated MeetEventPayload instance.
        """
        self._last_metadata = payload.meeting
        self._last_event_type = payload.event
        logger.info(
            "Bridge adapter received event %s for meeting code '%s'",
            payload.event.value,
            payload.meeting.meeting_code or "n/a",
        )

        if payload.event == MeetEventType.MEETING_DETECTED:
            self.meeting_detected.emit(payload.meeting)
        elif payload.event == MeetEventType.MEETING_STARTED:
            self.meeting_started.emit(payload.meeting)
        elif payload.event == MeetEventType.MEETING_ENDED:
            self.meeting_ended.emit(payload.meeting)
        elif payload.event == MeetEventType.HEARTBEAT:
            self.heartbeat_received.emit(payload.meeting)

    def set_bridge_status(self, is_active: bool, message: str) -> None:
        """Update and emit bridge status."""
        self._is_active = is_active
        self.bridge_status_changed.emit(is_active, message)
