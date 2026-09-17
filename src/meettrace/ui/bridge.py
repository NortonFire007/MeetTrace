"""Thread-safe PySide6 bridge for AudioCaptureObserver events.

Adapts backend AudioCapture observer callbacks (emitted on background capture threads)
into PySide6 signals dispatched safely to the Qt event loop on the main thread.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from meettrace.capture.models import (
    AudioChunk,
    CaptureError,
    CaptureState,
    DeviceChangeEvent,
)
from meettrace.capture.protocol import BaseAudioCaptureObserver

logger = logging.getLogger(__name__)


class AudioCaptureQtBridge(QObject, BaseAudioCaptureObserver):
    """Bridges AudioCaptureObserver callbacks to thread-safe Qt Signals."""

    state_changed = Signal(CaptureState)
    error_occurred = Signal(CaptureError)
    device_changed = Signal(DeviceChangeEvent)
    audio_chunk_received = Signal(AudioChunk)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def on_state_changed(self, state: CaptureState) -> None:
        """Handle state change notification from AudioCapture and emit Qt signal."""
        logger.debug("AudioCaptureQtBridge emitting state_changed -> %s", state.value)
        try:
            self.state_changed.emit(state)
        except RuntimeError:
            pass

    def on_error(self, error: CaptureError) -> None:
        """Handle capture error from AudioCapture and emit Qt signal."""
        logger.debug("AudioCaptureQtBridge emitting error_occurred -> %s", error.message)
        try:
            self.error_occurred.emit(error)
        except RuntimeError:
            pass

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        """Handle device switch notification from AudioCapture and emit Qt signal."""
        logger.debug("AudioCaptureQtBridge emitting device_changed -> %s", event.friendly_name)
        try:
            self.device_changed.emit(event)
        except RuntimeError:
            pass

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        """Handle audio chunk from AudioCapture and emit Qt signal."""
        try:
            self.audio_chunk_received.emit(chunk)
        except RuntimeError:
            pass
