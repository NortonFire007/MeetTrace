"""Domain models and schemas for persisted meeting artifacts.

Provides backend-agnostic, versioned immutable data structures representing
persisted meeting metadata, ordered transcript segments, and word timings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from meettrace.transcription.models import (
    TranscriptMetadata,
    TranscriptSegment,
    TranscriptWord,
)

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class PersistedWord:
    """Word-level timing information stored in transcript artifacts.

    Attributes:
        word: The spoken word text.
        start_ms: Offset in milliseconds from session start.
        end_ms: Offset in milliseconds from session start.
        probability: Confidence score (0.0 to 1.0).
    """

    word: str
    start_ms: int
    end_ms: int
    probability: float = 1.0

    @classmethod
    def from_transcript_word(cls, word: TranscriptWord) -> PersistedWord:
        return cls(
            word=word.word,
            start_ms=word.start_ms,
            end_ms=word.end_ms,
            probability=word.probability,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PersistedSegment:
    """Discrete timestamped transcript segment stored in transcript artifacts.

    Attributes:
        text: Transcribed spoken text.
        start_ms: Start time offset in milliseconds from session start.
        end_ms: End time offset in milliseconds from session start.
        language: Detected or configured language code (e.g., 'en', 'ru', 'uk').
        confidence: Average segment confidence probability (0.0 to 1.0) if provided.
        words: Optional word-level timing details.
    """

    text: str
    start_ms: int
    end_ms: int
    language: str
    confidence: float | None = None
    words: tuple[PersistedWord, ...] = field(default_factory=tuple)

    @classmethod
    def from_transcript_segment(cls, seg: TranscriptSegment) -> PersistedSegment:
        words = tuple(PersistedWord.from_transcript_word(w) for w in seg.words)
        return cls(
            text=seg.text,
            start_ms=seg.start_ms,
            end_ms=seg.end_ms,
            language=seg.language,
            confidence=seg.confidence,
            words=words,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "language": self.language,
            "confidence": self.confidence,
            "words": [w.to_dict() for w in self.words],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersistedSegment:
        raw_words = data.get("words", [])
        words = tuple(
            PersistedWord(
                word=w["word"],
                start_ms=w["start_ms"],
                end_ms=w["end_ms"],
                probability=float(w.get("probability", 1.0)),
            )
            for w in raw_words
        )
        return cls(
            text=str(data["text"]),
            start_ms=int(data["start_ms"]),
            end_ms=int(data["end_ms"]),
            language=str(data["language"]),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            words=words,
        )


@dataclass(frozen=True, slots=True)
class PersistedTranscript:
    """Structured transcript document serialized as transcript.json.

    Attributes:
        meeting_id: Unique meeting identifier.
        metadata: Aggregated session/transcript metadata.
        segments: Ordered sequence of transcript segments.
        schema_version: Schema version for backwards compatibility.
    """

    meeting_id: str
    metadata: TranscriptMetadata
    segments: tuple[PersistedSegment, ...] = field(default_factory=tuple)
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_segments(
        cls,
        meeting_id: str,
        metadata: TranscriptMetadata,
        segments: Sequence[TranscriptSegment | PersistedSegment],
        schema_version: str = SCHEMA_VERSION,
    ) -> PersistedTranscript:
        converted: list[PersistedSegment] = []
        for s in segments:
            if isinstance(s, PersistedSegment):
                converted.append(s)
            elif isinstance(s, TranscriptSegment):
                converted.append(PersistedSegment.from_transcript_segment(s))
            else:
                raise TypeError(f"Unsupported segment type: {type(s)}")
        return cls(
            meeting_id=meeting_id,
            metadata=metadata,
            segments=tuple(converted),
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "meeting_id": self.meeting_id,
            "metadata": {
                "session_id": self.metadata.session_id,
                "dominant_language": self.metadata.dominant_language,
                "detected_languages": self.metadata.detected_languages,
                "model_name": self.metadata.model_name,
                "total_duration_ms": self.metadata.total_duration_ms,
                "segment_count": self.metadata.segment_count,
                "created_at": self.metadata.created_at,
            },
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersistedTranscript:
        meta_dict = data.get("metadata", {})
        metadata = TranscriptMetadata(
            session_id=meta_dict.get("session_id"),
            dominant_language=meta_dict.get("dominant_language"),
            detected_languages=meta_dict.get("detected_languages", {}),
            model_name=meta_dict.get("model_name", "faster-whisper:base"),
            total_duration_ms=int(meta_dict.get("total_duration_ms", 0)),
            segment_count=int(meta_dict.get("segment_count", 0)),
            created_at=str(meta_dict.get("created_at", "")),
        )
        segments = tuple(PersistedSegment.from_dict(s) for s in data.get("segments", []))
        return cls(
            meeting_id=str(data["meeting_id"]),
            metadata=metadata,
            segments=segments,
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(frozen=True, slots=True)
class MeetingMetadata:
    """Domain model capturing full metadata of a meeting recording session.

    Attributes:
        meeting_id: Unique meeting identifier (e.g. 20260917_153000_a1b2c3d4).
        title: User-defined or auto-generated meeting title.
        started_at: ISO-8601 formatted start timestamp with timezone.
        ended_at: ISO-8601 formatted end timestamp with timezone.
        duration_ms: Total duration in milliseconds.
        dominant_language: Primary language identified across segments.
        detected_languages: Occurrence distribution of detected languages.
        source: Source application or platform metadata (e.g., {"platform": "google-meet"}).
        model_name: Name of transcription model used.
        segment_count: Total count of transcript segments.
        schema_version: Version identifier for persisted metadata format.
        created_at: ISO-8601 creation timestamp of the metadata record.
    """

    meeting_id: str
    title: str = "Meeting"
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    dominant_language: str | None = None
    detected_languages: dict[str, float] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    model_name: str = "faster-whisper:base"
    segment_count: int = 0
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetingMetadata:
        return cls(
            meeting_id=str(data["meeting_id"]),
            title=str(data.get("title", "Meeting")),
            started_at=str(data.get("started_at", "")),
            ended_at=str(data.get("ended_at", "")),
            duration_ms=int(data.get("duration_ms", 0)),
            dominant_language=data.get("dominant_language"),
            detected_languages=data.get("detected_languages", {}),
            source=data.get("source", {}),
            model_name=str(data.get("model_name", "faster-whisper:base")),
            segment_count=int(data.get("segment_count", 0)),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            created_at=str(data.get("created_at", "")),
        )
