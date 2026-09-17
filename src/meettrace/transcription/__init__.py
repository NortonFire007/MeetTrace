"""Local multilingual transcription subsystem for MeetTrace.

Provides faster-whisper adapter, audio normalization, timeline-aligned buffering,
and asynchronous transcription service for real-time meeting capture.
"""

from meettrace.transcription.buffer import TimelineAudioBuffer
from meettrace.transcription.models import (
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionErrorCategory,
    TranscriptMetadata,
    TranscriptSegment,
    TranscriptWord,
)
from meettrace.transcription.normalizer import (
    WHISPER_SAMPLE_RATE,
    normalize_chunk_to_16k_mono,
    pcm16_to_float32,
    resample_linear,
)
from meettrace.transcription.protocol import (
    BaseTranscriptionObserver,
    Transcriber,
    TranscriptionObserver,
)
from meettrace.transcription.service import TranscriptionService
from meettrace.transcription.whisper_adapter import FasterWhisperTranscriber

__all__ = [
    "WHISPER_SAMPLE_RATE",
    "BaseTranscriptionObserver",
    "FasterWhisperTranscriber",
    "TimelineAudioBuffer",
    "Transcriber",
    "TranscriptMetadata",
    "TranscriptSegment",
    "TranscriptWord",
    "TranscriptionConfig",
    "TranscriptionError",
    "TranscriptionErrorCategory",
    "TranscriptionObserver",
    "TranscriptionService",
    "normalize_chunk_to_16k_mono",
    "pcm16_to_float32",
    "resample_linear",
]
