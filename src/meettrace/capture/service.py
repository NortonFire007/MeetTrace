"""Production AudioCaptureService implementation.

Coordinates independent microphone and system loopback workers, handles dynamic
Core Audio endpoint switching, tracks state transitions, and emits timestamped audio chunks.
"""

from __future__ import annotations

import logging
import threading
import time

from meettrace.capture.backend import AudioBackend, WindowsAudioBackend
from meettrace.capture.broadcaster import CaptureObserverBroadcaster
from meettrace.capture.models import (
    AudioSource,
    CaptureError,
    CaptureErrorCategory,
    CaptureState,
    DeviceChangeEvent,
    DeviceFlow,
    validate_transition,
)
from meettrace.capture.protocol import AudioCapture, AudioCaptureObserver
from meettrace.capture.worker import AudioCaptureWorker

logger = logging.getLogger(__name__)


class AudioCaptureService(AudioCapture):
    """Production audio capture service coordinating dual independent capture streams.

    Manages microphone and system render-loopback workers independently, ensuring
    that device switching on one endpoint does not interrupt capture on the other.
    """

    def __init__(
        self,
        backend: AudioBackend | None = None,
        frames_per_buffer: int = 1024,
    ) -> None:
        self._backend = backend if backend is not None else WindowsAudioBackend()
        self._frames_per_buffer = frames_per_buffer

        self._state = CaptureState.IDLE
        self._state_lock = threading.RLock()
        self._broadcaster = CaptureObserverBroadcaster()

        self._session_start_time: float = 0.0
        self._mic_worker: AudioCaptureWorker | None = None
        self._loopback_worker: AudioCaptureWorker | None = None
        self._active_rebinds: set[AudioSource] = set()

    @property
    def state(self) -> CaptureState:
        """Current operational state of the capture service."""
        with self._state_lock:
            return self._state

    def _set_state(self, target_state: CaptureState) -> None:
        """Transition internal state and notify registered observers."""
        with self._state_lock:
            if self._state == target_state:
                return
            validate_transition(self._state, target_state)
            self._state = target_state
            logger.info("AudioCaptureService state -> %s", target_state.value)
        self._broadcaster.notify_state_changed(target_state)

    def add_observer(self, observer: AudioCaptureObserver) -> None:
        """Register an observer for audio chunks, state changes, device events, and errors."""
        self._broadcaster.add_observer(observer)

    def remove_observer(self, observer: AudioCaptureObserver) -> None:
        """Unregister an observer."""
        self._broadcaster.remove_observer(observer)

    def start(self) -> None:
        """Start audio capture for both microphone and system audio.

        Raises:
            InvalidStateTransitionError: If the transition to STARTING is not permitted.
            OSError: If no capture devices could be initialized.
        """
        with self._state_lock:
            self._set_state(CaptureState.STARTING)
            self._session_start_time = time.monotonic()
            self._active_rebinds.clear()

            # 1. Register device change notification listener
            self._backend.start_notifications(self._on_device_changed)

            # 2. Spawn independent workers
            self._mic_worker = AudioCaptureWorker(
                source="mic",
                backend=self._backend,
                broadcaster=self._broadcaster,
                session_start_time=self._session_start_time,
                frames_per_buffer=self._frames_per_buffer,
                on_rebind_started=self._on_worker_rebind_started,
                on_rebind_finished=self._on_worker_rebind_finished,
            )

            self._loopback_worker = AudioCaptureWorker(
                source="loopback",
                backend=self._backend,
                broadcaster=self._broadcaster,
                session_start_time=self._session_start_time,
                frames_per_buffer=self._frames_per_buffer,
                on_rebind_started=self._on_worker_rebind_started,
                on_rebind_finished=self._on_worker_rebind_finished,
            )

            self._mic_worker.start()
            self._loopback_worker.start()

            # Wait for workers to finish their stream initialization attempts
            self._mic_worker.wait_ready(timeout=2.0)
            self._loopback_worker.wait_ready(timeout=2.0)

            # If both workers failed to open any stream, report fatal error
            if not self._mic_worker.is_stream_active and not self._loopback_worker.is_stream_active:
                logger.error("Failed to initialize any audio capture devices.")
                self._broadcaster.notify_error(
                    CaptureError(
                        message="No audio input or output endpoints available for capture.",
                        fatal=True,
                        category=CaptureErrorCategory.DEVICE_UNAVAILABLE,
                    )
                )
                self._stop_workers()
                self._set_state(CaptureState.ERROR)
                raise OSError("No audio capture devices available.")

            self._set_state(CaptureState.RECORDING)

    def stop(self) -> None:
        """Stop audio capture and terminate active worker threads."""
        with self._state_lock:
            if self._state in (CaptureState.STOPPED, CaptureState.IDLE):
                return
            self._set_state(CaptureState.STOPPED)
            self._stop_workers()

    def _stop_workers(self) -> None:
        """Internal helper to stop workers and unregister notifications."""
        self._backend.stop_notifications()

        if self._mic_worker is not None:
            self._mic_worker.stop()
        if self._loopback_worker is not None:
            self._loopback_worker.stop()

        if self._mic_worker is not None:
            self._mic_worker.join(timeout=2.0)
            self._mic_worker = None
        if self._loopback_worker is not None:
            self._loopback_worker.join(timeout=2.0)
            self._loopback_worker = None

        self._active_rebinds.clear()

    def pause(self) -> None:
        """Temporarily pause chunk emission without closing hardware streams."""
        with self._state_lock:
            self._set_state(CaptureState.PAUSED)
            if self._mic_worker is not None:
                self._mic_worker.pause()
            if self._loopback_worker is not None:
                self._loopback_worker.pause()

    def resume(self) -> None:
        """Resume chunk emission after pause."""
        with self._state_lock:
            self._set_state(CaptureState.RECORDING)
            if self._mic_worker is not None:
                self._mic_worker.resume()
            if self._loopback_worker is not None:
                self._loopback_worker.resume()

    def _on_device_changed(self, flow: DeviceFlow, endpoint_id: str, friendly_name: str) -> None:
        """Handle endpoint change notification and route rebind to the appropriate worker."""
        now = time.monotonic()
        timestamp_ms = (
            max(0, int((now - self._session_start_time) * 1000))
            if self._session_start_time > 0
            else 0
        )
        event = DeviceChangeEvent(
            flow=flow,
            endpoint_id=endpoint_id,
            friendly_name=friendly_name,
            timestamp_ms=timestamp_ms,
        )
        logger.info(
            "Device change detected: flow=%s, endpoint=%s, name='%s'",
            flow,
            endpoint_id,
            friendly_name,
        )
        self._broadcaster.notify_device_changed(event)

        # Route rebind signal strictly to the corresponding worker
        if flow == "render" and self._loopback_worker is not None:
            logger.info("Signaling rebind for loopback worker only.")
            self._loopback_worker.signal_rebind()
        elif flow == "capture" and self._mic_worker is not None:
            logger.info("Signaling rebind for microphone worker only.")
            self._mic_worker.signal_rebind()

    def _on_worker_rebind_started(self, source: AudioSource) -> None:
        """Callback invoked when a worker enters rebind."""
        with self._state_lock:
            self._active_rebinds.add(source)
            if self._state == CaptureState.RECORDING:
                self._set_state(CaptureState.REBINDING)

    def _on_worker_rebind_finished(self, source: AudioSource) -> None:
        """Callback invoked when a worker finishes rebind."""
        with self._state_lock:
            self._active_rebinds.discard(source)
            if not self._active_rebinds and self._state == CaptureState.REBINDING:
                self._set_state(CaptureState.RECORDING)
