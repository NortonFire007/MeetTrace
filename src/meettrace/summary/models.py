"""Domain models and exceptions for meeting summarization.

Defines versioned, provider-neutral summary data structures, section mapping,
serialization helpers, and typed exception hierarchies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


class SummaryError(Exception):
    """Base exception for all summarization errors."""


class SummaryConfigError(SummaryError):
    """Raised when provider configuration (e.g. API key) is missing or invalid."""


class SummaryAuthError(SummaryError):
    """Raised when authentication fails (invalid API key or unauthorized)."""


class SummaryQuotaError(SummaryError):
    """Raised when API rate limits or quota are exceeded."""


class SummaryNetworkError(SummaryError):
    """Raised on network connection errors, timeouts, or 5xx server errors."""


class SummaryParsingError(SummaryError):
    """Raised when model output cannot be parsed into structured summary schema."""


@dataclass(frozen=True, slots=True)
class MeetingSummary:
    """Structured meeting summary domain model.

    Attributes:
        summary: High-level narrative summary of the meeting.
        decisions: Concrete decisions agreed upon during the discussion.
        action_items: Specific tasks with owners and deadlines if mentioned.
        open_questions: Unresolved topics or questions requiring further discussion.
        follow_ups: Next steps, follow-up meetings, or scheduled reviews.
        provider: Provider identifier (e.g., 'gemini', 'ollama').
        model: Specific model name used (e.g., 'gemini-2.5-flash').
        created_at: ISO-8601 timestamp of summary creation.
    """

    summary: str
    decisions: tuple[str, ...] = field(default_factory=tuple)
    action_items: tuple[str, ...] = field(default_factory=tuple)
    open_questions: tuple[str, ...] = field(default_factory=tuple)
    follow_ups: tuple[str, ...] = field(default_factory=tuple)
    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_sections_dict(self) -> dict[str, str]:
        """Convert structured fields to ordered Markdown sections for meeting.md.

        Returns:
            Dictionary mapping section headings to formatted Markdown text.
        """
        sections: dict[str, str] = {}

        if self.summary:
            sections["Summary"] = self.summary.strip()

        if self.decisions:
            sections["Decisions"] = "\n".join(f"- {d.strip()}" for d in self.decisions if d.strip())

        if self.action_items:
            sections["Action Items"] = "\n".join(
                f"- [ ] {a.strip()}" for a in self.action_items if a.strip()
            )

        if self.open_questions:
            sections["Open Questions"] = "\n".join(
                f"- {q.strip()}" for q in self.open_questions if q.strip()
            )

        if self.follow_ups:
            sections["Follow-ups"] = "\n".join(
                f"- {f.strip()}" for f in self.follow_ups if f.strip()
            )

        return sections

    def to_dict(self) -> dict[str, Any]:
        """Serialize MeetingSummary to JSON-compatible dictionary."""
        data = asdict(self)
        data["decisions"] = list(self.decisions)
        data["action_items"] = list(self.action_items)
        data["open_questions"] = list(self.open_questions)
        data["follow_ups"] = list(self.follow_ups)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetingSummary:
        """Construct MeetingSummary from JSON dictionary."""

        def _clean_str_list(val: Any) -> tuple[str, ...]:
            if not val or not isinstance(val, (list, tuple)):
                return ()
            return tuple(str(x) for x in val if x is not None)

        return cls(
            summary=str(data.get("summary", "")),
            decisions=_clean_str_list(data.get("decisions")),
            action_items=_clean_str_list(data.get("action_items")),
            open_questions=_clean_str_list(data.get("open_questions")),
            follow_ups=_clean_str_list(data.get("follow_ups")),
            provider=str(data.get("provider", "gemini")),
            model=str(data.get("model", "gemini-2.5-flash")),
            created_at=str(data.get("created_at", "")),
        )
