"""Audio capture subsystem for MeetTrace.

Provides backend-agnostic models, protocols, and dispatcher tools for recording
microphone and system loopback audio.
"""

from meettrace.capture.broadcaster import CaptureObserverBroadcaster
from meettrace.capture.models import (
    VALID_CAPTURE_STATE_TRANSITIONS,
    AudioChunk,
    AudioSource,
    CaptureError,
    CaptureErrorCategory,
    CaptureState,
    DeviceChangeEvent,
    DeviceFlow,
    InvalidStateTransitionError,
    can_transition,
    validate_transition,
)
from meettrace.capture.protocol import (
    AudioCapture,
    AudioCaptureObserver,
    BaseAudioCaptureObserver,
)

__all__ = [
    "VALID_CAPTURE_STATE_TRANSITIONS",
    "AudioCapture",
    "AudioCaptureObserver",
    "AudioChunk",
    "AudioSource",
    "BaseAudioCaptureObserver",
    "CaptureError",
    "CaptureErrorCategory",
    "CaptureObserverBroadcaster",
    "CaptureState",
    "DeviceChangeEvent",
    "DeviceFlow",
    "InvalidStateTransitionError",
    "can_transition",
    "validate_transition",
]
