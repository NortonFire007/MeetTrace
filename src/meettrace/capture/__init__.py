"""Audio capture subsystem for MeetTrace.

Provides backend-agnostic models, protocols, workers, and service for recording
microphone and system loopback audio.
"""

from meettrace.capture.backend import (
    AudioBackend,
    AudioStream,
    DeviceEndpointInfo,
    WindowsAudioBackend,
)
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
from meettrace.capture.service import AudioCaptureService
from meettrace.capture.worker import AudioCaptureWorker

__all__ = [
    "VALID_CAPTURE_STATE_TRANSITIONS",
    "AudioBackend",
    "AudioCapture",
    "AudioCaptureObserver",
    "AudioCaptureService",
    "AudioCaptureWorker",
    "AudioChunk",
    "AudioSource",
    "AudioStream",
    "BaseAudioCaptureObserver",
    "CaptureError",
    "CaptureErrorCategory",
    "CaptureObserverBroadcaster",
    "CaptureState",
    "DeviceChangeEvent",
    "DeviceEndpointInfo",
    "DeviceFlow",
    "InvalidStateTransitionError",
    "WindowsAudioBackend",
    "can_transition",
    "validate_transition",
]
