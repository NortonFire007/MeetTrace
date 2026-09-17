"""Audio normalization and format conversion utilities for Whisper transcription.

Converts raw PCM audio chunks of arbitrary sample rates and channel counts
into standardized 16kHz mono float32 numpy arrays suitable for faster-whisper.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np

from meettrace.capture.models import AudioChunk

logger = logging.getLogger(__name__)

WHISPER_SAMPLE_RATE: Final[int] = 16000
INT16_SCALE: Final[float] = 32768.0


def pcm16_to_float32(data: bytes, channels: int = 1) -> np.ndarray:
    """Convert raw 16-bit signed PCM byte string to normalized 1D float32 mono array.

    Args:
        data: Raw 16-bit PCM bytes.
        channels: Channel count (1 for mono, 2 for stereo).

    Returns:
        1D float32 numpy array normalized to [-1.0, 1.0].
    """
    if not data:
        return np.empty(0, dtype=np.float32)

    # Convert byte buffer to 16-bit signed integers
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / INT16_SCALE

    if channels == 2:
        # Average stereo channels to mono
        usable_samples = (len(samples) // 2) * 2
        if usable_samples < len(samples):
            samples = samples[:usable_samples]
        stereo = samples.reshape(-1, 2)
        return stereo.mean(axis=1).astype(np.float32)

    return samples


def resample_linear(
    audio: np.ndarray, orig_rate: int, target_rate: int = WHISPER_SAMPLE_RATE
) -> np.ndarray:
    """Resample 1D float32 audio to target sample rate using linear interpolation.

    Args:
        audio: 1D float32 array.
        orig_rate: Original sampling frequency in Hz (e.g., 48000, 44100).
        target_rate: Desired sampling frequency in Hz (default 16000).

    Returns:
        Resampled 1D float32 numpy array.
    """
    if orig_rate == target_rate or len(audio) == 0:
        return audio

    target_length = round(len(audio) * (target_rate / orig_rate))
    if target_length == 0:
        return np.empty(0, dtype=np.float32)

    orig_indices = np.linspace(0, len(audio) - 1, len(audio), dtype=np.float64)
    target_indices = np.linspace(0, len(audio) - 1, target_length, dtype=np.float64)

    resampled = np.interp(target_indices, orig_indices, audio).astype(np.float32)
    return resampled


def normalize_chunk_to_16k_mono(chunk: AudioChunk) -> np.ndarray:
    """Convert an AudioChunk into a 16kHz mono float32 array.

    Args:
        chunk: The captured AudioChunk (mic or loopback).

    Returns:
        1D float32 numpy array at 16000 Hz.
    """
    mono_float = pcm16_to_float32(chunk.data, channels=chunk.channels)
    return resample_linear(mono_float, orig_rate=chunk.sample_rate, target_rate=WHISPER_SAMPLE_RATE)
