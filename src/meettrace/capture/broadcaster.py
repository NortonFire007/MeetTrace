"""Thread-safe event broadcaster for audio capture observers.

This module provides CaptureObserverBroadcaster to manage observer registration
and safely dispatch audio chunks, state changes, device events, and errors.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meettrace.capture.models import (
        AudioChunk,
        CaptureError,
        CaptureState,
        DeviceChangeEvent,
    )
    from meettrace.capture.protocol import AudioCaptureObserver

logger = logging.getLogger(__name__)


class CaptureObserverBroadcaster:
    """Thread-safe registry and dispatcher for AudioCaptureObserver instances.

    Ensures that observers can be registered, unregistered, and notified concurrently
    across audio worker threads and main/UI threads. Exceptions raised by observers
    are caught and logged to prevent interrupting capture worker loops.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._observers: list[AudioCaptureObserver] = []

    def add_observer(self, observer: AudioCaptureObserver) -> None:
        """Register an observer if not already present.

        Args:
            observer: The observer to register.
        """
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)

    def remove_observer(self, observer: AudioCaptureObserver) -> None:
        """Unregister an observer. No-op if observer is not registered.

        Args:
            observer: The observer to unregister.
        """
        with self._lock:
            try:
                self._observers.remove(observer)
            except ValueError:
                pass

    def clear_observers(self) -> None:
        """Remove all registered observers."""
        with self._lock:
            self._observers.clear()

    @property
    def observers(self) -> tuple[AudioCaptureObserver, ...]:
        """Return a snapshot tuple of currently registered observers."""
        with self._lock:
            return tuple(self._observers)

    def notify_audio_chunk(self, chunk: AudioChunk) -> None:
        """Dispatch an audio chunk to all registered observers.

        Args:
            chunk: The captured audio chunk.
        """
        for observer in self.observers:
            try:
                observer.on_audio_chunk(chunk)
            except Exception:
                logger.exception("Unhandled error in observer %r on_audio_chunk", observer)

    def notify_state_changed(self, state: CaptureState) -> None:
        """Dispatch a capture state change to all registered observers.

        Args:
            state: The new capture state.
        """
        for observer in self.observers:
            try:
                observer.on_state_changed(state)
            except Exception:
                logger.exception("Unhandled error in observer %r on_state_changed", observer)

    def notify_device_changed(self, event: DeviceChangeEvent) -> None:
        """Dispatch a device change event to all registered observers.

        Args:
            event: The device change event details.
        """
        for observer in self.observers:
            try:
                observer.on_device_changed(event)
            except Exception:
                logger.exception("Unhandled error in observer %r on_device_changed", observer)

    def notify_error(self, error: CaptureError) -> None:
        """Dispatch a capture error to all registered observers.

        Args:
            error: The capture error details.
        """
        for observer in self.observers:
            try:
                observer.on_error(error)
            except Exception:
                logger.exception("Unhandled error in observer %r on_error", observer)
