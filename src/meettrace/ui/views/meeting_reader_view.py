"""Meeting detail reader view for MeetTrace.

Renders meeting metadata and timestamped transcript with soft violet highlights,
smooth scrolling, full Unicode (RU/EN/UK) fidelity, Copy Markdown, and Open Folder actions.
"""

from __future__ import annotations

import html
import logging
import os
from typing import Final

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
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
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_SURFACE,
    COLOR_BG_SURFACE_HOVER,
    COLOR_BORDER_DEFAULT,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
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
    """Detailed meeting transcript reader with metadata and document actions."""

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

        # Action 3: Copy Markdown button (Primary soft violet styling)
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
            f"font-family: {FONT_FAMILY}; font-size: 12.5px; font-weight: 500; color: {COLOR_TEXT_SECONDARY};"
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
        """Load and render the requested meeting transcript and metadata."""
        self._meeting_id = meeting_id
        meta = self._repository.get_meeting(meeting_id)
        self._current_metadata = meta

        if meta is None:
            self._title_label.setText("Meeting not found")
            self._subtitle_label.setText(f"Unable to locate artifacts for {meeting_id}")
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

        # Render Transcript Segments
        transcript = self._repository.get_transcript(meeting_id)
        html_content = [get_reader_html_stylesheet(), "<div>"]

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
    def transcript_browser(self) -> QTextBrowser:
        """Return transcript browser instance for testing."""
        return self._transcript_browser
