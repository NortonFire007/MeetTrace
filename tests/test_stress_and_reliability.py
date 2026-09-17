"""Stress and reliability tests for MeetTrace.

Covers:
- Task 10.2:
  - Long meeting fast-forward simulation (30 min / 1 hour timeline).
  - Audio rebind gap (2.5s device switch) and timeline continuity.
  - 20 repeated session cycling (start -> pause -> resume -> stop) with thread checks.
  - Resilience against corrupted artifacts (invalid JSON/Markdown).
  - Summary provider failure (503/timeout/network error) raw transcript preservation.
  - Bridge server port collision and abrupt client socket termination.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from typing import Any

import numpy as np
from PySide6.QtCore import QCoreApplication

from meettrace.bridge.server import BridgeServer
from meettrace.capture.backend import AudioStream, DeviceEndpointInfo
from meettrace.capture.models import AudioChunk, AudioSource, CaptureState, DeviceFlow
from meettrace.capture.service import AudioCaptureService
from meettrace.storage.models import PersistedTranscript
from meettrace.storage.repository import MeetingRepository
from meettrace.storage.store import MeetingArtifactStore
from meettrace.summary.models import MeetingSummary, SummaryNetworkError
from meettrace.summary.protocol import SummaryProvider
from meettrace.transcription.models import (
    TranscriptionConfig,
    TranscriptionError,
    TranscriptMetadata,
    TranscriptSegment,
)
from meettrace.transcription.protocol import Transcriber, TranscriptionObserver
from meettrace.transcription.service import TranscriptionService
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.main_window import MainWindow
from meettrace.ui.summary_worker import SummaryWorker


def find_free_port() -> int:
    """Find a free loopback port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StressAudioStream(AudioStream):
    """AudioStream that sleeps briefly to simulate non-blocking hardware I/O."""

    def __init__(self, source: AudioSource, sample_rate: int = 16000, channels: int = 1) -> None:
        self.source = source
        self._sample_rate = sample_rate
        self._channels = channels
        self.is_closed = False

    def read(self, num_frames: int) -> bytes:
        if self.is_closed:
            raise OSError("Stream is closed.")
        time.sleep(0.01)
        return b"\x00\x00" * (num_frames * self._channels)

    def close(self) -> None:
        self.is_closed = True

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels


class StressAudioBackend:
    """Mock audio backend for cycling and stress tests."""

    def __init__(self) -> None:
        self.open_streams: list[StressAudioStream] = []
        self._notification_cb: Any = None

    def open_stream(self, source: AudioSource, frames_per_buffer: int = 1024) -> StressAudioStream:
        stream = StressAudioStream(source=source)
        self.open_streams.append(stream)
        return stream

    def get_default_endpoint(self, flow: DeviceFlow) -> DeviceEndpointInfo:
        return DeviceEndpointInfo(
            endpoint_id=f"{flow}-stress-device",
            friendly_name=f"Stress {flow.capitalize()} Device",
        )

    def start_notifications(self, callback: Any) -> None:
        self._notification_cb = callback

    def stop_notifications(self) -> None:
        self._notification_cb = None

    def close(self) -> None:
        for stream in self.open_streams:
            stream.close()
        self.open_streams.clear()


class SegmentTrackingTranscriber(Transcriber):
    """Transcriber generating deterministic segments tied to audio window start offset."""

    def __init__(self) -> None:
        self._loaded = True

    def load_model(self) -> None:
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        start_offset_ms: int = 0,
        language: str | None = None,
    ) -> list[TranscriptSegment]:
        duration_ms = int(len(audio) * 1000 / sample_rate)
        return [
            TranscriptSegment(
                start_ms=start_offset_ms,
                end_ms=start_offset_ms + duration_ms,
                text=f"Speech segment at {start_offset_ms}ms",
                language=language or "en",
                confidence=0.98,
            )
        ]

    def detect_language(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        return "en", 0.99

    def close(self) -> None:
        self._loaded = False


class StressTranscriptionCollector(TranscriptionObserver):
    """Observer capturing segments, metadata, and errors for reliability validation."""

    def __init__(self) -> None:
        self.segments: list[TranscriptSegment] = []
        self.completed_metadata: TranscriptMetadata | None = None
        self.errors: list[TranscriptionError] = []

    def on_segment(self, segment: TranscriptSegment) -> None:
        self.segments.append(segment)

    def on_error(self, error: TranscriptionError) -> None:
        self.errors.append(error)

    def on_completed(self, metadata: TranscriptMetadata) -> None:
        self.completed_metadata = metadata


class FailingSummaryProvider(SummaryProvider):
    """SummaryProvider simulating network outages, timeouts, or 503 errors."""

    def __init__(self, error_message: str = "Gemini 503 Service Unavailable") -> None:
        self.error_message = error_message

    def generate_summary(
        self,
        transcript: PersistedTranscript,
        language: str | None = None,
    ) -> MeetingSummary:
        raise SummaryNetworkError(self.error_message)


# -----------------------------------------------------------------------------
# 1. Long meeting timeline simulation (30 min / 1 hour)
# -----------------------------------------------------------------------------


def test_long_meeting_timeline_buffering_30min():
    """Verify 30-minute fast-forward timeline buffering without drift or timestamp overlap."""
    transcriber = SegmentTrackingTranscriber()
    config = TranscriptionConfig(window_duration_sec=5, language="en")
    service = TranscriptionService(transcriber=transcriber, config=config)
    collector = StressTranscriptionCollector()
    service.add_observer(collector)

    service.start()

    sample_rate = 16000
    # Simulate 30 minutes in 5-second chunks (360 chunks = 1,800,000 ms)
    chunk_duration_ms = 5000
    chunk_samples = sample_rate * 5
    pcm_data = b"\x01\x00" * chunk_samples

    total_chunks = 360  # 360 * 5s = 1800s = 30 mins
    for i in range(total_chunks):
        ts = i * chunk_duration_ms
        chunk = AudioChunk(
            source="loopback",
            data=pcm_data,
            timestamp_ms=ts,
            duration_ms=chunk_duration_ms,
            sample_rate=sample_rate,
            channels=1,
        )
        service.on_audio_chunk(chunk)

    service.stop()

    # Verify segments
    segments = collector.segments
    assert len(segments) > 0

    # Monotonicity checks
    prev_start = -1
    for seg in segments:
        assert seg.start_ms >= prev_start, f"Timestamp regression: {seg.start_ms} < {prev_start}"
        assert seg.end_ms > seg.start_ms, (
            f"Invalid segment duration: [{seg.start_ms}, {seg.end_ms}]"
        )
        prev_start = seg.start_ms

    assert collector.completed_metadata is not None
    assert collector.completed_metadata.total_duration_ms >= 1800000
    assert len(collector.errors) == 0


def test_long_meeting_timeline_buffering_1hour():
    """Verify 1-hour fast-forward timeline buffering (3,600,000 ms) maintains timeline alignment."""
    transcriber = SegmentTrackingTranscriber()
    config = TranscriptionConfig(window_duration_sec=10, language="en")
    service = TranscriptionService(transcriber=transcriber, config=config)
    collector = StressTranscriptionCollector()
    service.add_observer(collector)

    service.start()

    sample_rate = 16000
    # Simulate 1 hour in 10-second chunks (360 chunks = 3,600,000 ms)
    chunk_duration_ms = 10000
    chunk_samples = sample_rate * 10
    pcm_data = b"\x01\x00" * chunk_samples

    total_chunks = 360  # 360 * 10s = 3600s = 60 mins
    for i in range(total_chunks):
        ts = i * chunk_duration_ms
        chunk = AudioChunk(
            source="mic",
            data=pcm_data,
            timestamp_ms=ts,
            duration_ms=chunk_duration_ms,
            sample_rate=sample_rate,
            channels=1,
        )
        service.on_audio_chunk(chunk)

    service.stop()

    segments = collector.segments
    assert len(segments) > 0

    # Ensure last segment reached the end of the 1-hour window
    last_seg = segments[-1]
    assert last_seg.end_ms >= 3500000

    assert collector.completed_metadata is not None
    assert collector.completed_metadata.total_duration_ms >= 3600000
    assert len(collector.errors) == 0


# -----------------------------------------------------------------------------
# 2. Device switch audio rebind gap simulation
# -----------------------------------------------------------------------------


def test_device_handover_rebind_gap_and_continuity():
    """Verify a 2.5-second rebind gap does not crash transcription or desynchronize timeline."""
    transcriber = SegmentTrackingTranscriber()
    config = TranscriptionConfig(window_duration_sec=2, language="en")
    service = TranscriptionService(transcriber=transcriber, config=config)
    collector = StressTranscriptionCollector()
    service.add_observer(collector)

    service.start()

    sample_rate = 16000
    one_sec_pcm = b"\x01\x00" * sample_rate

    # Emit 5 seconds before gap (0 to 5000 ms)
    for s in range(5):
        service.on_audio_chunk(
            AudioChunk(
                source="mic",
                data=one_sec_pcm,
                timestamp_ms=s * 1000,
                duration_ms=1000,
                sample_rate=sample_rate,
                channels=1,
            )
        )

    # 2.5s gap simulates audio device switch / rebind delay
    # Next chunk arrives at 7500 ms
    for s in range(5):
        ts = 7500 + (s * 1000)
        service.on_audio_chunk(
            AudioChunk(
                source="mic",
                data=one_sec_pcm,
                timestamp_ms=ts,
                duration_ms=1000,
                sample_rate=sample_rate,
                channels=1,
            )
        )

    service.stop()

    segments = collector.segments
    assert len(segments) >= 2

    # Segments before gap must not exceed 5500 ms
    first_group = [s for s in segments if s.start_ms < 5000]
    second_group = [s for s in segments if s.start_ms >= 5000]

    assert len(first_group) > 0
    assert len(second_group) > 0
    # Second group start offsets should reflect the jump
    assert second_group[0].start_ms >= 5000


# -----------------------------------------------------------------------------
# 3. Repeated session cycling (20 start -> pause -> resume -> stop cycles)
# -----------------------------------------------------------------------------


def test_repeated_session_cycling_20_times(qapp):
    """Verify 20 repeated session lifecycles without unhandled errors or thread leaks."""
    backend = StressAudioBackend()
    capture_service = AudioCaptureService(backend=backend)
    controller = RecordingSessionController(capture_service)

    initial_threads = threading.active_count()

    try:
        for _ in range(20):
            # Start
            controller.start()
            assert controller.state == CaptureState.RECORDING

            # Pause
            controller.pause()
            assert controller.state == CaptureState.PAUSED

            # Resume
            controller.resume()
            assert controller.state == CaptureState.RECORDING

            # Stop
            controller.stop()
            assert controller.state == CaptureState.STOPPED

            QCoreApplication.processEvents()

        # Thread leak check: threads should be cleaned up
        time.sleep(0.1)
        final_threads = threading.active_count()
        # Thread count should not have grown by 20+ workers
        assert final_threads <= initial_threads + 2
    finally:
        controller.cleanup()
        backend.close()


# -----------------------------------------------------------------------------
# 4. Resilience to corrupt artifacts
# -----------------------------------------------------------------------------


def test_corrupt_artifact_handling_in_repository_and_ui(tmp_path, qapp, qtbot):
    """Verify repository and MainWindow handle corrupt/truncated files gracefully."""
    storage_root = tmp_path / "meetings"
    bad_meeting_dir = storage_root / "2026" / "09" / "17" / "20260917_000000_corrupt"
    bad_meeting_dir.mkdir(parents=True, exist_ok=True)

    # Write truncated/invalid JSON
    (bad_meeting_dir / "transcript.json").write_text("{ corrupt json ...", encoding="utf-8")
    # Write invalid/empty Markdown
    (bad_meeting_dir / "meeting.md").write_text("Not valid frontmatter", encoding="utf-8")

    repository = MeetingRepository(storage_root=storage_root)
    # Refresh should not crash despite invalid JSON/Markdown
    repository.refresh()

    # get_transcript returns None safely
    assert repository.get_transcript("20260917_000000_corrupt") is None

    # MainWindow loading the corrupt meeting does not crash
    main_window = MainWindow(repository=repository)
    qtbot.addWidget(main_window)
    main_window.open_meeting_reader("20260917_000000_corrupt")
    QCoreApplication.processEvents()

    reader = main_window.meeting_reader_view
    assert reader is not None


# -----------------------------------------------------------------------------
# 5. Summary failure preserves raw transcript
# -----------------------------------------------------------------------------


def test_summary_generation_error_preserves_raw_transcript(tmp_path, qapp, qtbot):
    """Verify that a network/API failure during summarization leaves raw transcript intact."""
    artifact_store = MeetingArtifactStore(storage_root=tmp_path)
    meeting_id = "20260917_180000_summaryfail"

    # Save raw transcript
    segments = [
        TranscriptSegment(
            start_ms=0,
            end_ms=3000,
            text="Crucial meeting discussions.",
            language="en",
            confidence=0.99,
        )
    ]
    json_path, md_path = artifact_store.save_raw_transcript(
        meeting_id=meeting_id,
        segments=segments,
        title="Important Meeting",
    )
    assert json_path.is_file()
    assert md_path.is_file()

    meeting_dir = artifact_store.resolve_meeting_dir(meeting_id)
    transcript = artifact_store.load_transcript(meeting_dir)

    # Run failing SummaryWorker
    failing_provider = FailingSummaryProvider(error_message="Gemini API 503 Overloaded")
    worker = SummaryWorker(
        provider=failing_provider,
        store=artifact_store,
        meeting_id=meeting_id,
        transcript=transcript,
    )

    failed_messages = []
    worker.summary_failed.connect(failed_messages.append)

    with qtbot.waitSignal(worker.summary_failed, timeout=3000):
        worker.start()

    assert len(failed_messages) == 1
    assert "Gemini API 503 Overloaded" in failed_messages[0]

    # Verify raw artifacts were NOT removed or corrupted
    assert json_path.is_file()
    assert md_path.is_file()
    reloaded_transcript = artifact_store.load_transcript(meeting_dir)
    assert len(reloaded_transcript.segments) == 1
    assert reloaded_transcript.segments[0].text == "Crucial meeting discussions."
    # Summary field remains None / not partially written
    assert reloaded_transcript.summary is None


# -----------------------------------------------------------------------------
# 6. Bridge port collision and abrupt socket disconnect
# -----------------------------------------------------------------------------


def test_bridge_port_collision_and_abrupt_disconnect():
    """Verify BridgeServer handles port collisions and abrupt client disconnections gracefully."""
    port = find_free_port()
    token = "stress-bridge-token-999"

    # 1. Simulate port collision by binding raw socket
    blocker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker_socket.bind(("127.0.0.1", port))
    blocker_socket.listen(1)

    server = BridgeServer(token=token, port=port)
    # Startup must fail gracefully without throwing unhandled exception
    started = server.start()
    assert started is False
    assert server.is_running is False
    assert server.last_error is not None

    # Release blocker socket
    blocker_socket.close()

    # Now startup should succeed
    server2 = BridgeServer(token=token, port=port)
    assert server2.start() is True
    assert server2.is_running is True

    try:
        # 2. Abrupt client disconnect: connect, send partial headers, immediately close
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", port))
        s.sendall(b"POST /api/v1/meetings/events HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        s.close()  # abrupt reset

        # Bridge server should continue accepting subsequent valid requests
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("GET", "/api/v1/status", headers={"Authorization": f"Bearer {token}"})
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        conn.close()
    finally:
        server2.stop()
