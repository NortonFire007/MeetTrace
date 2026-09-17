"""Unit tests for TranscriptionService pipeline and lifecycle."""

from __future__ import annotations

from typing import Any

import numpy as np

from meettrace.capture.models import AudioChunk, CaptureState
from meettrace.transcription.models import (
    TranscriptionConfig,
    TranscriptionError,
    TranscriptMetadata,
    TranscriptSegment,
)
from meettrace.transcription.protocol import BaseTranscriptionObserver, Transcriber
from meettrace.transcription.service import TranscriptionService


class DummyTranscriber(Transcriber):
    """Mock Transcriber for pipeline testing."""

    def __init__(self, language: str = "en") -> None:
        self._language = language
        self.transcribe_calls: list[dict[str, Any]] = []
        self.fail_transcribe: Exception | None = None
        self.is_closed = False

    def load_model(self) -> None:
        pass

    @property
    def is_loaded(self) -> bool:
        return True

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        start_offset_ms: int = 0,
        language: str | None = None,
    ) -> list[TranscriptSegment]:
        self.transcribe_calls.append(
            {
                "audio_len": len(audio),
                "start_offset_ms": start_offset_ms,
                "language": language,
            }
        )
        if self.fail_transcribe is not None:
            raise self.fail_transcribe

        duration_ms = round(len(audio) / 16.0)
        return [
            TranscriptSegment(
                text=f"Segment at {start_offset_ms}",
                start_ms=start_offset_ms,
                end_ms=start_offset_ms + duration_ms,
                language=language or self._language,
                confidence=0.95,
            )
        ]

    def detect_language(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        return (self._language, 0.99)

    def close(self) -> None:
        self.is_closed = True


class RecordingTranscriptionObserver(BaseTranscriptionObserver):
    """Observer capturing emitted segments, errors, and completion events."""

    def __init__(self) -> None:
        self.segments: list[TranscriptSegment] = []
        self.errors: list[TranscriptionError] = []
        self.completed_metadata: TranscriptMetadata | None = None

    def on_segment(self, segment: TranscriptSegment) -> None:
        self.segments.append(segment)

    def on_error(self, error: TranscriptionError) -> None:
        self.errors.append(error)

    def on_completed(self, metadata: TranscriptMetadata) -> None:
        self.completed_metadata = metadata


def test_transcription_service_pipeline() -> None:
    """Verify AudioChunks flow through buffer and worker to produce segments and completion metadata."""
    transcriber = DummyTranscriber(language="ru")
    config = TranscriptionConfig(window_duration_sec=0.5)  # 500ms window for fast test
    service = TranscriptionService(transcriber=transcriber, config=config)

    observer = RecordingTranscriptionObserver()
    service.add_observer(observer)

    # 1. Start recording
    service.on_state_changed(CaptureState.RECORDING)

    # 2. Feed two chunks (300ms each = 600ms total >= 500ms window)
    pcm_300ms = (b"\x00\x08") * int(16000 * 0.3)
    chunk1 = AudioChunk(
        source="mic",
        data=pcm_300ms,
        timestamp_ms=0,
        duration_ms=300,
        sample_rate=16000,
        channels=1,
    )
    chunk2 = AudioChunk(
        source="loopback",
        data=pcm_300ms,
        timestamp_ms=300,
        duration_ms=300,
        sample_rate=16000,
        channels=1,
    )

    service.on_audio_chunk(chunk1)
    service.on_audio_chunk(chunk2)

    # 3. Stop recording (flushes remaining 100ms)
    service.on_state_changed(CaptureState.STOPPED)

    # Verify segments were produced and accumulated
    assert len(observer.segments) >= 1
    assert observer.segments[0].language == "ru"
    assert len(service.segments) == len(observer.segments)

    # Verify completion metadata
    assert observer.completed_metadata is not None
    assert observer.completed_metadata.dominant_language == "ru"
    assert observer.completed_metadata.segment_count == len(observer.segments)

    service.close()


def test_transcription_service_error_handling() -> None:
    """Verify transcription errors are reported to observers without crashing the worker."""
    transcriber = DummyTranscriber()
    transcriber.fail_transcribe = RuntimeError("Model execution error")

    config = TranscriptionConfig(window_duration_sec=0.2)
    service = TranscriptionService(transcriber=transcriber, config=config)

    observer = RecordingTranscriptionObserver()
    service.add_observer(observer)

    service.on_state_changed(CaptureState.RECORDING)

    # Send 150ms of audio (flushed on stop)
    pcm = (b"\x00\x08") * int(16000 * 0.15)
    chunk = AudioChunk(
        source="mic",
        data=pcm,
        timestamp_ms=0,
        duration_ms=150,
        sample_rate=16000,
        channels=1,
    )
    service.on_audio_chunk(chunk)
    service.stop()

    assert len(observer.errors) >= 1
    assert "Model execution error" in observer.errors[0].message

    service.close()


def test_transcription_service_cancellation() -> None:
    """Verify cancel() drains pending tasks and stops the background thread immediately."""
    transcriber = DummyTranscriber()
    config = TranscriptionConfig(window_duration_sec=10.0)
    service = TranscriptionService(transcriber=transcriber, config=config)

    service.start()
    assert service._worker_thread is not None and service._worker_thread.is_alive()

    service.cancel()
    assert service._worker_thread is None

    service.close()
