"""Unit tests for MeetTrace capture domain models, protocols, and broadcaster."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from meettrace.capture import (
    AudioCapture,
    AudioCaptureObserver,
    AudioChunk,
    BaseAudioCaptureObserver,
    CaptureError,
    CaptureErrorCategory,
    CaptureObserverBroadcaster,
    CaptureState,
    DeviceChangeEvent,
    InvalidStateTransitionError,
    can_transition,
    validate_transition,
)


class TestCaptureState:
    """Tests for CaptureState enum and transition rules."""

    def test_all_expected_states_exist(self) -> None:
        """Verify all 7 required capture states exist with string values."""
        expected_states = {
            "idle": CaptureState.IDLE,
            "starting": CaptureState.STARTING,
            "recording": CaptureState.RECORDING,
            "rebinding": CaptureState.REBINDING,
            "paused": CaptureState.PAUSED,
            "stopped": CaptureState.STOPPED,
            "error": CaptureState.ERROR,
        }
        for name, member in expected_states.items():
            assert member.value == name
            assert str(member) == member.value

    @pytest.mark.parametrize(
        ("from_state", "to_state"),
        [
            (CaptureState.IDLE, CaptureState.STARTING),
            (CaptureState.STARTING, CaptureState.RECORDING),
            (CaptureState.STARTING, CaptureState.STOPPED),
            (CaptureState.STARTING, CaptureState.ERROR),
            (CaptureState.RECORDING, CaptureState.PAUSED),
            (CaptureState.RECORDING, CaptureState.REBINDING),
            (CaptureState.RECORDING, CaptureState.STOPPED),
            (CaptureState.RECORDING, CaptureState.ERROR),
            (CaptureState.REBINDING, CaptureState.RECORDING),
            (CaptureState.REBINDING, CaptureState.STOPPED),
            (CaptureState.REBINDING, CaptureState.ERROR),
            (CaptureState.PAUSED, CaptureState.RECORDING),
            (CaptureState.PAUSED, CaptureState.STOPPED),
            (CaptureState.PAUSED, CaptureState.ERROR),
            (CaptureState.STOPPED, CaptureState.IDLE),
            (CaptureState.STOPPED, CaptureState.STARTING),
            (CaptureState.ERROR, CaptureState.IDLE),
            (CaptureState.ERROR, CaptureState.STARTING),
            (CaptureState.ERROR, CaptureState.STOPPED),
        ],
    )
    def test_valid_state_transitions(
        self, from_state: CaptureState, to_state: CaptureState
    ) -> None:
        """Verify that legitimate lifecycle transitions succeed without error."""
        assert can_transition(from_state, to_state) is True
        validate_transition(from_state, to_state)

    @pytest.mark.parametrize(
        ("from_state", "to_state"),
        [
            (CaptureState.IDLE, CaptureState.RECORDING),
            (CaptureState.IDLE, CaptureState.PAUSED),
            (CaptureState.IDLE, CaptureState.REBINDING),
            (CaptureState.PAUSED, CaptureState.REBINDING),
            (CaptureState.STOPPED, CaptureState.RECORDING),
            (CaptureState.STOPPED, CaptureState.PAUSED),
            (CaptureState.REBINDING, CaptureState.PAUSED),
        ],
    )
    def test_invalid_state_transitions(
        self, from_state: CaptureState, to_state: CaptureState
    ) -> None:
        """Verify that illegal transitions fail can_transition and raise exception."""
        assert can_transition(from_state, to_state) is False
        with pytest.raises(InvalidStateTransitionError, match="Cannot transition"):
            validate_transition(from_state, to_state)


class TestAudioChunk:
    """Tests for AudioChunk model, validation, and immutability."""

    def test_valid_chunk_creation(self) -> None:
        """Verify valid AudioChunk creation with mic, loopback, and mixed sources."""
        for source in ("mic", "loopback", "mixed"):
            chunk = AudioChunk(
                source=source,  # type: ignore[arg-type]
                data=b"\x00\x00" * 160,
                timestamp_ms=500,
                duration_ms=10,
                sample_rate=16000,
                channels=1,
            )
            assert chunk.source == source
            assert chunk.data == b"\x00\x00" * 160
            assert chunk.timestamp_ms == 500
            assert chunk.duration_ms == 10
            assert chunk.sample_rate == 16000
            assert chunk.channels == 1

    def test_chunk_immutability(self) -> None:
        """Verify AudioChunk instances are frozen and cannot be mutated."""
        chunk = AudioChunk(
            source="mic",
            data=b"\x00\x00",
            timestamp_ms=0,
            duration_ms=10,
            sample_rate=16000,
            channels=1,
        )
        with pytest.raises(FrozenInstanceError):
            chunk.timestamp_ms = 100  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            chunk.data = b"\x01\x02"  # type: ignore[misc]

    def test_invalid_source_raises(self) -> None:
        """Invalid audio source name should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid audio chunk source"):
            AudioChunk(
                source="speaker",  # type: ignore[arg-type]
                data=b"",
                timestamp_ms=0,
                duration_ms=10,
                sample_rate=16000,
                channels=1,
            )

    def test_non_bytes_data_raises(self) -> None:
        """Data passed as non-bytes should raise TypeError."""
        with pytest.raises(TypeError, match="must be bytes"):
            AudioChunk(
                source="mic",
                data="not bytes",  # type: ignore[arg-type]
                timestamp_ms=0,
                duration_ms=10,
                sample_rate=16000,
                channels=1,
            )

    def test_negative_timestamp_raises(self) -> None:
        """Negative timestamp_ms should raise ValueError."""
        with pytest.raises(ValueError, match="timestamp_ms must be non-negative"):
            AudioChunk(
                source="mic",
                data=b"",
                timestamp_ms=-1,
                duration_ms=10,
                sample_rate=16000,
                channels=1,
            )

    def test_negative_duration_raises(self) -> None:
        """Negative duration_ms should raise ValueError."""
        with pytest.raises(ValueError, match="duration_ms must be non-negative"):
            AudioChunk(
                source="mic",
                data=b"",
                timestamp_ms=0,
                duration_ms=-5,
                sample_rate=16000,
                channels=1,
            )

    def test_invalid_sample_rate_raises(self) -> None:
        """Zero or negative sample_rate should raise ValueError."""
        with pytest.raises(ValueError, match="sample_rate must be positive"):
            AudioChunk(
                source="mic",
                data=b"",
                timestamp_ms=0,
                duration_ms=10,
                sample_rate=0,
                channels=1,
            )

    def test_invalid_channels_raises(self) -> None:
        """Channels other than 1 or 2 should raise ValueError."""
        for invalid_ch in (0, 3, 6):
            with pytest.raises(ValueError, match="channels must be 1 .* or 2"):
                AudioChunk(
                    source="mic",
                    data=b"",
                    timestamp_ms=0,
                    duration_ms=10,
                    sample_rate=16000,
                    channels=invalid_ch,
                )


class TestDeviceChangeEvent:
    """Tests for DeviceChangeEvent model, validation, and immutability."""

    def test_valid_event_creation(self) -> None:
        """Verify DeviceChangeEvent creation for render and capture flows."""
        event_render = DeviceChangeEvent(
            flow="render",
            endpoint_id="{0.0.0.00000000}.{abc-123}",
            friendly_name="Headphones",
            timestamp_ms=1200,
        )
        assert event_render.flow == "render"
        assert event_render.endpoint_id == "{0.0.0.00000000}.{abc-123}"
        assert event_render.friendly_name == "Headphones"
        assert event_render.timestamp_ms == 1200

        event_capture = DeviceChangeEvent(
            flow="capture",
            endpoint_id="{0.0.1.00000000}.{def-456}",
            friendly_name="Microphone",
            timestamp_ms=1500,
        )
        assert event_capture.flow == "capture"

    def test_event_immutability(self) -> None:
        """Verify DeviceChangeEvent is immutable."""
        event = DeviceChangeEvent(
            flow="render",
            endpoint_id="id1",
            friendly_name="Speakers",
            timestamp_ms=0,
        )
        with pytest.raises(FrozenInstanceError):
            event.friendly_name = "New Speakers"  # type: ignore[misc]

    def test_invalid_flow_raises(self) -> None:
        """Invalid flow value should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid device flow"):
            DeviceChangeEvent(
                flow="duplex",  # type: ignore[arg-type]
                endpoint_id="id1",
                friendly_name="Device",
                timestamp_ms=0,
            )

    def test_empty_endpoint_id_raises(self) -> None:
        """Empty endpoint ID should raise ValueError."""
        with pytest.raises(ValueError, match="endpoint_id must not be empty"):
            DeviceChangeEvent(
                flow="render",
                endpoint_id="",
                friendly_name="Device",
                timestamp_ms=0,
            )

    def test_negative_timestamp_raises(self) -> None:
        """Negative timestamp should raise ValueError."""
        with pytest.raises(ValueError, match="timestamp_ms must be non-negative"):
            DeviceChangeEvent(
                flow="render",
                endpoint_id="id1",
                friendly_name="Device",
                timestamp_ms=-10,
            )


class TestCaptureError:
    """Tests for CaptureError model and formatting."""

    def test_default_values(self) -> None:
        """CaptureError should default to fatal=True and category=GENERAL."""
        err = CaptureError(message="Stream failure")
        assert err.message == "Stream failure"
        assert err.fatal is True
        assert err.category == CaptureErrorCategory.GENERAL
        assert err.underlying_exception is None
        assert err.timestamp_ms is None

    def test_str_representation_without_exception(self) -> None:
        """Test formatting string for warning and fatal errors."""
        fatal_err = CaptureError(
            message="No input device found",
            fatal=True,
            category=CaptureErrorCategory.DEVICE_UNAVAILABLE,
        )
        assert str(fatal_err) == "[FATAL][device_unavailable] No input device found"

        warning_err = CaptureError(
            message="Clock drift detected",
            fatal=False,
            category=CaptureErrorCategory.STREAM_ERROR,
        )
        assert str(warning_err) == "[WARNING][stream_error] Clock drift detected"

    def test_str_representation_with_exception(self) -> None:
        """Test formatting string when an underlying exception is attached."""
        cause = OSError("Audio endpoint disconnected")
        err = CaptureError(
            message="Render loopback failed",
            fatal=True,
            category=CaptureErrorCategory.REBIND_FAILURE,
            underlying_exception=cause,
        )
        msg = str(err)
        assert "[FATAL][rebind_failure] Render loopback failed" in msg
        assert "Caused by: OSError: Audio endpoint disconnected" in msg

    def test_immutability(self) -> None:
        """CaptureError should be frozen."""
        err = CaptureError(message="Oops")
        with pytest.raises(FrozenInstanceError):
            err.message = "Changed"  # type: ignore[misc]


class TestProtocolsAndObservers:
    """Tests for protocol conformance and observer dispatcher behavior."""

    def test_base_observer_implements_protocol(self) -> None:
        """BaseAudioCaptureObserver should satisfy AudioCaptureObserver protocol."""
        observer = BaseAudioCaptureObserver()
        assert isinstance(observer, AudioCaptureObserver)

        # Call all base methods to verify they execute cleanly as no-ops
        chunk = AudioChunk("mic", b"\x00", 0, 10, 16000, 1)
        device_evt = DeviceChangeEvent("render", "id1", "Speakers", 0)
        error = CaptureError("Test")

        observer.on_audio_chunk(chunk)
        observer.on_state_changed(CaptureState.RECORDING)
        observer.on_device_changed(device_evt)
        observer.on_error(error)

    def test_audio_capture_protocol_conformance(self) -> None:
        """A class implementing AudioCapture methods satisfies the runtime protocol."""

        class MockCaptureService:
            def __init__(self) -> None:
                self._state = CaptureState.IDLE

            def start(self) -> None:
                self._state = CaptureState.RECORDING

            def stop(self) -> None:
                self._state = CaptureState.STOPPED

            def pause(self) -> None:
                self._state = CaptureState.PAUSED

            def resume(self) -> None:
                self._state = CaptureState.RECORDING

            @property
            def state(self) -> CaptureState:
                return self._state

            def add_observer(self, observer: AudioCaptureObserver) -> None:
                pass

            def remove_observer(self, observer: AudioCaptureObserver) -> None:
                pass

        mock_service = MockCaptureService()
        assert isinstance(mock_service, AudioCapture)

    def test_audio_capture_protocol_non_conformance(self) -> None:
        """A class missing required methods does not satisfy AudioCapture protocol."""

        class IncompleteCaptureService:
            def start(self) -> None:
                pass

        incomplete = IncompleteCaptureService()
        assert not isinstance(incomplete, AudioCapture)


class RecordingTestObserver(BaseAudioCaptureObserver):
    """Test helper observer recording received events."""

    def __init__(self) -> None:
        self.chunks: list[AudioChunk] = []
        self.states: list[CaptureState] = []
        self.device_events: list[DeviceChangeEvent] = []
        self.errors: list[CaptureError] = []

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        self.chunks.append(chunk)

    def on_state_changed(self, state: CaptureState) -> None:
        self.states.append(state)

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        self.device_events.append(event)

    def on_error(self, error: CaptureError) -> None:
        self.errors.append(error)


class FaultyTestObserver(BaseAudioCaptureObserver):
    """Test helper observer that raises exceptions in all handlers."""

    def on_audio_chunk(self, chunk: AudioChunk) -> None:
        raise RuntimeError("Chunk handler crash")

    def on_state_changed(self, state: CaptureState) -> None:
        raise RuntimeError("State handler crash")

    def on_device_changed(self, event: DeviceChangeEvent) -> None:
        raise RuntimeError("Device handler crash")

    def on_error(self, error: CaptureError) -> None:
        raise RuntimeError("Error handler crash")


class TestCaptureObserverBroadcaster:
    """Tests for thread-safe observer dispatcher."""

    def test_add_and_remove_observers(self) -> None:
        """Verify registration, deduplication, and removal."""
        broadcaster = CaptureObserverBroadcaster()
        obs1 = RecordingTestObserver()
        obs2 = RecordingTestObserver()

        assert len(broadcaster.observers) == 0

        broadcaster.add_observer(obs1)
        broadcaster.add_observer(obs1)  # Duplicate should not add twice
        assert broadcaster.observers == (obs1,)

        broadcaster.add_observer(obs2)
        assert broadcaster.observers == (obs1, obs2)

        broadcaster.remove_observer(obs1)
        assert broadcaster.observers == (obs2,)

        # Removing an observer not present should be a no-op
        broadcaster.remove_observer(obs1)
        assert broadcaster.observers == (obs2,)

        broadcaster.clear_observers()
        assert len(broadcaster.observers) == 0

    def test_notification_delivery(self) -> None:
        """Verify events are delivered to all registered observers."""
        broadcaster = CaptureObserverBroadcaster()
        obs1 = RecordingTestObserver()
        obs2 = RecordingTestObserver()
        broadcaster.add_observer(obs1)
        broadcaster.add_observer(obs2)

        chunk = AudioChunk("mic", b"\x01\x02", 100, 10, 16000, 1)
        broadcaster.notify_audio_chunk(chunk)
        assert obs1.chunks == [chunk]
        assert obs2.chunks == [chunk]

        broadcaster.notify_state_changed(CaptureState.RECORDING)
        assert obs1.states == [CaptureState.RECORDING]
        assert obs2.states == [CaptureState.RECORDING]

        event = DeviceChangeEvent("render", "dev-1", "Headphones", 150)
        broadcaster.notify_device_changed(event)
        assert obs1.device_events == [event]
        assert obs2.device_events == [event]

        error = CaptureError("Device removed", fatal=False)
        broadcaster.notify_error(error)
        assert obs1.errors == [error]
        assert obs2.errors == [error]

    def test_fault_tolerance_when_observer_fails(self) -> None:
        """Exceptions in an observer should not crash the broadcaster or affect other observers."""
        broadcaster = CaptureObserverBroadcaster()
        faulty = FaultyTestObserver()
        healthy = RecordingTestObserver()

        broadcaster.add_observer(faulty)
        broadcaster.add_observer(healthy)

        chunk = AudioChunk("loopback", b"\x00\x00", 200, 20, 48000, 2)
        # Should not raise RuntimeError
        broadcaster.notify_audio_chunk(chunk)
        assert healthy.chunks == [chunk]

        broadcaster.notify_state_changed(CaptureState.REBINDING)
        assert healthy.states == [CaptureState.REBINDING]

        event = DeviceChangeEvent("capture", "mic-1", "USB Mic", 250)
        broadcaster.notify_device_changed(event)
        assert healthy.device_events == [event]

        error = CaptureError("Rebind glitch", fatal=False)
        broadcaster.notify_error(error)
        assert healthy.errors == [error]
