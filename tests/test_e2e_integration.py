"""End-to-end integration tests for the full MeetTrace meeting lifecycle pipeline.

Tests the logical flow:
recording start -> AudioCaptureService -> AudioChunk -> TranscriptionService ->
TranscriptSegment[] -> MeetingArtifactStore -> transcript.json + meeting.md ->
SummaryProvider -> MeetingRepository -> MeetingReaderView.

Also tests Google Meet extension metadata integration through localhost bridge.
"""

from __future__ import annotations

import http.client
import json
import socket
from typing import Any

import numpy as np
from PySide6.QtCore import QCoreApplication

from meettrace.bridge.adapter import MeetBridgeQtAdapter
from meettrace.bridge.server import BridgeServer
from meettrace.capture.backend import AudioStream, DeviceEndpointInfo
from meettrace.capture.models import AudioChunk, AudioSource, DeviceFlow
from meettrace.capture.service import AudioCaptureService
from meettrace.storage.models import PersistedTranscript
from meettrace.storage.repository import MeetingRepository
from meettrace.storage.store import MeetingArtifactStore
from meettrace.summary.models import MeetingSummary
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


def find_free_port() -> int:
    """Find a free loopback port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


import time


class MockAudioStream(AudioStream):
    """Mock audio stream producing deterministic PCM chunks for testing."""

    def __init__(self, source: AudioSource, sample_rate: int = 16000, channels: int = 1) -> None:
        self.source = source
        self._sample_rate = sample_rate
        self._channels = channels
        self.is_closed = False

    def read(self, num_frames: int) -> bytes:
        if self.is_closed:
            raise OSError("Stream is closed.")
        time.sleep(0.02)
        return b"\x00\x00" * (num_frames * self._channels)

    def close(self) -> None:
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
        self.open_streams: list[MockAudioStream] = []
        self._notification_cb: Any = None

    def open_stream(self, source: AudioSource, frames_per_buffer: int = 1024) -> MockAudioStream:
        stream = MockAudioStream(source=source)
        self.open_streams.append(stream)
        return stream

    def get_default_endpoint(self, flow: DeviceFlow) -> DeviceEndpointInfo:
        return DeviceEndpointInfo(
            endpoint_id=f"{flow}-device-1",
            friendly_name=f"Mock {flow.capitalize()} Device",
        )

    def start_notifications(self, callback: Any) -> None:
        self._notification_cb = callback

    def stop_notifications(self) -> None:
        self._notification_cb = None

    def close(self) -> None:
        for stream in self.open_streams:
            stream.close()
        self.open_streams.clear()


class MockTranscriber(Transcriber):
    """Mock Whisper engine producing deterministic transcript segments."""

    def __init__(self) -> None:
        self._loaded = False

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
        return [
            TranscriptSegment(
                start_ms=start_offset_ms,
                end_ms=start_offset_ms + 4500,
                text="Hello everyone, let's start the sprint review.",
                language=language or "en",
                confidence=0.96,
            ),
            TranscriptSegment(
                start_ms=start_offset_ms + 5000,
                end_ms=start_offset_ms + 9500,
                text="We decided to launch the Windows MVP next Tuesday.",
                language=language or "en",
                confidence=0.98,
            ),
        ]

    def detect_language(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        return "en", 0.99

    def close(self) -> None:
        self._loaded = False


class RecordingTranscriptionCollector(TranscriptionObserver):
    """Observer capturing emitted segments and completion metadata."""

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


class MockSummaryProvider(SummaryProvider):
    """Mock Gemini summary provider generating structured meeting sections."""

    def generate_summary(
        self,
        transcript: PersistedTranscript,
        language: str | None = None,
    ) -> MeetingSummary:
        return MeetingSummary(
            summary="Sprint review covering MVP progress and release targets.",
            decisions=("Launch Windows MVP next Tuesday",),
            action_items=("Package standalone Windows binary",),
            open_questions=(),
            follow_ups=(),
            provider="gemini",
            model="gemini-2.5-flash:mock",
        )


def test_full_pipeline_recording_transcribe_store_and_read(tmp_path, qapp, qtbot):
    """Verify complete end-to-end flow from audio chunks to stored artifacts and UI reader view."""
    # 1. Setup services
    mock_backend = MockAudioBackend()
    capture_service = AudioCaptureService(backend=mock_backend)
    controller = RecordingSessionController(capture_service)

    mock_transcriber = MockTranscriber()
    config = TranscriptionConfig(window_duration_sec=2, language="en")
    transcription_service = TranscriptionService(transcriber=mock_transcriber, config=config)
    collector = RecordingTranscriptionCollector()
    transcription_service.add_observer(collector)

    # Wire capture events to transcription service
    capture_service.add_observer(transcription_service)

    artifact_store = MeetingArtifactStore(storage_root=tmp_path)
    repository = MeetingRepository(storage_root=tmp_path)
    summary_provider = MockSummaryProvider()

    # 2. Start recording session
    controller.start()
    assert controller.state.value == "recording"

    # 3. Simulate audio chunk emission (16-bit PCM silence/synthetic audio)
    sample_rate = 16000
    # 1 second of 16-bit mono audio = 32000 bytes
    one_sec_bytes = b"\x01\x00" * sample_rate
    chunk1 = AudioChunk(
        source="loopback",
        data=one_sec_bytes,
        timestamp_ms=0,
        duration_ms=1000,
        sample_rate=sample_rate,
        channels=1,
    )
    chunk2 = AudioChunk(
        source="mic",
        data=one_sec_bytes,
        timestamp_ms=1000,
        duration_ms=1000,
        sample_rate=sample_rate,
        channels=1,
    )
    chunk3 = AudioChunk(
        source="loopback",
        data=one_sec_bytes,
        timestamp_ms=2000,
        duration_ms=1000,
        sample_rate=sample_rate,
        channels=1,
    )

    capture_service._broadcaster.notify_audio_chunk(chunk1)
    capture_service._broadcaster.notify_audio_chunk(chunk2)
    capture_service._broadcaster.notify_audio_chunk(chunk3)

    # 4. Stop recording and finalize transcription
    controller.stop()
    assert controller.state.value == "stopped"

    # Allow worker thread to drain
    transcription_service.stop()

    segments = collector.segments
    transcript_meta = collector.completed_metadata
    assert len(segments) >= 2
    assert "Hello everyone" in segments[0].text
    assert transcript_meta is not None
    assert transcript_meta.dominant_language == "en"

    # 5. Persist meeting artifacts (meeting.md + transcript.json)
    meeting_id = "20260917_150000_e2etest1"
    json_path, md_path = artifact_store.save_raw_transcript(
        meeting_id=meeting_id,
        segments=segments,
        transcript_metadata=transcript_meta,
        title="Weekly Sprint Review",
        source={"platform": "desktop-app"},
    )
    assert json_path.is_file()
    assert md_path.is_file()

    # Verify JSON content
    meeting_dir = artifact_store.resolve_meeting_dir(meeting_id)
    saved_transcript = artifact_store.load_transcript(meeting_dir)
    assert saved_transcript.meeting_id == meeting_id
    assert len(saved_transcript.segments) == len(segments)

    # 6. Generate and save AI summary
    summary = summary_provider.generate_summary(saved_transcript)
    artifact_store.save_summary(meeting_id, summary)

    updated_transcript = artifact_store.load_transcript(meeting_dir)
    assert updated_transcript.summary is not None
    assert "Launch Windows MVP next Tuesday" in updated_transcript.summary["decisions"]

    # 7. Verify MeetingRepository indexes the meeting correctly
    meetings = repository.list_meetings()
    assert len(meetings) == 1
    assert meetings[0].meeting_id == meeting_id
    assert meetings[0].title == "Weekly Sprint Review"

    # 8. Load in MainWindow and MeetingReaderView
    main_window = MainWindow(repository=repository)
    qtbot.addWidget(main_window)
    main_window.refresh_meetings()
    QCoreApplication.processEvents()

    # Reader view displays transcript and summary
    main_window.open_meeting_reader(meeting_id)
    reader_view = main_window.meeting_reader_view
    assert reader_view is not None
    assert "Weekly Sprint Review" in reader_view._title_label.text()
    browser_text = reader_view._transcript_browser.toPlainText()
    assert "Hello everyone" in browser_text
    assert "Decisions" in browser_text
    controller.cleanup()


def test_google_meet_bridge_to_persisted_meeting_flow(tmp_path, qapp):
    """Verify Google Meet extension event through localhost bridge associates metadata with session."""
    port = find_free_port()
    token = "test-e2e-bridge-token-xyz12345"

    fake_capture = MockAudioBackend()
    capture_service = AudioCaptureService(backend=fake_capture)
    controller = RecordingSessionController(capture_service)
    adapter = MeetBridgeQtAdapter()

    adapter.meeting_detected.connect(controller.on_meeting_detected)
    adapter.meeting_started.connect(controller.on_meeting_started)
    adapter.meeting_ended.connect(controller.on_meeting_ended)

    server = BridgeServer(
        token=token,
        port=port,
        on_event=adapter.handle_event,
    )
    assert server.start() is True

    try:
        # Simulate Chrome extension sending MEETING_STARTED
        event_payload = {
            "event": "MEETING_STARTED",
            "meeting": {
                "url": "https://meet.google.com/eng-sync-2026",
                "title": "Engineering All-Hands",
                "meeting_code": "eng-sync-2026",
                "detected_at": "2026-09-17T16:00:00Z",
                "browser": "chrome",
            },
        }

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3.0)
        conn.request(
            "POST",
            "/api/v1/meetings/events",
            body=json.dumps(event_payload),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        QCoreApplication.processEvents()

        # Controller should have received and registered the context
        assert controller.current_meet_context is not None
        assert controller.current_meet_context.title == "Engineering All-Hands"
        assert controller.current_meet_context.meeting_code == "eng-sync-2026"

        # Start recording -> session inherits Meet metadata
        controller.start()
        assert controller.state.value == "recording"

        session_meta = controller.get_session_metadata()
        assert session_meta["title"] == "Engineering All-Hands"
        assert session_meta["source"]["platform"] == "google-meet"
        assert session_meta["source"]["url"] == "https://meet.google.com/eng-sync-2026"

        controller.stop()

        # Persist meeting with metadata
        artifact_store = MeetingArtifactStore(storage_root=tmp_path)
        meeting_id = "20260917_160000_meettest2"
        json_path, md_path = artifact_store.save_raw_transcript(
            meeting_id=meeting_id,
            segments=[],
            title=session_meta["title"],
            source=session_meta["source"],
        )
        assert json_path.is_file()

        # Check markdown header contains Meet URL and Title
        md_content = md_path.read_text(encoding="utf-8")
        assert "Engineering All-Hands" in md_content
        assert "https://meet.google.com/eng-sync-2026" in md_content
    finally:
        controller.cleanup()
        server.stop()
