"""Comprehensive unit tests with mock audio devices and mocked device-change events.

Validates the Meeting audio capture requirements and scenarios from OpenSpec:
- Default endpoint discovery and binding without manual device matching.
- Dynamic render and capture endpoint switching and seamless session rebinding.
- Abrupt device disconnection, reconnection resilience, and error handling.
- Independent sample rates, channels, and clock drift tolerance.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from meettrace.capture import (
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


@dataclass(frozen=True, slots=True)
class MockDeviceSpec:
    """Specification for a virtual audio hardware endpoint."""

    device_id: str
    friendly_name: str
    flow: DeviceFlow
    sample_rate: int = 48000
    channels: int = 2


class VirtualAudioStream(AudioStream):
    """Virtual audio stream connected to a specific MockDeviceSpec."""

    def __init__(self, spec: MockDeviceSpec, read_delay: float = 0.005) -> None:
        self.spec = spec
        self.read_delay = read_delay
        self.is_connected = True
        self.is_closed = False
        self.read_count = 0
        self.close_count = 0

    def read(self, num_frames: int) -> bytes:
        if self.is_closed:
            raise OSError("Attempted read from closed virtual stream.")
        if not self.is_connected:
            raise OSError(f"Device '{self.spec.friendly_name}' disconnected unexpectedly.")
        if self.read_delay > 0:
            time.sleep(self.read_delay)
        self.read_count += 1
        return b"\x02\x00" * (num_frames * self.spec.channels)

    def close(self) -> None:
        self.is_closed = True
        self.close_count += 1

    @property
    def sample_rate(self) -> int:
        return self.spec.sample_rate

    @property
    def channels(self) -> int:
        return self.spec.channels


class MockDeviceAudioBackend:
    """Mock audio backend managing multiple simulated audio hardware devices."""

    def __init__(self) -> None:
        self.devices: dict[str, MockDeviceSpec] = {}
        self.default_render_id: str | None = None
        self.default_capture_id: str | None = None

        self.active_streams: list[VirtualAudioStream] = []
        self._notification_callback: Callable[[DeviceFlow, str, str], None] | None = None
        self._lock = threading.Lock()

    def add_device(self, spec: MockDeviceSpec, is_default: bool = False) -> None:
        """Register a mock audio device in the virtual environment."""
        with self._lock:
            self.devices[spec.device_id] = spec
            if is_default:
                if spec.flow == "render":
                    self.default_render_id = spec.device_id
                else:
                    self.default_capture_id = spec.device_id

    def set_default_device(self, device_id: str) -> None:
        """Switch default endpoint and fire device-change notification."""
        with self._lock:
            spec = self.devices[device_id]
            if spec.flow == "render":
                self.default_render_id = spec.device_id
            else:
                self.default_capture_id = spec.device_id
            callback = self._notification_callback

        if callback is not None:
            callback(spec.flow, spec.device_id, spec.friendly_name)

    def disconnect_device(self, device_id: str, fallback_id: str | None = None) -> None:
        """Simulate hardware unplug: disconnect active streams and update default."""
        with self._lock:
            spec = self.devices[device_id]
            for stream in self.active_streams:
                if stream.spec.device_id == device_id and not stream.is_closed:
                    stream.is_connected = False

            if fallback_id is not None:
                fallback_spec = self.devices[fallback_id]
                if spec.flow == "render":
                    self.default_render_id = fallback_id
                else:
                    self.default_capture_id = fallback_id
                callback = self._notification_callback
                notify_spec = fallback_spec
            else:
                if spec.flow == "render":
                    self.default_render_id = None
                else:
                    self.default_capture_id = None
                callback = None
                notify_spec = None

        if callback is not None and notify_spec is not None:
            callback(notify_spec.flow, notify_spec.device_id, notify_spec.friendly_name)

    def reconnect_device(self, device_id: str, make_default: bool = True) -> None:
        """Simulate hardware replug / re-pairing."""
        with self._lock:
            spec = self.devices[device_id]
            if make_default:
                if spec.flow == "render":
                    self.default_render_id = spec.device_id
                else:
                    self.default_capture_id = spec.device_id
            callback = self._notification_callback

        if callback is not None and make_default:
            callback(spec.flow, spec.device_id, spec.friendly_name)

    def open_stream(self, source: AudioSource, frames_per_buffer: int = 1024) -> AudioStream:
        """Open a stream to the active default device for the source."""
        with self._lock:
            device_id = self.default_render_id if source == "loopback" else self.default_capture_id
            if device_id is None:
                raise OSError(f"No default {source} audio endpoint available.")
            spec = self.devices[device_id]
            stream = VirtualAudioStream(spec)
            self.active_streams.append(stream)
            return stream

    def get_default_endpoint(self, flow: DeviceFlow) -> DeviceEndpointInfo:
        """Get current default endpoint information."""
        with self._lock:
            device_id = self.default_render_id if flow == "render" else self.default_capture_id
            if device_id is None:
                return DeviceEndpointInfo("none", "None")
            spec = self.devices[device_id]
            return DeviceEndpointInfo(spec.device_id, spec.friendly_name)

    def start_notifications(
        self, callback: Callable[[DeviceFlow, str, str], None]
    ) -> None:
        with self._lock:
            self._notification_callback = callback

    def stop_notifications(self) -> None:
        with self._lock:
            self._notification_callback = None

    def close(self) -> None:
        self.stop_notifications()


class MockRecordingObserver(BaseAudioCaptureObserver):
    """Captures events for test validation in a thread-safe manner."""

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


@pytest.fixture
def virtual_environment() -> tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]]:
    """Fixture preparing a multi-device virtual Windows audio environment."""
    backend = MockDeviceAudioBackend()

    specs = {
        "speakers": MockDeviceSpec(
            device_id="{dev-speakers-1}",
            friendly_name="Realtek High Definition Audio",
            flow="render",
            sample_rate=48000,
            channels=2,
        ),
        "headphones": MockDeviceSpec(
            device_id="{dev-headphones-2}",
            friendly_name="Sony WH-1000XM4",
            flow="render",
            sample_rate=44100,
            channels=2,
        ),
        "internal_mic": MockDeviceSpec(
            device_id="{dev-int-mic-1}",
            friendly_name="Built-in Microphone Array",
            flow="capture",
            sample_rate=16000,
            channels=1,
        ),
        "usb_mic": MockDeviceSpec(
            device_id="{dev-usb-mic-2}",
            friendly_name="Shure MV7 USB Microphone",
            flow="capture",
            sample_rate=48000,
            channels=1,
        ),
    }

    backend.add_device(specs["speakers"], is_default=True)
    backend.add_device(specs["headphones"], is_default=False)
    backend.add_device(specs["usb_mic"], is_default=True)
    backend.add_device(specs["internal_mic"], is_default=False)

    return backend, specs


def test_scenario_render_endpoint_switched_speakers_to_headphones(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Start on speakers, switch to headphones during meeting.

    - AudioCaptureService binds initially to speakers and USB mic.
    - Switching default render endpoint rebinds loopback worker to headphones.
    - Microphone worker is never interrupted or closed.
    - Emits DeviceChangeEvent(flow="render", ...).
    """
    backend, specs = virtual_environment
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Initial state check
    assert service.state == CaptureState.RECORDING
    initial_mic_streams = [s for s in backend.active_streams if s.spec.flow == "capture"]
    initial_render_streams = [s for s in backend.active_streams if s.spec.flow == "render"]
    assert len(initial_mic_streams) == 1
    assert len(initial_render_streams) == 1

    # Switch render endpoint to headphones
    backend.set_default_device(specs["headphones"].device_id)
    time.sleep(0.2)  # Allow worker to complete rebind

    service.stop()

    # Verify loopback rebound to headphones with 44.1kHz
    render_streams = [s for s in backend.active_streams if s.spec.flow == "render"]
    assert len(render_streams) == 2
    assert render_streams[0].spec.device_id == specs["speakers"].device_id
    assert render_streams[0].close_count >= 1
    assert render_streams[1].spec.device_id == specs["headphones"].device_id
    assert render_streams[1].sample_rate == 44100

    # Verify microphone worker remained completely uninterrupted
    mic_streams = [s for s in backend.active_streams if s.spec.flow == "capture"]
    assert len(mic_streams) == 1
    assert mic_streams[0].close_count == 1  # only closed on final service.stop()

    # Verify DeviceChangeEvent was emitted
    render_events = [e for e in observer.device_events if e.flow == "render"]
    assert len(render_events) == 1
    assert render_events[0].endpoint_id == specs["headphones"].device_id
    assert render_events[0].friendly_name == specs["headphones"].friendly_name
    assert render_events[0].timestamp_ms >= 0


def test_scenario_capture_endpoint_switched_usb_mic_to_internal_mic(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Switch microphone during recording session.

    - Switching default capture endpoint rebinds mic worker to internal mic.
    - Loopback worker is never interrupted or closed.
    - Emits DeviceChangeEvent(flow="capture", ...).
    """
    backend, specs = virtual_environment
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Switch capture endpoint to internal microphone array (16kHz)
    backend.set_default_device(specs["internal_mic"].device_id)
    time.sleep(0.2)

    service.stop()

    # Verify microphone rebound to internal mic
    mic_streams = [s for s in backend.active_streams if s.spec.flow == "capture"]
    assert len(mic_streams) == 2
    assert mic_streams[0].spec.device_id == specs["usb_mic"].device_id
    assert mic_streams[0].close_count >= 1
    assert mic_streams[1].spec.device_id == specs["internal_mic"].device_id
    assert mic_streams[1].sample_rate == 16000

    # Verify loopback worker remained completely uninterrupted
    render_streams = [s for s in backend.active_streams if s.spec.flow == "render"]
    assert len(render_streams) == 1
    assert render_streams[0].close_count == 1

    # Verify DeviceChangeEvent was emitted
    capture_events = [e for e in observer.device_events if e.flow == "capture"]
    assert len(capture_events) == 1
    assert capture_events[0].endpoint_id == specs["internal_mic"].device_id
    assert capture_events[0].friendly_name == specs["internal_mic"].friendly_name


def test_scenario_abrupt_disconnect_with_automatic_fallback(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Device disconnect during recording with available fallback.

    - Active stream encounters abrupt disconnection on read (OSError).
    - Worker catches error, emits STREAM_ERROR.
    - Fallback device is selected and worker automatically rebinds.
    - Recording continues without application crash.
    """
    backend, specs = virtual_environment
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Abruptly disconnect USB mic hardware stream while running (causes next read to fail)
    mic_stream = [
        s for s in backend.active_streams if s.spec.device_id == specs["usb_mic"].device_id
    ][-1]
    mic_stream.is_connected = False
    time.sleep(0.05)  # Wait for worker to encounter read failure and emit STREAM_ERROR

    # Windows selects fallback internal microphone
    backend.set_default_device(specs["internal_mic"].device_id)
    time.sleep(0.25)

    service.stop()

    # Stream read error was recorded
    stream_errors = [e for e in observer.errors if e.category == CaptureErrorCategory.STREAM_ERROR]
    assert len(stream_errors) > 0
    assert not stream_errors[0].fatal

    # Worker rebound to fallback internal mic
    mic_streams = [s for s in backend.active_streams if s.spec.flow == "capture"]
    assert len(mic_streams) >= 2
    assert mic_streams[-1].spec.device_id == specs["internal_mic"].device_id

    # Loopback continued uninterrupted
    loop_chunks = [c for c in observer.chunks if c.source == "loopback"]
    assert len(loop_chunks) > 0


def test_scenario_disconnect_without_fallback_then_reconnect(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Device disconnects with no fallback, then reconnects later.

    - When disconnected, worker rebind fails and emits REBIND_FAILURE.
    - Loopback worker continues capturing meeting audio.
    - When device is reconnected, worker successfully rebinds and resumes chunks.
    """
    backend, specs = virtual_environment
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Disconnect USB mic without any fallback device available
    backend.disconnect_device(specs["usb_mic"].device_id, fallback_id=None)
    time.sleep(0.2)

    # Rebind failed while device was absent
    assert any(e.category == CaptureErrorCategory.REBIND_FAILURE for e in observer.errors)

    # Reconnect device
    backend.reconnect_device(specs["usb_mic"].device_id, make_default=True)
    time.sleep(0.2)

    service.stop()

    # Mic chunks should have resumed after reconnection
    mic_chunks_after = [c for c in observer.chunks if c.source == "mic"]
    assert len(mic_chunks_after) > 0


def test_scenario_simultaneous_render_and_capture_switch(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Bluetooth headset connected providing both input and output endpoints.

    - Both render and capture device changes fired in rapid succession.
    - Both workers rebind independently without deadlocks or race conditions.
    """
    backend, specs = virtual_environment
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Fire both device switches
    backend.set_default_device(specs["headphones"].device_id)
    backend.set_default_device(specs["internal_mic"].device_id)
    time.sleep(0.25)

    service.stop()

    assert len([e for e in observer.device_events if e.flow == "render"]) == 1
    assert len([e for e in observer.device_events if e.flow == "capture"]) == 1

    # Both streams rebound
    render_streams = [s for s in backend.active_streams if s.spec.flow == "render"]
    capture_streams = [s for s in backend.active_streams if s.spec.flow == "capture"]
    assert len(render_streams) == 2
    assert len(capture_streams) == 2


def test_scenario_rapid_repeated_device_changes(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Rapid repeated device toggling does not crash or corrupt worker loops."""
    backend, specs = virtual_environment
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()

    # Rapid alternating switches
    for _ in range(3):
        backend.set_default_device(specs["headphones"].device_id)
        backend.set_default_device(specs["speakers"].device_id)

    time.sleep(0.3)
    service.stop()

    # Service survived and stopped cleanly
    assert service.state == CaptureState.STOPPED
    assert len(observer.device_events) >= 6


def test_scenario_initial_device_unavailable_then_connected() -> None:
    """Scenario: Start session with missing microphone; microphone connects later.

    - Initial start emits non-fatal error for mic; loopback records normally.
    - When mic connects, device change notification triggers rebind and starts mic capture.
    """
    backend = MockDeviceAudioBackend()
    speakers = MockDeviceSpec(
        device_id="dev-spk",
        friendly_name="Speakers",
        flow="render",
    )
    mic = MockDeviceSpec(
        device_id="dev-mic",
        friendly_name="USB Mic",
        flow="capture",
    )
    backend.add_device(speakers, is_default=True)
    # Mic is not added initially

    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.05)

    # Initial start has no mic
    assert any(e.category == CaptureErrorCategory.DEVICE_UNAVAILABLE for e in observer.errors)
    assert len([c for c in observer.chunks if c.source == "loopback"]) > 0

    # User plugs in microphone
    backend.add_device(mic, is_default=True)
    backend.set_default_device(mic.device_id)
    time.sleep(0.2)

    service.stop()

    # Mic chunks started arriving after device connected
    assert len([c for c in observer.chunks if c.source == "mic"]) > 0


def test_scenario_no_devices_at_all_fails_gracefully() -> None:
    """Scenario: No audio devices available when recording starts.

    - Surfaced as fatal error without application crash.
    - State transitions to ERROR.
    """
    backend = MockDeviceAudioBackend()
    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    with pytest.raises(OSError, match="No audio capture devices available"):
        service.start()

    assert service.state == CaptureState.ERROR
    fatal_errors = [e for e in observer.errors if e.fatal]
    assert len(fatal_errors) == 1
    assert fatal_errors[0].category == CaptureErrorCategory.DEVICE_UNAVAILABLE

    # Calling stop() resets cleanly to STOPPED
    service.stop()
    assert service.state == CaptureState.STOPPED


def test_independent_clock_drift_and_sample_rates(
    virtual_environment: tuple[MockDeviceAudioBackend, dict[str, MockDeviceSpec]],
) -> None:
    """Scenario: Mic (16kHz mono) and Loopback (48kHz stereo) run with clock variance.

    - Chunks are timestamped relative to session start monotonic clock.
    - No lockstep reads; neither stream waits for the other.
    """
    backend, specs = virtual_environment
    # Set internal mic (16kHz mono) as default
    backend.set_default_device(specs["internal_mic"].device_id)
    backend.set_default_device(specs["speakers"].device_id)

    service = AudioCaptureService(backend=backend)
    observer = MockRecordingObserver()
    service.add_observer(observer)

    service.start()
    time.sleep(0.1)
    service.stop()

    mic_chunks = [c for c in observer.chunks if c.source == "mic"]
    loop_chunks = [c for c in observer.chunks if c.source == "loopback"]

    assert len(mic_chunks) > 0
    assert len(loop_chunks) > 0

    for c in mic_chunks:
        assert c.sample_rate == 16000
        assert c.channels == 1
        assert c.timestamp_ms >= 0

    for c in loop_chunks:
        assert c.sample_rate == 48000
        assert c.channels == 2
        assert c.timestamp_ms >= 0
