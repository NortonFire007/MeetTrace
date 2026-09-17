"""Capture domain models and state definitions for MeetTrace.

This module provides backend-agnostic, immutable data structures representing
audio chunks, device events, capture states, and structured errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class CaptureState(StrEnum):
    """Operational states of the audio capture subsystem."""

    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    REBINDING = "rebinding"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal transition between capture states is attempted."""


# Mapping of permitted state transitions for CaptureState.
VALID_CAPTURE_STATE_TRANSITIONS: dict[CaptureState, frozenset[CaptureState]] = {
    CaptureState.IDLE: frozenset({CaptureState.STARTING}),
    CaptureState.STARTING: frozenset({
        CaptureState.RECORDING,
        CaptureState.STOPPED,
        CaptureState.ERROR,
    }),
    CaptureState.RECORDING: frozenset({
        CaptureState.PAUSED,
        CaptureState.REBINDING,
        CaptureState.STOPPED,
        CaptureState.ERROR,
    }),
    CaptureState.REBINDING: frozenset({
        CaptureState.RECORDING,
        CaptureState.STOPPED,
        CaptureState.ERROR,
    }),
    CaptureState.PAUSED: frozenset({
        CaptureState.RECORDING,
        CaptureState.STOPPED,
        CaptureState.ERROR,
    }),
    CaptureState.STOPPED: frozenset({
        CaptureState.IDLE,
        CaptureState.STARTING,
    }),
    CaptureState.ERROR: frozenset({
        CaptureState.IDLE,
        CaptureState.STARTING,
        CaptureState.STOPPED,
    }),
}


def can_transition(current_state: CaptureState, target_state: CaptureState) -> bool:
    """Return True if transitioning from current_state to target_state is permitted."""
    allowed_targets = VALID_CAPTURE_STATE_TRANSITIONS.get(current_state, frozenset())
    return target_state in allowed_targets


def validate_transition(current_state: CaptureState, target_state: CaptureState) -> None:
    """Validate that transition from current_state to target_state is permitted.

    Raises:
        InvalidStateTransitionError: If the transition is not allowed.
    """
    if not can_transition(current_state, target_state):
        raise InvalidStateTransitionError(
            f"Cannot transition capture state from {current_state.value!r} to {target_state.value!r}"
        )


AudioSource = Literal["mic", "loopback", "mixed"]


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """Discrete, immutable timestamped audio segment emitted by capture engines.

    Attributes:
        source: Origin of the chunk ('mic', 'loopback', or 'mixed').
        data: Raw 16-bit PCM audio samples in bytes.
        timestamp_ms: Monotonic millisecond offset from the start of the recording session.
        duration_ms: Segment duration in milliseconds.
        sample_rate: Sampling frequency in Hz (e.g., 16000, 44100, 48000).
        channels: Number of audio channels (1 for mono, 2 for stereo).
    """

    source: AudioSource
    data: bytes
    timestamp_ms: int
    duration_ms: int
    sample_rate: int
    channels: int

    def __post_init__(self) -> None:
        if self.source not in ("mic", "loopback", "mixed"):
            raise ValueError(
                f"Invalid audio chunk source: {self.source!r}. Must be 'mic', 'loopback', or 'mixed'."
            )
        if not isinstance(self.data, bytes):
            raise TypeError(f"Audio chunk data must be bytes, got {type(self.data).__name__}.")
        if self.timestamp_ms < 0:
            raise ValueError(f"timestamp_ms must be non-negative, got {self.timestamp_ms}.")
        if self.duration_ms < 0:
            raise ValueError(f"duration_ms must be non-negative, got {self.duration_ms}.")
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}.")
        if self.channels not in (1, 2):
            raise ValueError(f"channels must be 1 (mono) or 2 (stereo), got {self.channels}.")


DeviceFlow = Literal["render", "capture"]


@dataclass(frozen=True, slots=True)
class DeviceChangeEvent:
    """Emitted when Windows switches or updates the active audio endpoint.

    Attributes:
        flow: Flow direction ('render' for output/speakers, 'capture' for input/mic).
        endpoint_id: Windows Core Audio endpoint GUID/string.
        friendly_name: Human-readable device name (e.g. 'Headphones (Realtek Audio)').
        timestamp_ms: Millisecond offset from session start when the change was detected.
    """

    flow: DeviceFlow
    endpoint_id: str
    friendly_name: str
    timestamp_ms: int

    def __post_init__(self) -> None:
        if self.flow not in ("render", "capture"):
            raise ValueError(
                f"Invalid device flow: {self.flow!r}. Must be 'render' or 'capture'."
            )
        if not self.endpoint_id:
            raise ValueError("endpoint_id must not be empty.")
        if self.timestamp_ms < 0:
            raise ValueError(f"timestamp_ms must be non-negative, got {self.timestamp_ms}.")


class CaptureErrorCategory(StrEnum):
    """Categorization of capture subsystem errors."""

    INITIALIZATION = "initialization"
    DEVICE_UNAVAILABLE = "device_unavailable"
    STREAM_ERROR = "stream_error"
    REBIND_FAILURE = "rebind_failure"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class CaptureError:
    """Structured capture error or warning delivered to observers.

    Attributes:
        message: Human-readable error explanation.
        fatal: Whether this error prevents further audio capture.
        category: Error category identifying the failure origin.
        underlying_exception: Original Python exception, if available.
        timestamp_ms: Optional millisecond timestamp when the error occurred.
    """

    message: str
    fatal: bool = True
    category: CaptureErrorCategory | str = CaptureErrorCategory.GENERAL
    underlying_exception: Exception | None = None
    timestamp_ms: int | None = None

    def __str__(self) -> str:
        category_name = (
            self.category.value if hasattr(self.category, "value") else str(self.category)
        )
        severity = "FATAL" if self.fatal else "WARNING"
        result = f"[{severity}][{category_name}] {self.message}"
        if self.underlying_exception is not None:
            cause_name = type(self.underlying_exception).__name__
            result = f"{result} (Caused by: {cause_name}: {self.underlying_exception})"
        return result
