"""Protocols and interfaces for the transcription subsystem.

Defines the backend-agnostic Transcriber contract and observer listener protocols.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from meettrace.transcription.models import (
    TranscriptionError,
    TranscriptMetadata,
    TranscriptSegment,
)


@runtime_checkable
class Transcriber(Protocol):
    """Backend-agnostic contract for local speech-to-text engines."""

    def load_model(self) -> None:
        """Explicitly initialize and load model weights into memory."""
        ...

    @property
    def is_loaded(self) -> bool:
        """True if the underlying model has been loaded and is ready for inference."""
        ...

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        start_offset_ms: int = 0,
        language: str | None = None,
    ) -> list[TranscriptSegment]:
        """Transcribe an audio array into ordered timestamped segments.

        Args:
            audio: 1D float32 numpy array normalized to [-1.0, 1.0].
            sample_rate: Sample rate in Hz (must be 16000 for standard Whisper).
            start_offset_ms: Session offset in ms corresponding to audio[0].
            language: Optional explicit language code ('en', 'ru', 'uk') or None for auto.

        Returns:
            List of chronologically ordered TranscriptSegment instances.
        """
        ...

    def detect_language(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        """Detect the dominant spoken language from an audio array.

        Returns:
            Tuple of (language_code, probability).
        """
        ...

    def close(self) -> None:
        """Release any allocated model resources and unbind hardware handles."""
        ...


@runtime_checkable
class TranscriptionObserver(Protocol):
    """Listener interface for transcription events."""

    def on_segment(self, segment: TranscriptSegment) -> None:
        """Invoked when a new transcript segment is produced."""
        ...

    def on_error(self, error: TranscriptionError) -> None:
        """Invoked when a transcription or normalization error occurs."""
        ...

    def on_completed(self, metadata: TranscriptMetadata) -> None:
        """Invoked when transcription for a recording session is completed."""
        ...


class BaseTranscriptionObserver:
    """Default no-op implementation of TranscriptionObserver."""

    def on_segment(self, segment: TranscriptSegment) -> None:
        pass

    def on_error(self, error: TranscriptionError) -> None:
        pass

    def on_completed(self, metadata: TranscriptMetadata) -> None:
        pass
