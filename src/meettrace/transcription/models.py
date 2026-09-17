"""Transcription domain models and configuration for MeetTrace.

Provides backend-agnostic immutable data structures representing timestamped
segments, meeting transcript metadata, configurations, and errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    """Word-level timing information within a transcript segment.

    Attributes:
        word: The spoken word text.
        start_ms: Monotonic millisecond offset from session start when the word begins.
        end_ms: Monotonic millisecond offset from session start when the word ends.
        probability: Model confidence probability between 0.0 and 1.0.
    """

    word: str
    start_ms: int
    end_ms: int
    probability: float = 1.0

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be non-negative, got {self.start_ms}.")
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) cannot be less than start_ms ({self.start_ms})."
            )


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Discrete, immutable timestamped transcript segment emitted by transcribers.

    Attributes:
        text: The transcribed speech text.
        start_ms: Start time offset in milliseconds relative to session start.
        end_ms: End time offset in milliseconds relative to session start.
        language: Detected or configured language code (e.g., 'en', 'ru', 'uk').
        confidence: Average segment confidence probability (0.0 to 1.0) if provided.
        words: Optional word-level timing details.
    """

    text: str
    start_ms: int
    end_ms: int
    language: str
    confidence: float | None = None
    words: tuple[TranscriptWord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("TranscriptSegment text must be a string.")
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be non-negative, got {self.start_ms}.")
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) cannot be less than start_ms ({self.start_ms})."
            )
        if not self.language:
            raise ValueError("language code must not be empty.")


@dataclass(frozen=True, slots=True)
class TranscriptMetadata:
    """Aggregated metadata for a completed or ongoing meeting transcript.

    Attributes:
        session_id: Unique session identifier or None.
        dominant_language: Most frequently detected language across segments.
        detected_languages: Mapping of language codes to their occurrence probability or count.
        model_name: Model identifier used for inference (e.g. 'faster-whisper:base').
        total_duration_ms: Total audio duration processed in milliseconds.
        segment_count: Total count of transcript segments produced.
        created_at: ISO-8601 formatted timestamp when the transcript was initiated.
    """

    session_id: str | None = None
    dominant_language: str | None = None
    detected_languages: dict[str, float] = field(default_factory=dict)
    model_name: str = "faster-whisper:base"
    total_duration_ms: int = 0
    segment_count: int = 0
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class TranscriptionConfig:
    """Configuration for local transcription inference and windowing.

    Attributes:
        model_size: Whisper model size ('tiny', 'base', 'small', 'medium', 'large-v3').
        device: Hardware device to run inference on ('cpu', 'cuda', 'auto').
        compute_type: Computation precision ('int8', 'float16', 'float32', 'default').
        language: Explicit language code ('en', 'ru', 'uk') or None for automatic detection.
        window_duration_sec: Window size in seconds for audio buffer accumulation (15-30s).
        beam_size: Beam search width for decoding (default 5).
        vad_filter: Whether to enable Silero VAD filtering to suppress non-speech intervals.
    """

    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    window_duration_sec: float = 20.0
    beam_size: int = 5
    vad_filter: bool = True

    def __post_init__(self) -> None:
        if self.window_duration_sec <= 0:
            raise ValueError(
                f"window_duration_sec must be positive, got {self.window_duration_sec}."
            )
        if self.beam_size < 1:
            raise ValueError(f"beam_size must be at least 1, got {self.beam_size}.")


class TranscriptionErrorCategory(StrEnum):
    """Categorization of transcription subsystem errors."""

    MODEL_LOAD = "model_load"
    INFERENCE = "inference"
    AUDIO_NORMALIZATION = "audio_normalization"
    GENERAL = "general"


@dataclass(frozen=True)
class TranscriptionError(Exception):
    """Structured error emitted when transcription fails or encounters an issue.

    Attributes:
        message: Human-readable error description.
        category: Error classification.
        fatal: Whether this error prevents further transcription.
        underlying_exception: Original Python exception, if any.
        timestamp_ms: Monotonic millisecond offset when the error occurred.
    """

    message: str
    category: TranscriptionErrorCategory | str = TranscriptionErrorCategory.GENERAL
    fatal: bool = True
    underlying_exception: Exception | None = None
    timestamp_ms: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def __str__(self) -> str:
        cat_name = self.category.value if hasattr(self.category, "value") else str(self.category)
        sev = "FATAL" if self.fatal else "WARNING"
        result = f"[{sev}][{cat_name}] {self.message}"
        if self.underlying_exception is not None:
            cause = type(self.underlying_exception).__name__
            result = f"{result} (Caused by: {cause}: {self.underlying_exception})"
        return result
