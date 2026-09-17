"""Meeting detail reader view for MeetTrace.

Renders meeting metadata and timestamped transcript with soft violet highlights,
smooth scrolling, full Unicode (RU/EN/UK) fidelity, Copy Markdown, and Open Folder actions.
"""

from __future__ import annotations

import html
import logging
import os
from typing import Any, Final

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QCursor,
    QDesktopServices,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from meettrace.storage.markdown import format_timestamp_ms
from meettrace.storage.models import MeetingMetadata
from meettrace.storage.repository import MeetingRepository, parse_datetime_safe
from meettrace.summary.gemini import (
    DEFAULT_GEMINI_MODEL,
    GeminiConfig,
    GeminiSummaryProvider,
)
from meettrace.summary.models import MeetingSummary
from meettrace.ui.summary_worker import SummaryWorker
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_SURFACE,
    COLOR_BG_SURFACE_HOVER,
    COLOR_BORDER_DEFAULT,
    COLOR_ERROR_BG,
    COLOR_ERROR_BORDER,
    COLOR_ERROR_RED,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_SOFT,
    COLOR_PRIMARY_SOFT_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_FAMILY,
    get_reader_html_stylesheet,
)
from meettrace.ui.views.meeting_list_view import format_meeting_duration

logger = logging.getLogger(__name__)

COPY_FEEDBACK_MS: Final[int] = 2000


def format_meeting_date_long(dt_str: str) -> str:
    """Format ISO datetime string to readable date 'Sep 17, 2026'."""
    dt = parse_datetime_safe(dt_str)
    if dt is None:
        return "Unknown Date"
    local_dt = dt.astimezone()
    # Format e.g. "Sep 17, 2026"
    month_name = local_dt.strftime("%b")
    return f"{month_name} {local_dt.day}, {local_dt.year}"


class MeetingReaderView(QWidget):
    """Detailed meeting transcript reader with metadata, AI summary, and document actions."""

    back_requested = Signal()

    def __init__(
        self,
        repository: MeetingRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._meeting_id: str | None = None
        self._current_metadata: MeetingMetadata | None = None
        self._summary_worker: SummaryWorker | None = None

        self._init_ui()
        self._setup_shortcuts()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(28, 20, 28, 20)
        root_layout.setSpacing(14)

        # ---------------------------------------------------------------------
        # 1. Top navigation & actions bar
        # ---------------------------------------------------------------------
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        # Back to Meetings button
        self._back_button = QPushButton("← Meetings", self)
        self._back_button.setObjectName("backToMeetingsButton")
        self._back_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._back_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                color: {COLOR_TEXT_SECONDARY};
                font-family: {FONT_FAMILY};
                font-size: 13px;
                font-weight: 500;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_BG_SURFACE_HOVER};
                color: {COLOR_TEXT_PRIMARY};
            }}
            """
        )
        self._back_button.clicked.connect(self.back_requested.emit)
        top_bar.addWidget(self._back_button)

        top_bar.addStretch(1)

        # Action 1: Refresh button
        self._refresh_button = QPushButton("↻ Refresh", self)
        self._refresh_button.setObjectName("readerRefreshButton")
        self._refresh_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_button.setToolTip("Reload meeting data (F5)")
        self._refresh_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 6px;
                color: {COLOR_TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 500;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_BG_SURFACE_HOVER};
                border: 1px solid #CBD5E1;
            }}
            """
        )
        self._refresh_button.clicked.connect(self._on_refresh_clicked)
        top_bar.addWidget(self._refresh_button)

        # Action 2: Open Folder button
        self._open_folder_button = QPushButton("📁 Open Folder", self)
        self._open_folder_button.setObjectName("readerOpenFolderButton")
        self._open_folder_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_folder_button.setToolTip("Open meeting directory in Windows Explorer")
        self._open_folder_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 6px;
                color: {COLOR_TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 500;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_BG_SURFACE_HOVER};
                border: 1px solid #CBD5E1;
            }}
            """
        )
        self._open_folder_button.clicked.connect(self._on_open_folder_clicked)
        top_bar.addWidget(self._open_folder_button)

        # Action 3: Generate/Regenerate Summary button
        self._generate_summary_button = QPushButton("✨ Generate Summary", self)
        self._generate_summary_button.setObjectName("readerGenerateSummaryButton")
        self._generate_summary_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._generate_summary_button.setToolTip("Generate or update AI summary with Gemini")
        self._generate_summary_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY_SOFT};
                border: 1px solid {COLOR_PRIMARY_SOFT_BORDER};
                border-radius: 6px;
                color: {COLOR_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 600;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: #E9E3FE;
                border: 1px solid {COLOR_PRIMARY};
            }}
            QPushButton:disabled {{
                background-color: {COLOR_BG_SURFACE_HOVER};
                color: {COLOR_TEXT_MUTED};
                border: 1px solid {COLOR_BORDER_DEFAULT};
            }}
            """
        )
        self._generate_summary_button.clicked.connect(self._on_generate_summary_clicked)
        top_bar.addWidget(self._generate_summary_button)

        # Action 4: Copy Markdown button (Primary soft violet styling)
        self._copy_markdown_button = QPushButton("📋 Copy Markdown", self)
        self._copy_markdown_button.setObjectName("readerCopyMarkdownButton")
        self._copy_markdown_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._copy_markdown_button.setToolTip("Copy exact meeting.md content to clipboard")
        self._copy_markdown_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_PRIMARY};
                border-radius: 6px;
                color: {COLOR_TEXT_WHITE};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 600;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
                border: 1px solid {COLOR_PRIMARY_HOVER};
            }}
            """
        )
        self._copy_markdown_button.clicked.connect(self._on_copy_markdown_clicked)
        top_bar.addWidget(self._copy_markdown_button)

        root_layout.addLayout(top_bar)

        # ---------------------------------------------------------------------
        # Error Banner (hidden by default)
        # ---------------------------------------------------------------------
        self._error_banner = QFrame(self)
        self._error_banner.setObjectName("readerErrorBanner")
        self._error_banner.setVisible(False)
        self._error_banner.setStyleSheet(
            f"""
            QFrame#readerErrorBanner {{
                background-color: {COLOR_ERROR_BG};
                border: 1px solid {COLOR_ERROR_BORDER};
                border-radius: 8px;
            }}
            """
        )
        banner_layout = QHBoxLayout(self._error_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        banner_layout.setSpacing(8)

        self._error_label = QLabel(self._error_banner)
        self._error_label.setObjectName("readerErrorLabel")
        self._error_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; color: {COLOR_ERROR_RED}; font-weight: 500;"
        )
        self._error_label.setWordWrap(True)
        banner_layout.addWidget(self._error_label, stretch=1)

        error_dismiss_btn = QPushButton("✕", self._error_banner)
        error_dismiss_btn.setObjectName("readerErrorDismissButton")
        error_dismiss_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        error_dismiss_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLOR_ERROR_RED};
                font-size: 13px;
                font-weight: bold;
                padding: 2px 6px;
            }}
            QPushButton:hover {{
                background-color: #FEE2E2;
                border-radius: 4px;
            }}
            """
        )
        error_dismiss_btn.clicked.connect(self._hide_error)
        banner_layout.addWidget(error_dismiss_btn)

        root_layout.addWidget(self._error_banner)

        # ---------------------------------------------------------------------
        # 2. Meeting Header (Title & Subtitle metadata)
        # ---------------------------------------------------------------------
        header_card = QFrame(self)
        header_card.setObjectName("readerHeaderCard")
        header_card.setStyleSheet(
            f"""
            QFrame#readerHeaderCard {{
                background-color: {COLOR_BG_CARD};
                border-bottom: 1px solid {COLOR_BORDER_DEFAULT};
                padding-bottom: 14px;
            }}
            """
        )
        h_layout = QVBoxLayout(header_card)
        h_layout.setContentsMargins(0, 4, 0, 8)
        h_layout.setSpacing(6)

        self._title_label = QLabel("Loading meeting...", header_card)
        self._title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 20px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        self._title_label.setWordWrap(True)
        h_layout.addWidget(self._title_label)

        self._subtitle_label = QLabel("", header_card)
        self._subtitle_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; font-weight: 500; color: {COLOR_TEXT_SECONDARY};"
        )

        h_layout.addWidget(self._subtitle_label)

        root_layout.addWidget(header_card)

        # ---------------------------------------------------------------------
        # 3. Transcript Body Section
        # ---------------------------------------------------------------------
        body_section_label = QLabel("Transcript", self)
        body_section_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 15px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        root_layout.addWidget(body_section_label)

        self._transcript_browser = QTextBrowser(self)
        self._transcript_browser.setObjectName("transcriptBrowser")
        self._transcript_browser.setOpenExternalLinks(False)
        self._transcript_browser.setReadOnly(True)
        self._transcript_browser.setStyleSheet(
            f"""
            QTextBrowser#transcriptBrowser {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 8px;
            }}
            """
        )
        root_layout.addWidget(self._transcript_browser, stretch=1)

    def _setup_shortcuts(self) -> None:
        """Register convenient keyboard shortcuts for navigation and refresh."""
        # Esc to navigate back to meeting list
        esc_action = QAction(self)
        esc_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        esc_action.triggered.connect(self.back_requested.emit)
        self.addAction(esc_action)

        # Alt+Left to navigate back
        alt_left_action = QAction(self)
        alt_left_action.setShortcut(QKeySequence("Alt+Left"))
        alt_left_action.triggered.connect(self.back_requested.emit)
        self.addAction(alt_left_action)

        # F5 to refresh
        f5_action = QAction(self)
        f5_action.setShortcut(QKeySequence(Qt.Key.Key_F5))
        f5_action.triggered.connect(self._on_refresh_clicked)
        self.addAction(f5_action)

    def load_meeting(self, meeting_id: str) -> None:
        """Load and render the requested meeting transcript, AI summary, and metadata."""
        self._cleanup_worker()
        self._hide_error()

        self._meeting_id = meeting_id
        meta = self._repository.get_meeting(meeting_id)
        self._current_metadata = meta

        if meta is None:
            self._title_label.setText("Meeting not found")
            self._subtitle_label.setText(f"Unable to locate artifacts for {meeting_id}")
            self._generate_summary_button.setText("✨ Generate Summary")
            self._generate_summary_button.setEnabled(False)
            self._transcript_browser.setHtml(
                f"{get_reader_html_stylesheet()}<div class='empty-transcript'>Meeting directory not found.</div>"
            )
            return

        # Render Header
        self._title_label.setText(meta.title)

        date_text = format_meeting_date_long(meta.started_at)
        dur_text = format_meeting_duration(meta.duration_ms)

        platform = meta.source.get("platform") if isinstance(meta.source, dict) else None
        platform_text = str(platform) if platform else "Audio Session"
        if platform_text.lower() == "google-meet":
            platform_text = "Google Meet"

        langs = []
        if meta.detected_languages:
            langs = [l.upper() for l in meta.detected_languages]
        elif meta.dominant_language:
            langs = [meta.dominant_language.upper()]
        lang_text = " / ".join(langs) if langs else "AUTO"

        self._subtitle_label.setText(
            f"{date_text}  •  {dur_text}  •  {platform_text}  •  {lang_text}"
        )

        # Retrieve transcript & summary
        transcript = self._repository.get_transcript(meeting_id)
        summary = self._repository.get_summary(meeting_id)

        has_segments = bool(transcript and transcript.segments)
        if summary is not None:
            self._generate_summary_button.setText("↻ Regenerate Summary")
            self._generate_summary_button.setEnabled(has_segments)
        else:
            self._generate_summary_button.setText("✨ Generate Summary")
            self._generate_summary_button.setEnabled(has_segments)

        html_content = [get_reader_html_stylesheet(), "<div>"]

        # Render Summary Card if available
        if summary is not None:
            html_content.append("<div class='summary-card'>")
            html_content.append("<span class='summary-badge'>AI SUMMARY</span>")

            if summary.summary:
                html_content.append(
                    "<div class='summary-section'>"
                    "<div class='summary-section-title'>Summary</div>"
                    f"<div class='summary-text'>{html.escape(summary.summary)}</div>"
                    "</div>"
                )

            if summary.decisions:
                html_content.append(
                    "<div class='summary-section'>"
                    "<div class='summary-section-title'>Decisions</div>"
                    "<ul class='summary-list'>"
                )
                for item in summary.decisions:
                    html_content.append(f"<li>{html.escape(item)}</li>")
                html_content.append("</ul></div>")

            if summary.action_items:
                html_content.append(
                    "<div class='summary-section'>"
                    "<div class='summary-section-title'>Action Items</div>"
                    "<ul class='summary-list'>"
                )
                for item in summary.action_items:
                    html_content.append(f"<li>{html.escape(item)}</li>")
                html_content.append("</ul></div>")

            if summary.open_questions:
                html_content.append(
                    "<div class='summary-section'>"
                    "<div class='summary-section-title'>Open Questions</div>"
                    "<ul class='summary-list'>"
                )
                for item in summary.open_questions:
                    html_content.append(f"<li>{html.escape(item)}</li>")
                html_content.append("</ul></div>")

            if summary.follow_ups:
                html_content.append(
                    "<div class='summary-section'>"
                    "<div class='summary-section-title'>Follow-ups</div>"
                    "<ul class='summary-list'>"
                )
                for item in summary.follow_ups:
                    html_content.append(f"<li>{html.escape(item)}</li>")
                html_content.append("</ul></div>")

            html_content.append("</div>")
            html_content.append("<div class='section-divider'></div>")
            html_content.append("<div class='section-header'>Transcript</div>")

        # Render Transcript Segments
        if transcript is None or not transcript.segments:
            html_content.append(
                "<div class='empty-transcript'>No speech detected in this recording.</div>"
            )
        else:
            for seg in transcript.segments:
                time_str = format_timestamp_ms(seg.start_ms)
                # html.escape preserves Unicode RU/EN/UK safely while escaping HTML tags
                escaped_text = html.escape(seg.text.strip())
                if escaped_text:
                    html_content.append(
                        f"<div class='segment'>"
                        f"<span class='timestamp'>{time_str}</span> "
                        f"<span class='spoken-text'>{escaped_text}</span>"
                        f"</div>"
                    )

        html_content.append("</div>")
        self._transcript_browser.setHtml("".join(html_content))

    def _on_generate_summary_clicked(self) -> None:
        """Trigger background summary generation using configured Gemini provider."""
        if not self._meeting_id:
            return

        transcript = self._repository.get_transcript(self._meeting_id)
        if transcript is None or not transcript.segments:
            self._show_error("Cannot generate summary for an empty transcript.")
            return

        # Check API key from QSettings or environment
        settings = QSettings("MeetTrace", "MeetTrace")
        api_key = (
            str(settings.value("gemini_api_key", "")).strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
        )

        if not api_key:
            self._show_error(
                "Gemini API key not configured. Please enter your API key in Settings or set GEMINI_API_KEY."
            )
            return

        model = (
            str(settings.value("gemini_model", DEFAULT_GEMINI_MODEL)).strip()
            or DEFAULT_GEMINI_MODEL
        )

        self._hide_error()
        self._generate_summary_button.setEnabled(False)
        self._generate_summary_button.setText("⏳ Generating...")

        lang = self._current_metadata.dominant_language if self._current_metadata else None

        config = GeminiConfig(api_key=api_key, model=model)
        provider = GeminiSummaryProvider(config=config)

        self._summary_worker = SummaryWorker(
            provider=provider,
            store=self._repository.store,
            meeting_id=self._meeting_id,
            transcript=transcript,
            language=lang,
            parent=self,
        )
        self._summary_worker.summary_finished.connect(self._on_summary_finished)
        self._summary_worker.summary_failed.connect(self._on_summary_failed)
        self._summary_worker.start()

    def _on_summary_finished(self, summary: MeetingSummary) -> None:
        """Handle successful summary generation."""
        logger.info("Summary generated successfully for %s", self._meeting_id)
        if self._meeting_id:
            self._repository.refresh()
            self.load_meeting(self._meeting_id)

    def _on_summary_failed(self, error_message: str) -> None:
        """Handle summary generation failure gracefully without losing data."""
        logger.warning("Summary generation failed for %s: %s", self._meeting_id, error_message)
        self._show_error(f"Summary generation failed: {error_message}")
        has_summary = (
            self._meeting_id is not None
            and self._repository.get_summary(self._meeting_id) is not None
        )
        self._generate_summary_button.setText(
            "↻ Regenerate Summary" if has_summary else "✨ Generate Summary"
        )
        has_segments = bool(
            self._meeting_id
            and (t := self._repository.get_transcript(self._meeting_id))
            and t.segments
        )
        self._generate_summary_button.setEnabled(has_segments)

    def _show_error(self, message: str) -> None:
        """Show error banner with message."""
        self._error_label.setText(message)
        self._error_banner.setVisible(True)

    def _hide_error(self) -> None:
        """Hide error banner."""
        self._error_banner.setVisible(False)
        self._error_label.setText("")

    def _cleanup_worker(self) -> None:
        """Safely terminate any in-flight summary worker before navigation or closing."""
        if self._summary_worker is not None and self._summary_worker.isRunning():
            self._summary_worker.quit()
            self._summary_worker.wait(500)
            self._summary_worker = None

    def closeEvent(self, event: Any) -> None:
        """Clean up threads on close."""
        self._cleanup_worker()
        super().closeEvent(event)

    def _on_copy_markdown_clicked(self) -> None:
        """Copy exact meeting.md content to the system clipboard."""
        if self._meeting_id is None:
            return

        md_content = self._repository.get_meeting_markdown(self._meeting_id)
        if md_content is None:
            logger.warning("No markdown found to copy for %s", self._meeting_id)
            return

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(md_content)

        # Temporary visual feedback
        self._copy_markdown_button.setText("✓ Copied!")
        self._copy_markdown_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #10B981;
                border: 1px solid #10B981;
                border-radius: 6px;
                color: {COLOR_TEXT_WHITE};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 600;
                padding: 6px 14px;
            }}
            """
        )
        QTimer.singleShot(COPY_FEEDBACK_MS, self._restore_copy_button)

    def _restore_copy_button(self) -> None:
        """Restore Copy Markdown button text and styling."""
        self._copy_markdown_button.setText("📋 Copy Markdown")
        self._copy_markdown_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_PRIMARY};
                border-radius: 6px;
                color: {COLOR_TEXT_WHITE};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 600;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
                border: 1px solid {COLOR_PRIMARY_HOVER};
            }}
            """
        )

    def _on_open_folder_clicked(self) -> None:
        """Safely open the meeting directory in the default Windows file manager."""
        if self._meeting_id is None:
            return

        folder = self._repository.get_meeting_dir(self._meeting_id)
        if folder is None or not folder.is_dir():
            logger.warning("Directory for meeting %s not found", self._meeting_id)
            return

        try:
            # Native Windows Explorer launch
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            # Safe cross-platform Qt fallback
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_refresh_clicked(self) -> None:
        """Refresh current meeting from disk."""
        if self._meeting_id:
            self._repository.refresh()
            self.load_meeting(self._meeting_id)

    @property
    def back_button(self) -> QPushButton:
        """Return back button instance for testing."""
        return self._back_button

    @property
    def copy_button(self) -> QPushButton:
        """Return copy button instance for testing."""
        return self._copy_markdown_button

    @property
    def open_folder_button(self) -> QPushButton:
        """Return open folder button instance for testing."""
        return self._open_folder_button

    @property
    def generate_summary_button(self) -> QPushButton:
        """Return generate summary button instance for testing."""
        return self._generate_summary_button

    @property
    def error_banner(self) -> QFrame:
        """Return error banner frame instance for testing."""
        return self._error_banner

    @property
    def error_label(self) -> QLabel:
        """Return error label instance for testing."""
        return self._error_label

    @property
    def transcript_browser(self) -> QTextBrowser:
        """Return transcript browser instance for testing."""
        return self._transcript_browser
