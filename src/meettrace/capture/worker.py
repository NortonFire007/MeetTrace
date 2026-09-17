"""Independent audio capture worker for MeetTrace.

Each AudioCaptureWorker instance runs in its own thread, capturing audio from a
single source ('mic' or 'loopback') and handling its own lifecycle, rebinds,
and stream errors independently.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from meettrace.capture.models import (
    AudioChunk,
    AudioSource,
    CaptureError,
    CaptureErrorCategory,
)

if TYPE_CHECKING:
    from meettrace.capture.backend import AudioBackend, AudioStream
    from meettrace.capture.broadcaster import CaptureObserverBroadcaster

logger = logging.getLogger(__name__)


class AudioCaptureWorker(threading.Thread):
    """Independent worker capturing audio from a single source ('mic' or 'loopback').

    Runs an independent loop reading discrete audio buffers and emitting timestamped
    AudioChunk events. Can rebind its stream independently without stopping or affecting
    other active capture workers.
    """

    def __init__(
        self,
        source: AudioSource,
        backend: AudioBackend,
        broadcaster: CaptureObserverBroadcaster,
        session_start_time: float,
        frames_per_buffer: int = 1024,
        on_rebind_started: Callable[[AudioSource], None] | None = None,
        on_rebind_finished: Callable[[AudioSource], None] | None = None,
    ) -> None:
        super().__init__(name=f"CaptureWorker-{source.capitalize()}", daemon=True)
        self.source = source
        self.backend = backend
        self.broadcaster = broadcaster
        self.session_start_time = session_start_time
        self.frames_per_buffer = frames_per_buffer
        self.on_rebind_started = on_rebind_started
        self.on_rebind_finished = on_rebind_finished

        self._stream: AudioStream | None = None
        self._stop_event = threading.Event()
        self._rebind_event = threading.Event()
        self._pause_event = threading.Event()
        self._initial_open_failed = False

    @property
    def is_stream_active(self) -> bool:
        """True if the worker currently holds an open audio stream."""
        return self._stream is not None

    def signal_rebind(self) -> None:
        """Flag this worker to close its current stream and rebind to the new default endpoint."""
        self._rebind_event.set()

    def pause(self) -> None:
        """Pause emitting audio chunks without closing the stream."""
        self._pause_event.set()

    def resume(self) -> None:
        """Resume emitting audio chunks."""
        self._pause_event.clear()

    def stop(self) -> None:
        """Signal the worker to terminate and unblock any waiting events."""
        self._stop_event.set()

    def _open_stream(self) -> bool:
        """Attempt to open the audio stream from the backend."""
        try:
            self._stream = self.backend.open_stream(self.source, self.frames_per_buffer)
            logger.info("Worker [%s] successfully opened audio stream.", self.source)
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("Worker [%s] failed to open stream: %s", self.source, exc)
            self._stream = None
            self.broadcaster.notify_error(
                CaptureError(
                    message=f"Failed to open {self.source} audio stream: {exc}",
                    fatal=False,
                    category=CaptureErrorCategory.DEVICE_UNAVAILABLE,
                    underlying_exception=exc,
                )
            )
            return False

    def _perform_rebind(self) -> None:
        """Safely close the current stream and reopen from the updated default device."""
        if self._stop_event.is_set():
            return

        logger.info("Worker [%s] performing stream rebind...", self.source)
        if self.on_rebind_started is not None:
            with contextlib.suppress(Exception):
                self.on_rebind_started(self.source)

        if self._stream is not None:
            with contextlib.suppress(OSError, RuntimeError):
                self._stream.close()
            self._stream = None

        # Short grace period for OS audio graph to settle
        if self._stop_event.wait(timeout=0.1):
            return

        try:
            self._stream = self.backend.open_stream(self.source, self.frames_per_buffer)
            logger.info("Worker [%s] stream rebind succeeded.", self.source)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("Worker [%s] stream rebind failed: %s", self.source, exc)
            self.broadcaster.notify_error(
                CaptureError(
                    message=f"Failed to rebind {self.source} audio stream: {exc}",
                    fatal=False,
                    category=CaptureErrorCategory.REBIND_FAILURE,
                    underlying_exception=exc,
                )
            )
        finally:
            if self.on_rebind_finished is not None:
                with contextlib.suppress(Exception):
                    self.on_rebind_finished(self.source)

    def run(self) -> None:
        """Main worker capture loop."""
        if not self._open_stream():
            self._initial_open_failed = True

        while not self._stop_event.is_set():
            # 1. Handle device rebind request
            if self._rebind_event.is_set():
                self._rebind_event.clear()
                self._perform_rebind()
                continue

            # 2. Handle paused state
            if self._pause_event.is_set():
                self._stop_event.wait(timeout=0.05)
                continue

            # 3. Handle stream absent (e.g. initial failure or failed rebind)
            if self._stream is None:
                # Wait for rebind signal or stop signal
                self._stop_event.wait(timeout=0.5)
                continue

            # 4. Read audio data from stream
            try:
                data = self._stream.read(self.frames_per_buffer)
            except (OSError, RuntimeError) as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("Worker [%s] stream read error: %s", self.source, exc)
                self.broadcaster.notify_error(
                    CaptureError(
                        message=f"Read error on {self.source} audio stream: {exc}",
                        fatal=False,
                        category=CaptureErrorCategory.STREAM_ERROR,
                        underlying_exception=exc,
                    )
                )
                self.signal_rebind()
                continue

            # Discard read data if worker was paused or stopped while read was executing
            if self._pause_event.is_set() or self._stop_event.is_set():
                continue

            if not data:
                time.sleep(0.01)
                continue

            # 5. Build and emit timestamped AudioChunk
            now = time.monotonic()
            timestamp_ms = max(0, int((now - self.session_start_time) * 1000))
            channels = self._stream.channels
            sample_rate = self._stream.sample_rate
            bytes_per_sample = 2  # 16-bit PCM
            bytes_per_frame = channels * bytes_per_sample
            frame_count = len(data) // bytes_per_frame if bytes_per_frame > 0 else 0
            duration_ms = int(frame_count * 1000 / sample_rate) if sample_rate > 0 else 0

            try:
                chunk = AudioChunk(
                    source=self.source,
                    data=data,
                    timestamp_ms=timestamp_ms,
                    duration_ms=duration_ms,
                    sample_rate=sample_rate,
                    channels=channels,
                )
                self.broadcaster.notify_audio_chunk(chunk)
            except (ValueError, TypeError) as exc:
                logger.debug("Failed to construct or emit AudioChunk: %s", exc)

        # Cleanup on exit
        if self._stream is not None:
            with contextlib.suppress(OSError, RuntimeError):
                self._stream.close()
            self._stream = None
        logger.info("Worker [%s] stopped cleanly.", self.source)
