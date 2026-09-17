"""Asynchronous transcription service consuming AudioChunks and emitting TranscriptSegments.

Coordinates timeline buffering, asynchronous background Whisper worker execution,
observer notifications, and lifecycle management without blocking capture or UI threads.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import Counter
from typing import Final

import numpy as np

from meettrace.capture.models import AudioChunk, CaptureState
from meettrace.capture.protocol import BaseAudioCaptureObserver
from meettrace.transcription.buffer import TimelineAudioBuffer
from meettrace.transcription.models import (
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionErrorCategory,
    TranscriptMetadata,
    TranscriptSegment,
)
from meettrace.transcription.protocol import Transcriber, TranscriptionObserver
from meettrace.transcription.whisper_adapter import FasterWhisperTranscriber

logger = logging.getLogger(__name__)

STOP_SENTINEL: Final[object] = object()


class TranscriptionService(BaseAudioCaptureObserver):
    """Coordinates audio chunk consumption, windowing, and async Whisper transcription."""

    def __init__(
        self,
        transcriber: Transcriber | None = None,
        config: TranscriptionConfig | None = None,
    ) -> None:
        self._config = (
            config
            if config is not None
            else (
                transcriber.config
                if isinstance(transcriber, FasterWhisperTranscriber)
                else TranscriptionConfig()
            )
        )
        self._transcriber = (
            transcriber if transcriber is not None else FasterWhisperTranscriber(self._config)
        )
        self._buffer = TimelineAudioBuffer(window_duration_sec=self._config.window_duration_sec)

        self._observers: list[TranscriptionObserver] = []
        self._observers_lock = threading.Lock()

        # Accumulated transcript results
        self._segments: list[TranscriptSegment] = []
        self._segments_lock = threading.Lock()
        self._language_counter: Counter[str] = Counter()

        # Background inference worker and task queue
        self._task_queue: queue.Queue[tuple[np.ndarray, int, int] | object] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_active = False

        self._session_start_time_iso: str = ""
        self._total_audio_duration_ms: int = 0

    @property
    def config(self) -> TranscriptionConfig:
        """Transcription configuration."""
        return self._config

    @property
    def transcriber(self) -> Transcriber:
        """Underlying Transcriber adapter."""
        return self._transcriber

    @property
    def segments(self) -> list[TranscriptSegment]:
        """Chronologically ordered transcript segments accumulated so far."""
        with self._segments_lock:
            return list(self._segments)

    def add_observer(self, observer: TranscriptionObserver) -> None:
        """Register a listener for transcript segments and completion events."""
        with self._observers_lock:
            if observer not in self._observers:
                self._observers.append(observer)

    def remove_observer(self, observer: TranscriptionObserver) -> None:
        """Unregister a listener."""
        with self._observers_lock:
            if observer in self._observers:
                self._observers.remove(observer)

    def start(self) -> None:
        """Start or initialize the background transcription worker."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._is_active = True
        self._session_start_time_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with self._segments_lock:
            self._segments.clear()
            self._language_counter.clear()

        self._buffer.reset()
        self._total_audio_duration_ms = 0

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="TranscriptionWorkerThread",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("TranscriptionService worker thread started.")

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        """Handle incoming timestamped AudioChunk from mic or loopback."""
        if not self._is_active or self._stop_event.is_set():
            return

        # Buffer and mix chunk; extract complete windows
        ready_windows = self._buffer.add_chunk(chunk)
        for window_data, start_offset_ms, duration_ms in ready_windows:
            self._total_audio_duration_ms = max(
                self._total_audio_duration_ms,
                start_offset_ms + duration_ms,
            )
            self._task_queue.put((window_data, start_offset_ms, duration_ms))

    def on_state_changed(self, state: CaptureState) -> None:
        """Synchronize with capture session lifecycle transitions."""
        if state == CaptureState.RECORDING:
            if not self._is_active:
                self.start()
        elif state == CaptureState.STOPPED:
            self.stop()

    def stop(self) -> None:
        """Flush remaining buffered audio and finalize transcription."""
        if not self._is_active:
            return

        self._is_active = False
        logger.info("Finalizing transcription session, flushing remaining buffer...")

        # Flush any trailing audio from the buffer
        trailing = self._buffer.flush()
        if trailing is not None:
            window_data, start_offset_ms, duration_ms = trailing
            self._total_audio_duration_ms = max(
                self._total_audio_duration_ms,
                start_offset_ms + duration_ms,
            )
            self._task_queue.put((window_data, start_offset_ms, duration_ms))

        # Enqueue sentinel to gracefully terminate worker
        self._task_queue.put(STOP_SENTINEL)

        # Wait for pending inference tasks to drain
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10.0)
            self._worker_thread = None

        self._notify_completion()
        logger.info("TranscriptionService session finalized.")

    def cancel(self) -> None:
        """Cancel ongoing transcription immediately without waiting for queued windows."""
        self._stop_event.set()
        self._is_active = False

        # Drain the task queue
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
                self._task_queue.task_done()
            except (queue.Empty, ValueError):
                break

        self._task_queue.put(STOP_SENTINEL)
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        self._buffer.reset()
        logger.info("TranscriptionService canceled.")

    def close(self) -> None:
        """Release all worker threads and model resources."""
        self.cancel()
        self._transcriber.close()

    def _worker_loop(self) -> None:
        """Background thread executing model inference on queued audio windows."""
        logger.debug("Transcription worker loop entered.")
        while not self._stop_event.is_set():
            try:
                item = self._task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is STOP_SENTINEL:
                self._task_queue.task_done()
                break

            window_data, start_offset_ms, _duration_ms = item  # type: ignore[misc]

            try:
                segments = self._transcriber.transcribe(
                    window_data,
                    sample_rate=16000,
                    start_offset_ms=start_offset_ms,
                    language=self._config.language,
                )

                for segment in segments:
                    with self._segments_lock:
                        self._segments.append(segment)
                        self._language_counter[segment.language] += 1
                    self._notify_segment(segment)

            except (RuntimeError, ValueError, OSError) as exc:
                error = (
                    exc
                    if isinstance(exc, TranscriptionError)
                    else TranscriptionError(
                        message=f"Transcription worker failure: {exc}",
                        category=TranscriptionErrorCategory.INFERENCE,
                        fatal=False,
                        underlying_exception=exc,
                        timestamp_ms=start_offset_ms,
                    )
                )
                self._notify_error(error)
            finally:
                self._task_queue.task_done()

        logger.debug("Transcription worker loop exited.")

    def _notify_segment(self, segment: TranscriptSegment) -> None:
        """Deliver segment notification to registered observers."""
        with self._observers_lock:
            observers = list(self._observers)

        for obs in observers:
            try:
                obs.on_segment(segment)
            except Exception:
                logger.exception("Error in TranscriptionObserver.on_segment")

    def _notify_error(self, error: TranscriptionError) -> None:
        """Deliver error notification to registered observers."""
        with self._observers_lock:
            observers = list(self._observers)

        for obs in observers:
            try:
                obs.on_error(error)
            except Exception:
                logger.exception("Error in TranscriptionObserver.on_error")

    def _notify_completion(self) -> None:
        """Compute summary metadata and notify completion to observers."""
        with self._segments_lock:
            total_segments = len(self._segments)
            dominant_lang = (
                self._language_counter.most_common(1)[0][0]
                if self._language_counter
                else (self._config.language or "en")
            )
            detected_langs: dict[str, float] = (
                {lang: count / total_segments for lang, count in self._language_counter.items()}
                if total_segments > 0
                else {}
            )

        metadata = TranscriptMetadata(
            dominant_language=dominant_lang,
            detected_languages=detected_langs,
            model_name=f"faster-whisper:{self._config.model_size}",
            total_duration_ms=self._total_audio_duration_ms,
            segment_count=total_segments,
            created_at=self._session_start_time_iso,
        )

        with self._observers_lock:
            observers = list(self._observers)

        for obs in observers:
            try:
                obs.on_completed(metadata)
            except Exception:
                logger.exception("Error in TranscriptionObserver.on_completed")
