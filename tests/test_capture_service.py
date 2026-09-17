import threading
import time
from collections.abc import Callable

import pytest

from meettrace.capture import (
    AudioCapture,
    AudioCaptureService,
    AudioChunk,
    AudioSource,
    AudioStream,
    BaseAudioCaptureObserver,
    CaptureError,
    CaptureErrorCategory,
    CaptureState,
    DeviceChangeEvent,
    DeviceEndpointInfo,
    DeviceFlow,
)


class MockAudioStream(AudioStream):
    """Mock audio stream producing deterministic PCM chunks for testing."""

    def __init__(
        self,
        source: AudioSource,
        sample_rate: int = 16000,
        channels: int = 1,
        read_delay: float = 0.01,
        fail_on_read: bool = False,
    ) -> None:
        self.source = source
        self._sample_rate = sample_rate
        self._channels = channels
        self.read_delay = read_delay
        self.fail_on_read = fail_on_read
        self.read_calls = 0
        self.close_calls = 0
        self.is_closed = False

    def read(self, num_frames: int) -> bytes:
        if self.is_closed:
            raise OSError("Stream is closed.")
        if self.fail_on_read:
            raise OSError(f"Mock read failure on {self.source}")
        if self.read_delay > 0:
            time.sleep(self.read_delay)
        self.read_calls += 1
        # 16-bit PCM = 2 bytes per sample per channel
        return b"\x01\x00" * (num_frames * self._channels)

    def close(self) -> None:
        self.close_calls += 1
        self.is_closed = True

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels


class MockAudioBackend:
    """Mock audio backend simulating devices, streams, and dynamic notifications."""

    def __init__(self) -> None:
        self.fail_open_mic = False
        self.fail_open_loopback = False
        self.fail_rebind_mic = False
        self.fail_rebind_loopback = False

        self.mic_streams: list[MockAudioStream] = []
        self.loopback_streams: list[MockAudioStream] = []

        self.notification_callback: Callable[[DeviceFlow, str, str], None] | None = None
        self.notifications_started = False
        self.notifications_stopped = False

    def open_stream(self, source: AudioSource, frames_per_buffer: int = 1024) -> AudioStream:
        if source == "mic":
            if self.fail_open_mic and len(self.mic_streams) == 0:
                raise OSError("Mock mic open error")
            if self.fail_rebind_mic and len(self.mic_streams) > 0:
                raise OSError("Mock mic rebind error")
            stream = MockAudioStream(source="mic", sample_rate=16000, channels=1)
            self.mic_streams.append(stream)
            return stream

        if source == "loopback":
            if self.fail_open_loopback and len(self.loopback_streams) == 0:
                raise OSError("Mock loopback open error")
            if self.fail_rebind_loopback and len(self.loopback_streams) > 0:
                raise OSError("Mock loopback rebind error")
            stream = MockAudioStream(source="loopback", sample_rate=48000, channels=2)
            self.loopback_streams.append(stream)
            return stream

        raise ValueError(f"Unknown source: {source}")

    def get_default_endpoint(self, flow: DeviceFlow) -> DeviceEndpointInfo:
        if flow == "render":
            return DeviceEndpointInfo("mock-render-id", "Mock Speakers")
        return DeviceEndpointInfo("mock-capture-id", "Mock Microphone")

    def start_notifications(
        self, callback: Callable[[DeviceFlow, str, str], None]
    ) -> None:
        self.notification_callback = callback
        self.notifications_started = True
        self.notifications_stopped = False

    def stop_notifications(self) -> None:
        self.notification_callback = None
        self.notifications_stopped = True

    def simulate_device_change(self, flow: DeviceFlow, endpoint_id: str, friendly_name: str) -> None:
        if self.notification_callback is not None:
            self.notification_callback(flow, endpoint_id, friendly_name)

    def close(self) -> None:
        self.stop_notifications()


class EventCollectingObserver(BaseAudioCaptureObserver):
    """Observer capturing emitted events for test assertions."""

    def __init__(self) -> None:
        self.chunks: list[AudioChunk] = []
        self.states: list[CaptureState] = []
        self.device_events: list[DeviceChangeEvent] = []
        self.errors: list[CaptureError] = []
        self._lock = threading.Lock()

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        with self._lock:
            self.chunks.append(chunk)

    def on_state_changed(self, state: CaptureState) -> None:
        with self._lock:
            self.states.append(state)

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        with self._lock:
            self.device_events.append(event)

    def on_error(self, error: CaptureError) -> None:
        with self._lock:
            self.errors.append(error)


class FaultyObserver(BaseAudioCaptureObserver):
    """Observer that raises exceptions in all callbacks to test isolation."""

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        raise RuntimeError("Observer chunk crash")

    def on_state_changed(self, state: CaptureState) -> None:
        raise RuntimeError("Observer state crash")

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        raise RuntimeError("Observer device crash")

    def on_error(self, error: CaptureError) -> None:
        raise RuntimeError("Observer error crash")


def test_service_implements_protocol() -> None:
    """AudioCaptureService conforms to AudioCapture protocol."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    assert isinstance(service, AudioCapture)
    assert service.state == CaptureState.IDLE


def test_start_stop_lifecycle() -> None:
    """Service correctly progresses IDLE -> STARTING -> RECORDING -> STOPPED."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    assert service.state == CaptureState.IDLE

    service.start()
    assert service.state == CaptureState.RECORDING
    assert CaptureState.STARTING in observer.states
    assert CaptureState.RECORDING in observer.states

    service.stop()
    assert service.state == CaptureState.STOPPED
    assert CaptureState.STOPPED in observer.states

    # Repeated stop calls should be idempotent
    service.stop()
    assert service.state == CaptureState.STOPPED


def test_repeated_start_stop_cycles() -> None:
    """Service can be safely restarted for subsequent sessions."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)

    # First session
    service.start()
    assert service.state == CaptureState.RECORDING
    service.stop()
    assert service.state == CaptureState.STOPPED

    # Second session
    service.start()
    assert service.state == CaptureState.RECORDING
    service.stop()
    assert service.state == CaptureState.STOPPED


def test_microphone_and_loopback_emit_timestamped_chunks() -> None:
    """Microphone and loopback workers concurrently emit timestamped chunks."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.1)
    service.stop()

    mic_chunks = [c for c in observer.chunks if c.source == "mic"]
    loop_chunks = [c for c in observer.chunks if c.source == "loopback"]

    assert len(mic_chunks) > 0
    assert len(loop_chunks) > 0

    first_mic = mic_chunks[0]
    assert first_mic.sample_rate == 16000
    assert first_mic.channels == 1
    assert first_mic.timestamp_ms >= 0
    assert first_mic.duration_ms > 0
    assert len(first_mic.data) > 0

    first_loop = loop_chunks[0]
    assert first_loop.sample_rate == 48000
    assert first_loop.channels == 2
    assert first_loop.timestamp_ms >= 0
    assert first_loop.duration_ms > 0
    assert len(first_loop.data) > 0


def test_independent_worker_startup_failure() -> None:
    """If one source fails to open, non-fatal error is emitted and other source continues."""
    backend = MockAudioBackend()
    backend.fail_open_mic = True  # Mic fails, loopback succeeds

    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.1)
    service.stop()

    # Service remains functional with loopback
    assert any(
        err.category == CaptureErrorCategory.DEVICE_UNAVAILABLE and not err.fatal
        for err in observer.errors
    )
    loop_chunks = [c for c in observer.chunks if c.source == "loopback"]
    mic_chunks = [c for c in observer.chunks if c.source == "mic"]

    assert len(loop_chunks) > 0
    assert len(mic_chunks) == 0


def test_all_workers_startup_failure_raises_oserror() -> None:
    """If both sources fail to open, a fatal error is emitted and start() raises OSError."""
    backend = MockAudioBackend()
    backend.fail_open_mic = True
    backend.fail_open_loopback = True

    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    with pytest.raises(OSError, match="No audio capture devices available"):
        service.start()

    assert service.state == CaptureState.ERROR
    assert any(err.fatal for err in observer.errors)


def test_render_rebind_does_not_restart_microphone_worker() -> None:
    """Switching render endpoint rebinds loopback only; microphone worker is uninterrupted."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    assert len(backend.mic_streams) == 1
    assert len(backend.loopback_streams) == 1
    initial_mic_stream = backend.mic_streams[0]
    initial_loop_stream = backend.loopback_streams[0]

    # Trigger default render device change
    backend.simulate_device_change("render", "endpoint-speakers-2", "External Speakers")
    time.sleep(0.2)  # Wait for worker rebind

    service.stop()

    # Loopback stream was closed and reopened
    assert initial_loop_stream.close_calls >= 1
    assert len(backend.loopback_streams) == 2

    # Microphone stream was NOT closed or interrupted
    assert initial_mic_stream.close_calls == 1  # only closed once at final service.stop()
    assert len(backend.mic_streams) == 1

    # Device change event was emitted
    dev_events = [e for e in observer.device_events if e.flow == "render"]
    assert len(dev_events) == 1
    assert dev_events[0].endpoint_id == "endpoint-speakers-2"
    assert dev_events[0].friendly_name == "External Speakers"


def test_capture_rebind_does_not_restart_loopback_worker() -> None:
    """Switching capture endpoint rebinds mic only; loopback worker is uninterrupted."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    assert len(backend.mic_streams) == 1
    assert len(backend.loopback_streams) == 1
    initial_mic_stream = backend.mic_streams[0]
    initial_loop_stream = backend.loopback_streams[0]

    # Trigger default capture device change
    backend.simulate_device_change("capture", "endpoint-mic-2", "USB Conference Mic")
    time.sleep(0.2)  # Wait for worker rebind

    service.stop()

    # Mic stream was closed and reopened
    assert initial_mic_stream.close_calls >= 1
    assert len(backend.mic_streams) == 2

    # Loopback stream was NOT closed during mic rebind
    assert initial_loop_stream.close_calls == 1  # only closed once at final service.stop()
    assert len(backend.loopback_streams) == 1

    # Device change event was emitted
    dev_events = [e for e in observer.device_events if e.flow == "capture"]
    assert len(dev_events) == 1
    assert dev_events[0].endpoint_id == "endpoint-mic-2"
    assert dev_events[0].friendly_name == "USB Conference Mic"


def test_failed_rebind_produces_capture_error_and_allows_other_source_to_continue() -> None:
    """Failed rebind emits non-fatal CaptureError while keeping the other worker running."""
    backend = MockAudioBackend()
    backend.fail_rebind_loopback = True

    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Trigger render device change that will fail on rebind
    backend.simulate_device_change("render", "bad-render-id", "Faulty Output")
    time.sleep(0.2)

    service.stop()

    # Verify CaptureErrorCategory.REBIND_FAILURE was emitted
    rebind_errors = [
        err for err in observer.errors if err.category == CaptureErrorCategory.REBIND_FAILURE
    ]
    assert len(rebind_errors) > 0
    assert rebind_errors[0].fatal is False

    # Microphone continued to emit chunks
    mic_chunks = [c for c in observer.chunks if c.source == "mic"]
    assert len(mic_chunks) > 0


def test_stream_read_error_emits_stream_error_and_triggers_rebind() -> None:
    """Stream read error emits STREAM_ERROR and attempts dynamic rebind."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Inject read failure on active microphone stream
    assert len(backend.mic_streams) == 1
    backend.mic_streams[0].fail_on_read = True

    time.sleep(0.2)
    service.stop()

    stream_errors = [
        err for err in observer.errors if err.category == CaptureErrorCategory.STREAM_ERROR
    ]
    assert len(stream_errors) > 0
    assert stream_errors[0].fatal is False

    # The mic worker should have rebound and opened a second stream
    assert len(backend.mic_streams) >= 2


def test_pause_and_resume() -> None:
    """Pausing stops chunk emission; resuming restarts emission under the same session."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = EventCollectingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)
    assert service.state == CaptureState.RECORDING

    # Pause capture
    service.pause()
    assert service.state == CaptureState.PAUSED
    count_at_pause = len(observer.chunks)

    # In paused state, chunks should not be emitted
    time.sleep(0.1)
    assert len(observer.chunks) == count_at_pause

    # Resume capture
    service.resume()
    assert service.state == CaptureState.RECORDING
    time.sleep(0.05)
    assert len(observer.chunks) > count_at_pause

    service.stop()
    assert service.state == CaptureState.STOPPED


def test_clean_shutdown_leaves_no_lingering_threads() -> None:
    """stop() cleanly joins capture worker threads."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)

    service.start()
    active_worker_threads = [
        t for t in threading.enumerate() if t.name.startswith("CaptureWorker-")
    ]
    assert len(active_worker_threads) == 2

    service.stop()

    remaining_worker_threads = [
        t for t in threading.enumerate() if t.name.startswith("CaptureWorker-")
    ]
    assert len(remaining_worker_threads) == 0
    assert backend.notifications_stopped is True


def test_observer_isolation() -> None:
    """Exceptions in faulty observers do not disrupt other observers or the capture service."""
    backend = MockAudioBackend()
    service = AudioCaptureService(backend=backend)

    faulty = FaultyObserver()
    healthy = EventCollectingObserver()

    service.add_observer(faulty)
    service.add_observer(healthy)

    service.start()
    time.sleep(0.05)
    backend.simulate_device_change("render", "new-id", "Speakers")
    time.sleep(0.15)
    service.pause()
    service.resume()
    service.stop()

    assert len(healthy.chunks) > 0
    assert len(healthy.states) > 0
    assert len(healthy.device_events) > 0
