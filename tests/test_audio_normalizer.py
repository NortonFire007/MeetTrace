"""Unit tests for audio normalization and TimelineAudioBuffer."""

from __future__ import annotations

import numpy as np
import pytest

from meettrace.capture.models import AudioChunk
from meettrace.transcription.buffer import TimelineAudioBuffer
from meettrace.transcription.normalizer import (
    WHISPER_SAMPLE_RATE,
    normalize_chunk_to_16k_mono,
    pcm16_to_float32,
    resample_linear,
)


def test_pcm16_to_float32_mono() -> None:
    """Verify mono 16-bit PCM bytes are properly scaled to float32 in [-1.0, 1.0]."""
    # 0 -> 0.0, 32767 -> ~1.0, -32768 -> -1.0
    pcm_bytes = np.array([0, 16384, 32767, -32768], dtype=np.int16).tobytes()
    float_samples = pcm16_to_float32(pcm_bytes, channels=1)

    assert float_samples.dtype == np.float32
    assert len(float_samples) == 4
    assert pytest.approx(float_samples[0], 0.001) == 0.0
    assert pytest.approx(float_samples[1], 0.001) == 0.5
    assert pytest.approx(float_samples[2], 0.001) == 1.0
    assert pytest.approx(float_samples[3], 0.001) == -1.0


def test_pcm16_to_float32_stereo() -> None:
    """Verify stereo 16-bit PCM bytes are averaged into mono float32."""
    # Pair 1: (16384, 16384) -> 0.5
    # Pair 2: (32767, 0) -> ~0.5
    pcm_bytes = np.array([16384, 16384, 32767, 0], dtype=np.int16).tobytes()
    float_samples = pcm16_to_float32(pcm_bytes, channels=2)

    assert len(float_samples) == 2
    assert pytest.approx(float_samples[0], 0.001) == 0.5
    assert pytest.approx(float_samples[1], 0.001) == 0.5


def test_pcm16_to_float32_empty() -> None:
    """Verify empty byte input returns empty float32 array."""
    res = pcm16_to_float32(b"", channels=1)
    assert len(res) == 0
    assert res.dtype == np.float32


def test_resample_linear() -> None:
    """Verify linear interpolation downsamples 48kHz to 16kHz correctly."""
    # 48000 samples at 48kHz = 1.0 second of audio
    # Resampled at 16kHz must equal 16000 samples
    orig_samples = np.sin(np.linspace(0, 2 * np.pi * 440, 48000), dtype=np.float32)
    resampled = resample_linear(orig_samples, orig_rate=48000, target_rate=16000)

    assert len(resampled) == 16000
    assert resampled.dtype == np.float32


def test_normalize_chunk_to_16k_mono() -> None:
    """Verify AudioChunk conversion helper converts multi-rate stereo chunk to 16kHz mono."""
    # 960 frames of 48kHz stereo = 20ms
    frames = 960
    pcm_bytes = (b"\x00\x10\x00\x10") * frames  # 4 bytes per frame
    chunk = AudioChunk(
        source="loopback",
        data=pcm_bytes,
        timestamp_ms=1000,
        duration_ms=20,
        sample_rate=48000,
        channels=2,
    )

    mono_16k = normalize_chunk_to_16k_mono(chunk)
    # 20ms at 16kHz = 320 samples
    assert len(mono_16k) == 320
    assert mono_16k.dtype == np.float32


def test_timeline_buffer_window_accumulation() -> None:
    """Verify TimelineAudioBuffer accumulates chunks and emits windows at duration threshold."""
    # Use small window of 1.0 second for fast deterministic test
    buffer = TimelineAudioBuffer(window_duration_sec=1.0)
    window_samples = 1.0 * WHISPER_SAMPLE_RATE  # 16000 samples

    # Add two 600ms chunks (total 1200ms)
    pcm_600ms = (b"\x00\x08") * int(16000 * 0.6)
    chunk1 = AudioChunk(
        source="mic",
        data=pcm_600ms,
        timestamp_ms=0,
        duration_ms=600,
        sample_rate=16000,
        channels=1,
    )
    chunk2 = AudioChunk(
        source="mic",
        data=pcm_600ms,
        timestamp_ms=600,
        duration_ms=600,
        sample_rate=16000,
        channels=1,
    )

    windows1 = buffer.add_chunk(chunk1)
    assert len(windows1) == 0  # Only 600ms accumulated, threshold is 1000ms

    windows2 = buffer.add_chunk(chunk2)
    assert len(windows2) == 1  # Reached 1200ms >= 1000ms window

    window_data, start_ms, duration_ms = windows2[0]
    assert len(window_data) == window_samples
    assert start_ms == 0
    assert duration_ms == 1000


def test_timeline_buffer_mic_and_loopback_mixing() -> None:
    """Verify concurrent mic and loopback chunks are mixed into the same timeline position."""
    buffer = TimelineAudioBuffer(window_duration_sec=1.0)

    # Mic chunk with amplitude 0.2
    mic_arr = np.ones(8000, dtype=np.int16) * 6553  # ~0.2
    # Loopback chunk with amplitude 0.3 at the exact same timestamp (0ms)
    loop_arr = np.ones(8000, dtype=np.int16) * 9830  # ~0.3

    chunk_mic = AudioChunk(
        source="mic",
        data=mic_arr.tobytes(),
        timestamp_ms=0,
        duration_ms=500,
        sample_rate=16000,
        channels=1,
    )
    chunk_loop = AudioChunk(
        source="loopback",
        data=loop_arr.tobytes(),
        timestamp_ms=0,
        duration_ms=500,
        sample_rate=16000,
        channels=1,
    )

    buffer.add_chunk(chunk_mic)
    buffer.add_chunk(chunk_loop)

    # Flush buffer and verify combined audio has amplitude ~0.5
    flushed = buffer.flush()
    assert flushed is not None
    window_data, start_ms, duration_ms = flushed

    assert start_ms == 0
    assert duration_ms == 500
    # Average amplitude should be ~0.5 (0.2 + 0.3)
    assert pytest.approx(float(np.mean(window_data)), 0.05) == 0.5


def test_timeline_buffer_rebind_gap_tolerance() -> None:
    """Verify device rebind gap creates silence rather than resetting the timeline."""
    buffer = TimelineAudioBuffer(window_duration_sec=2.0)

    # Chunk 1: 0ms -> 500ms
    arr1 = np.ones(8000, dtype=np.int16) * 10000
    chunk1 = AudioChunk(
        source="mic",
        data=arr1.tobytes(),
        timestamp_ms=0,
        duration_ms=500,
        sample_rate=16000,
        channels=1,
    )

    # Gap of 1000ms (500ms -> 1500ms is missing)
    # Chunk 2: 1500ms -> 2000ms
    chunk2 = AudioChunk(
        source="mic",
        data=arr1.tobytes(),
        timestamp_ms=1500,
        duration_ms=500,
        sample_rate=16000,
        channels=1,
    )

    buffer.add_chunk(chunk1)
    windows = buffer.add_chunk(chunk2)

    assert len(windows) == 1
    window_data, start_ms, duration_ms = windows[0]

    assert start_ms == 0
    assert duration_ms == 2000
    assert len(window_data) == 32000  # 2.0s at 16kHz

    # The middle interval (samples 8000 to 24000) corresponds to the 1-second gap
    gap_samples = window_data[8000:24000]
    assert np.all(gap_samples == 0.0)


def test_timeline_buffer_flush_and_reset() -> None:
    """Verify flush returns remaining audio and reset clears internal state."""
    buffer = TimelineAudioBuffer(window_duration_sec=10.0)

    # Add 200ms of audio (< 10s window)
    arr = np.ones(3200, dtype=np.int16) * 5000
    chunk = AudioChunk(
        source="mic",
        data=arr.tobytes(),
        timestamp_ms=0,
        duration_ms=200,
        sample_rate=16000,
        channels=1,
    )
    buffer.add_chunk(chunk)

    flushed = buffer.flush()
    assert flushed is not None
    assert flushed[1] == 0
    assert flushed[2] == 200

    # Second flush should be None
    assert buffer.flush() is None

    buffer.reset()
    assert buffer.window_start_ms == 0
