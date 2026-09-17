"""Unit tests for MeetingSummary domain model, serialization, and SummaryError hierarchy."""

from __future__ import annotations

import dataclasses

import pytest

from meettrace.summary.models import (
    MeetingSummary,
    SummaryAuthError,
    SummaryConfigError,
    SummaryError,
    SummaryNetworkError,
    SummaryParsingError,
    SummaryQuotaError,
)
from meettrace.summary.protocol import SummaryProvider


def test_meeting_summary_instantiation_and_immutability() -> None:
    """Verify MeetingSummary is immutable and preserves structured fields."""
    summary = MeetingSummary(
        summary="Brief overview of discussion.",
        decisions=("Adopt Gemini 2.5 Flash", "Keep raw transcript intact"),
        action_items=("Implement provider protocol", "Wire UI button"),
        open_questions=("Support local models later?",),
        follow_ups=("Review benchmark metrics next week",),
    )

    assert summary.summary == "Brief overview of discussion."
    assert len(summary.decisions) == 2
    assert len(summary.action_items) == 2
    assert len(summary.open_questions) == 1
    assert len(summary.follow_ups) == 1

    with pytest.raises(dataclasses.FrozenInstanceError):
        # Frozen dataclass should reject modification
        summary.summary = "New overview"  # type: ignore[misc]


def test_meeting_summary_serialization_roundtrip() -> None:
    """Verify MeetingSummary to_dict and from_dict produce lossless serialization."""
    original = MeetingSummary(
        summary="Sprint planning meeting.",
        decisions=("Feature frozen on Friday",),
        action_items=("Write tests", "Run linter"),
        open_questions=(),
        follow_ups=("Standup on Monday",),
    )

    d = original.to_dict()
    assert d["summary"] == "Sprint planning meeting."
    assert d["decisions"] == ["Feature frozen on Friday"]
    assert d["action_items"] == ["Write tests", "Run linter"]
    assert d["open_questions"] == []
    assert d["follow_ups"] == ["Standup on Monday"]

    restored = MeetingSummary.from_dict(d)
    assert restored == original


def test_meeting_summary_from_dict_handles_missing_and_none() -> None:
    """Verify from_dict handles partial or malformed dicts gracefully."""
    partial = {"summary": "Only summary text"}
    restored = MeetingSummary.from_dict(partial)
    assert restored.summary == "Only summary text"
    assert restored.decisions == ()
    assert restored.action_items == ()
    assert restored.open_questions == ()
    assert restored.follow_ups == ()

    with_none = {
        "summary": "With none fields",
        "decisions": None,
        "action_items": ["item 1", None, "item 2"],
    }
    restored_none = MeetingSummary.from_dict(with_none)
    assert restored_none.summary == "With none fields"
    assert restored_none.decisions == ()
    assert restored_none.action_items == ("item 1", "item 2")


def test_meeting_summary_to_sections_dict() -> None:
    """Verify to_sections_dict formats markdown section titles and contents."""
    summary = MeetingSummary(
        summary="Key tech decisions.",
        decisions=("Approve design",),
        action_items=("Ship release",),
        open_questions=(),
        follow_ups=(),
    )

    sections = summary.to_sections_dict()
    assert sections["Summary"] == "Key tech decisions."
    assert sections["Decisions"] == "- Approve design"
    assert sections["Action Items"] == "- [ ] Ship release"
    assert "Open Questions" not in sections
    assert "Follow-ups" not in sections


def test_summary_error_hierarchy() -> None:
    """Verify domain error types inherit from SummaryError."""
    assert issubclass(SummaryConfigError, SummaryError)
    assert issubclass(SummaryAuthError, SummaryError)
    assert issubclass(SummaryQuotaError, SummaryError)
    assert issubclass(SummaryNetworkError, SummaryError)
    assert issubclass(SummaryParsingError, SummaryError)


def test_summary_provider_protocol_compliance() -> None:
    """Verify a mock class conforming to SummaryProvider satisfies runtime protocol checks."""

    class MockProvider:
        def generate_summary(
            self,
            transcript: object,
            language: str | None = None,
        ) -> MeetingSummary:
            return MeetingSummary(summary="Mocked")

    mock = MockProvider()
    assert isinstance(mock, SummaryProvider)
