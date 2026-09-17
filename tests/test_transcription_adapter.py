"""Unit tests for FasterWhisperTranscriber and multilingual transcription."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from meettrace.transcription.models import (
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionErrorCategory,
    TranscriptSegment,
    TranscriptWord,
)
from meettrace.transcription.whisper_adapter import FasterWhisperTranscriber


class MockWhisperSegment:
    """Mock Segment object emitted by faster-whisper."""

    def __init__(
        self,
        text: str,
        start: float,
        end: float,
        avg_logprob: float = -0.2,
        words: list[Any] | None = None,
    ) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.avg_logprob = avg_logprob
        self.words = words or []


class MockWhisperWord:
    """Mock Word object emitted by faster-whisper."""

    def __init__(self, word: str, start: float, end: float, probability: float = 0.95) -> None:
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class MockTranscriptionInfo:
    """Mock TranscriptionInfo emitted by faster-whisper."""

    def __init__(self, language: str, language_probability: float = 0.98) -> None:
        self.language = language
        self.language_probability = language_probability
        self.duration = 10.0


def test_transcriber_lazy_loading() -> None:
    """Verify WhisperModel is not instantiated upon Transcriber construction."""
    config = TranscriptionConfig(model_size="base", device="cpu", compute_type="int8")
    transcriber = FasterWhisperTranscriber(config)

    assert not transcriber.is_loaded

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_model_cls.return_value = mock_instance

        transcriber.load_model()
        assert transcriber.is_loaded
        mock_model_cls.assert_called_once_with("base", device="cpu", compute_type="int8")


def test_transcriber_cuda_fallback_to_cpu() -> None:
    """Verify CUDA failure automatically falls back to CPU int8."""
    config = TranscriptionConfig(model_size="base", device="cuda", compute_type="float16")
    transcriber = FasterWhisperTranscriber(config)

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        # First call fails (CUDA error), second call succeeds (CPU fallback)
        mock_model_cls.side_effect = [RuntimeError("CUDA out of memory"), MagicMock()]

        transcriber.load_model()
        assert transcriber.is_loaded
        assert mock_model_cls.call_count == 2
        mock_model_cls.assert_called_with("base", device="cpu", compute_type="int8")


def test_transcriber_load_failure_raises_transcription_error() -> None:
    """Verify total model load failure raises structured TranscriptionError."""
    config = TranscriptionConfig(model_size="invalid-model")
    transcriber = FasterWhisperTranscriber(config)

    with patch("faster_whisper.WhisperModel", side_effect=OSError("Model repo not found")):
        with pytest.raises(TranscriptionError) as exc_info:
            transcriber.load_model()

        assert exc_info.value.category == TranscriptionErrorCategory.MODEL_LOAD
        assert exc_info.value.fatal is True


@pytest.mark.parametrize(
    ("lang_code", "sample_text", "expected_words"),
    [
        ("en", "Welcome to the meeting.", ["Welcome", "to", "the", "meeting."]),
        ("ru", "Добро пожаловать на встречу.", ["Добро", "пожаловать", "на", "встречу."]),
        ("uk", "Ласкаво просимо на зустріч.", ["Ласкаво", "просимо", "на", "зустріч."]),
    ],
)
def test_transcription_multilingual_samples(
    lang_code: str,
    sample_text: str,
    expected_words: list[str],
) -> None:
    """Verify English, Russian, and Ukrainian samples return timestamped segments and words."""
    config = TranscriptionConfig(model_size="base", language=None)  # Auto-detection
    transcriber = FasterWhisperTranscriber(config)

    mock_words = [
        MockWhisperWord(word=w, start=i * 0.5, end=(i + 1) * 0.5, probability=0.95)
        for i, w in enumerate(expected_words)
    ]
    mock_segment = MockWhisperSegment(
        text=sample_text,
        start=0.0,
        end=len(expected_words) * 0.5,
        words=mock_words,
    )
    mock_info = MockTranscriptionInfo(language=lang_code, language_probability=0.99)

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([mock_segment], mock_info)
        mock_model_cls.return_value = mock_instance

        # 1-second dummy audio
        audio = np.ones(16000, dtype=np.float32) * 0.1
        segments = transcriber.transcribe(audio, sample_rate=16000, start_offset_ms=5000)

        assert len(segments) == 1
        seg = segments[0]
        assert isinstance(seg, TranscriptSegment)
        assert seg.text == sample_text
        assert seg.language == lang_code
        assert seg.start_ms == 5000  # 5000ms offset + 0s
        assert seg.end_ms == 5000 + int(len(expected_words) * 500)
        assert seg.confidence is not None
        assert len(seg.words) == len(expected_words)
        assert isinstance(seg.words[0], TranscriptWord)
        assert seg.words[0].word == expected_words[0]
        assert seg.words[0].start_ms == 5000


def test_transcription_explicit_language_override() -> None:
    """Verify explicit language configuration overrides auto-detection."""
    config = TranscriptionConfig(model_size="base", language="uk")
    transcriber = FasterWhisperTranscriber(config)

    mock_segment = MockWhisperSegment(text="Тестовий запис", start=0.0, end=1.5)
    mock_info = MockTranscriptionInfo(language="uk")

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([mock_segment], mock_info)
        mock_model_cls.return_value = mock_instance

        audio = np.ones(16000, dtype=np.float32) * 0.1
        segments = transcriber.transcribe(audio)

        assert len(segments) == 1
        assert segments[0].language == "uk"
        mock_instance.transcribe.assert_called_once()
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["language"] == "uk"


def test_transcription_detect_language() -> None:
    """Verify language detection method invokes WhisperModel.detect_language."""
    transcriber = FasterWhisperTranscriber()

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_instance.detect_language.return_value = ("ru", 0.94, [("ru", 0.94), ("uk", 0.05)])
        mock_model_cls.return_value = mock_instance

        audio = np.ones(16000, dtype=np.float32)
        lang, prob = transcriber.detect_language(audio)

        assert lang == "ru"
        assert pytest.approx(prob, 0.01) == 0.94


def test_transcription_empty_audio_returns_empty_list() -> None:
    """Verify empty audio yields empty segment list without calling inference."""
    transcriber = FasterWhisperTranscriber()
    segments = transcriber.transcribe(np.empty(0, dtype=np.float32))
    assert segments == []
