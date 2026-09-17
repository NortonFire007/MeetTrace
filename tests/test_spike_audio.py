"""Unit tests for the Audio Capture Spike helpers and audio processing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))
from scripts.spike_audio_capture import AudioCaptureSpike, get_default_endpoint_info


def test_endpoint_info_query() -> None:
    """Check that Windows default endpoint queries return valid dictionary structure."""
    render_info = get_default_endpoint_info(0)
    capture_info = get_default_endpoint_info(1)

    assert "id" in render_info
    assert "name" in render_info
    assert "id" in capture_info
    assert "name" in capture_info


def test_resample_same_rate() -> None:
    """Resampling with identical rate should return unchanged array."""
    spike = AudioCaptureSpike()
    data = np.ones((100, 2), dtype=np.int16)
    res = spike._resample(data, 48000, 48000)
    np.testing.assert_array_equal(data, res)


def test_resample_different_rates() -> None:
    """Resampling 44.1kHz to 48kHz should scale the sample count correctly."""
    spike = AudioCaptureSpike(target_rate=48000)
    # 441 samples at 44100Hz = 10ms -> should become 480 samples at 48000Hz
    data = np.zeros((441, 2), dtype=np.int16)
    res = spike._resample(data, 44100, 48000)
    assert res.shape == (480, 2)


def test_signal_rebind() -> None:
    """Signaling rebind should set flag and reason."""
    spike = AudioCaptureSpike()
    assert not spike._rebind_flag
    spike.signal_rebind("Headphones disconnected")
    assert spike._rebind_flag
    assert spike._rebind_reason == "Headphones disconnected"
