"""Background worker thread for asynchronous meeting summarization.

Ensures the PySide6 UI event loop remains completely responsive during network
requests, LLM generation, and storage persistence.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from meettrace.storage.models import PersistedTranscript
from meettrace.storage.store import MeetingArtifactStore
from meettrace.summary.models import MeetingSummary, SummaryError
from meettrace.summary.protocol import SummaryProvider

logger = logging.getLogger(__name__)


class SummaryWorker(QThread):
    """Worker thread running AI summarization and atomic persistence off the UI thread."""

    summary_finished = Signal(object)  # Emits MeetingSummary
    summary_failed = Signal(str)  # Emits error message string
    progress_updated = Signal(str)  # Emits status hint

    def __init__(
        self,
        provider: SummaryProvider,
        store: MeetingArtifactStore,
        meeting_id: str,
        transcript: PersistedTranscript,
        language: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._store = store
        self._meeting_id = meeting_id
        self._transcript = transcript
        self._language = language

    def run(self) -> None:
        """Execute summarization and persistence in the worker thread."""
        try:
            self.progress_updated.emit("Generating summary with Gemini...")
            summary: MeetingSummary = self._provider.generate_summary(
                transcript=self._transcript,
                language=self._language,
            )

            self.progress_updated.emit("Saving summary artifacts...")
            self._store.save_summary(
                meeting_id=self._meeting_id,
                summary=summary,
            )

            self.summary_finished.emit(summary)
        except SummaryError as exc:
            logger.warning("Summary generation error: %s", exc)
            self.summary_failed.emit(str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during summary generation")
            self.summary_failed.emit(f"Failed to generate summary: {exc}")
