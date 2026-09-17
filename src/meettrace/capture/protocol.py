"""Protocols and interfaces for the MeetTrace audio capture subsystem.

Defines the backend-agnostic contracts for audio capture services and
event/stream observers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from meettrace.capture.models import (
    AudioChunk,
    CaptureError,
    CaptureState,
    DeviceChangeEvent,
)


@runtime_checkable
class AudioCaptureObserver(Protocol):
    """Observer interface for receiving audio chunks and lifecycle events."""

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        """Handle a newly captured discrete audio chunk.

        Args:
            chunk: The immutable timestamped audio segment.
        """
        ...

    def on_state_changed(self, state: CaptureState) -> None:
        """Handle a state transition in the capture subsystem.

        Args:
            state: The new operational state.
        """
        ...

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        """Handle a default audio endpoint change event.

        Args:
            event: Metadata regarding the new or switched audio device.
        """
        ...

    def on_error(self, error: CaptureError) -> None:
        """Handle an error or warning emitted by the capture subsystem.

        Args:
            error: Structured capture error details.
        """
        ...


class BaseAudioCaptureObserver:
    """Convenience base class providing no-op default implementations.

    Subclasses may override only the event methods they are interested in.
    Instances conform to the AudioCaptureObserver protocol.
    """

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        """Default no-op handler for audio chunks."""

    def on_state_changed(self, state: CaptureState) -> None:
        """Default no-op handler for state changes."""

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        """Default no-op handler for device changes."""

    def on_error(self, error: CaptureError) -> None:
        """Default no-op handler for errors."""


@runtime_checkable
class AudioCapture(Protocol):
    """Backend-agnostic audio capture contract.

    Encapsulates microphone and system audio loopback capture without exposing
    hardware-specific details, device indexes, or platform libraries.
    """

    def start(self) -> None:
        """Start audio capture for both microphone and system audio streams."""
        ...

    def stop(self) -> None:
        """Stop audio capture and finalize active streams."""
        ...

    def pause(self) -> None:
        """Temporarily pause chunk emission without destroying device streams."""
        ...

    def resume(self) -> None:
        """Resume chunk emission after pause."""
        ...

    @property
    def state(self) -> CaptureState:
        """Current operational state of the capture subsystem."""
        ...

    def add_observer(self, observer: AudioCaptureObserver) -> None:
        """Register an observer for audio chunks and lifecycle events.

        Args:
            observer: The observer to register.
        """
        ...

    def remove_observer(self, observer: AudioCaptureObserver) -> None:
        """Unregister an existing observer.

        Args:
            observer: The observer to remove.
        """
        ...
