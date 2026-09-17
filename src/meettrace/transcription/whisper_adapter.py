"""faster-whisper adapter implementing local speech-to-text inference.

Wraps faster_whisper.WhisperModel with lazy model loading, automatic language detection
(including English, Russian, Ukrainian), hardware fallback, and domain segment mapping.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from meettrace.transcription.models import (
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionErrorCategory,
    TranscriptSegment,
    TranscriptWord,
)
from meettrace.transcription.protocol import Transcriber

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


class FasterWhisperTranscriber(Transcriber):
    """Local multilingual speech transcriber powered by faster-whisper."""

    def __init__(self, config: TranscriptionConfig | None = None) -> None:
        self.config = config if config is not None else TranscriptionConfig()
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        """True if the underlying model weights have been initialized."""
        with self._lock:
            return self._model is not None

    def load_model(self) -> None:
        """Lazily initialize and load the faster-whisper model weights."""
        with self._lock:
            if self._model is not None:
                return

            import faster_whisper

            device = self.config.device
            compute_type = self.config.compute_type

            logger.info(
                "Loading faster-whisper model '%s' on %s (%s)...",
                self.config.model_size,
                device,
                compute_type,
            )

            try:
                self._model = faster_whisper.WhisperModel(
                    self.config.model_size,
                    device=device,
                    compute_type=compute_type,
                )
                logger.info("faster-whisper model loaded successfully.")
            except Exception as exc:
                if device != "cpu":
                    logger.warning(
                        "Failed to load model on %s (%s). Falling back to CPU/int8: %s",
                        device,
                        compute_type,
                        exc,
                    )
                    try:
                        self._model = faster_whisper.WhisperModel(
                            self.config.model_size,
                            device="cpu",
                            compute_type="int8",
                        )
                        logger.info("faster-whisper model loaded on CPU fallback.")
                        return
                    except (RuntimeError, ValueError, OSError) as fallback_exc:
                        exc = fallback_exc

                error = TranscriptionError(
                    message=f"Failed to load faster-whisper model '{self.config.model_size}': {exc}",
                    category=TranscriptionErrorCategory.MODEL_LOAD,
                    fatal=True,
                    underlying_exception=exc,
                )
                logger.error("%s", error)
                raise error from exc

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        start_offset_ms: int = 0,
        language: str | None = None,
    ) -> list[TranscriptSegment]:
        """Transcribe a 16kHz float32 mono audio array into timestamped segments.

        Args:
            audio: 1D float32 numpy array normalized to [-1.0, 1.0].
            sample_rate: Must be 16000 Hz.
            start_offset_ms: Meeting session offset in milliseconds for audio[0].
            language: Explicit language code or None for auto-detection.

        Returns:
            List of TranscriptSegment instances with session-relative millisecond timestamps.
        """
        if len(audio) == 0:
            return []

        # Ensure model is ready
        self.load_model()
        assert self._model is not None

        target_language = language if language is not None else self.config.language

        try:
            segments_gen, info = self._model.transcribe(
                audio,
                language=target_language,
                beam_size=self.config.beam_size,
                vad_filter=self.config.vad_filter,
                word_timestamps=True,
            )

            detected_lang = info.language or (target_language or "en")
            results: list[TranscriptSegment] = []

            for seg in segments_gen:
                text = seg.text.strip()
                if not text:
                    continue

                seg_start_ms = start_offset_ms + round(seg.start * 1000)
                seg_end_ms = start_offset_ms + round(seg.end * 1000)

                # Safeguard timestamp ordering
                seg_end_ms = max(seg_end_ms, seg_start_ms)

                # Compute approximate confidence from avg_logprob if available
                confidence: float | None = None
                if getattr(seg, "avg_logprob", None) is not None:
                    confidence = float(np.clip(np.exp(seg.avg_logprob), 0.0, 1.0))
                elif getattr(info, "language_probability", None) is not None:
                    confidence = float(info.language_probability)

                # Parse word-level timing details
                words: list[TranscriptWord] = []
                for w in getattr(seg, "words", None) or []:
                    w_start_ms = start_offset_ms + round(w.start * 1000)
                    w_end_ms = start_offset_ms + round(w.end * 1000)
                    w_end_ms = max(w_end_ms, w_start_ms)
                    words.append(
                        TranscriptWord(
                            word=w.word,
                            start_ms=w_start_ms,
                            end_ms=w_end_ms,
                            probability=getattr(w, "probability", 1.0),
                        )
                    )

                results.append(
                    TranscriptSegment(
                        text=text,
                        start_ms=seg_start_ms,
                        end_ms=seg_end_ms,
                        language=detected_lang,
                        confidence=confidence,
                        words=tuple(words),
                    )
                )

            return results

        except Exception as exc:
            error = TranscriptionError(
                message=f"Inference error during transcription: {exc}",
                category=TranscriptionErrorCategory.INFERENCE,
                fatal=False,
                underlying_exception=exc,
                timestamp_ms=start_offset_ms,
            )
            logger.error("%s", error)
            raise error from exc

    def detect_language(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        """Detect dominant spoken language on the provided audio signal."""
        if len(audio) == 0:
            return (self.config.language or "en", 0.0)

        self.load_model()
        assert self._model is not None

        try:
            lang, prob, _ = self._model.detect_language(audio=audio)
            return (lang, float(prob))
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("Language detection failed: %s. Falling back to default.", exc)
            return (self.config.language or "en", 0.0)

    def close(self) -> None:
        """Release faster-whisper model handles and memory."""
        with self._lock:
            self._model = None
            logger.info("FasterWhisperTranscriber closed and model unloaded.")
