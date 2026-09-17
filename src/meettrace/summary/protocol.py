"""Protocol definition for replaceable meeting summary providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from meettrace.storage.models import PersistedTranscript
from meettrace.summary.models import MeetingSummary


@runtime_checkable
class SummaryProvider(Protocol):
    """Backend-agnostic contract for meeting summary generation providers."""

    def generate_summary(
        self,
        transcript: PersistedTranscript,
        language: str | None = None,
    ) -> MeetingSummary:
        """Generate structured meeting summary from a persisted transcript.

        Args:
            transcript: Persisted meeting transcript containing segments and metadata.
            language: Optional explicit target language (e.g., 'en', 'ru', 'uk').
                      If omitted, provider should follow dominant transcript language.

        Returns:
            Structured MeetingSummary instance.

        Raises:
            SummaryConfigError: If configuration (such as API key) is missing.
            SummaryAuthError: If authentication with the provider fails.
            SummaryQuotaError: If quota or rate limits are exceeded.
            SummaryNetworkError: On connection failure, timeout, or server error.
            SummaryParsingError: If model output does not conform to the schema.
        """
        ...
