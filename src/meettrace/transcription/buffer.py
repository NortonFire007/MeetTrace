"""Timeline-aligned audio buffer for mixing dual-stream meeting audio.

Accumulates asynchronous mic and loopback AudioChunk events into a unified
16kHz mono timeline, handles clock offsets and device-rebind gaps, and extracts
configurable 15-30s windows for Whisper inference.
"""

from __future__ import annotations

import logging
import threading
from typing import Final

import numpy as np

from meettrace.capture.models import AudioChunk
from meettrace.transcription.normalizer import (
    WHISPER_SAMPLE_RATE,
    normalize_chunk_to_16k_mono,
)

logger = logging.getLogger(__name__)

MS_TO_SAMPLES: Final[float] = WHISPER_SAMPLE_RATE / 1000.0  # 16 samples per millisecond


class TimelineAudioBuffer:
    """Timestamp-aware rolling audio buffer combining mic and loopback streams."""

    def __init__(self, window_duration_sec: float = 20.0) -> None:
        if window_duration_sec <= 0:
            raise ValueError(f"window_duration_sec must be positive, got {window_duration_sec}.")

        self._window_duration_sec = window_duration_sec
        self._window_samples = round(window_duration_sec * WHISPER_SAMPLE_RATE)
        self._window_duration_ms = round(window_duration_sec * 1000)

        self._lock = threading.Lock()
        self._window_start_ms: int = 0
        self._buffer = np.zeros(0, dtype=np.float32)
        self._max_observed_timestamp_ms: int = 0

    @property
    def window_duration_sec(self) -> float:
        """Window duration threshold in seconds."""
        return self._window_duration_sec

    @property
    def window_start_ms(self) -> int:
        """Current starting timestamp offset of the buffer in milliseconds."""
        with self._lock:
            return self._window_start_ms

    def add_chunk(self, chunk: AudioChunk) -> list[tuple[np.ndarray, int, int]]:
        """Add an AudioChunk to the timeline and extract any complete windows.

        Args:
            chunk: Captured AudioChunk from mic or loopback.

        Returns:
            List of tuples: `(audio_array, start_offset_ms, duration_ms)`.
        """
        if not chunk.data:
            return []

        # Convert chunk to 16kHz mono float32
        audio = normalize_chunk_to_16k_mono(chunk)
        if len(audio) == 0:
            return []

        with self._lock:
            chunk_start_ms = chunk.timestamp_ms
            chunk_end_ms = chunk_start_ms + chunk.duration_ms
            self._max_observed_timestamp_ms = max(self._max_observed_timestamp_ms, chunk_end_ms)

            # Compute sample offset relative to current window start
            offset_ms = chunk_start_ms - self._window_start_ms
            start_sample = round(offset_ms * MS_TO_SAMPLES)

            if start_sample < 0:
                # Chunk starts before current window; slice the leading portion
                drop_samples = -start_sample
                if drop_samples >= len(audio):
                    return []
                audio = audio[drop_samples:]
                start_sample = 0

            end_sample = start_sample + len(audio)

            # Expand internal buffer with silence if chunk extends beyond current length
            if end_sample > len(self._buffer):
                expansion = np.zeros(end_sample - len(self._buffer), dtype=np.float32)
                self._buffer = np.concatenate([self._buffer, expansion])

            # Add audio to timeline (accumulating mic and loopback)
            self._buffer[start_sample:end_sample] += audio

            # Check if any full windows can be extracted
            ready_windows: list[tuple[np.ndarray, int, int]] = []
            while len(self._buffer) >= self._window_samples:
                # Extract full window
                window_data = np.clip(self._buffer[: self._window_samples], -1.0, 1.0)
                window_start = self._window_start_ms

                ready_windows.append((window_data, window_start, self._window_duration_ms))

                # Slide window forward
                self._buffer = self._buffer[self._window_samples :]
                self._window_start_ms += self._window_duration_ms

            return ready_windows

    def flush(self) -> tuple[np.ndarray, int, int] | None:
        """Flush and return any remaining buffered audio upon session completion.

        Returns:
            Tuple `(audio_array, start_offset_ms, duration_ms)` or None if buffer is empty.
        """
        with self._lock:
            if len(self._buffer) == 0:
                return None

            duration_ms = round(len(self._buffer) / MS_TO_SAMPLES)
            window_data = np.clip(self._buffer, -1.0, 1.0)
            window_start = self._window_start_ms

            # Clear buffer
            self._buffer = np.zeros(0, dtype=np.float32)
            self._window_start_ms += duration_ms

            # Only return if window has audible content (non-zero)
            if np.max(np.abs(window_data)) < 1e-4:
                return None

            return (window_data, window_start, duration_ms)

    def reset(self) -> None:
        """Reset the buffer state for a new recording session."""
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)
            self._window_start_ms = 0
            self._max_observed_timestamp_ms = 0
