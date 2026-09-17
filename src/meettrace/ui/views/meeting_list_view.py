"""Meeting catalog list view for MeetTrace.

Displays date-grouped meetings (Today, Yesterday, Older), basic text search,
metadata badges (platform, languages, duration), and calm empty state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from meettrace.storage.models import MeetingMetadata
from meettrace.storage.repository import MeetingRepository, parse_datetime_safe
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_SURFACE,
    COLOR_BORDER_DEFAULT,
    COLOR_PRIMARY,
    COLOR_PRIMARY_SOFT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_FAMILY,
    get_meeting_card_stylesheet,
    get_search_input_stylesheet,
)

logger = logging.getLogger(__name__)

EMPTY_HEADING: Final[str] = "No meetings yet"
EMPTY_SUBTEXT: Final[str] = (
    "Start your first recording and MeetTrace\nwill keep the transcript here."
)


def format_meeting_duration(ms: int) -> str:
    """Format duration in milliseconds to human-readable string (e.g. '42 min' or '1h 12m')."""
    if ms <= 0:
        return "0 min"
    minutes = ms // 60000
    if minutes < 60:
        return f"{max(1, minutes)} min"
    hours = minutes // 60
    rem_min = minutes % 60
    return f"{hours}h {rem_min}m" if rem_min > 0 else f"{hours}h"


def format_meeting_time(dt_str: str) -> str:
    """Format ISO datetime string to local 24h time 'HH:MM'."""
    dt = parse_datetime_safe(dt_str)
    if dt is None:
        return "--:--"
    local_dt = dt.astimezone()
    return f"{local_dt.hour:02d}:{local_dt.minute:02d}"


def get_date_group_key(dt_str: str) -> str:
    """Classify a meeting's started_at datetime into 'Today', 'Yesterday', or 'Older'."""
    dt = parse_datetime_safe(dt_str)
    if dt is None:
        return "Older"

    local_dt = dt.astimezone()
    now_local = datetime.now(UTC).astimezone()

    today_date = now_local.date()
    yesterday_date = today_date - timedelta(days=1)
    meeting_date = local_dt.date()

    if meeting_date == today_date:
        return "Today"
    if meeting_date == yesterday_date:
        return "Yesterday"
    return "Older"


class MeetingCardWidget(QFrame):
    """Clickable meeting summary item row."""

    clicked = Signal(str)

    def __init__(
        self,
        metadata: MeetingMetadata,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._metadata = metadata
        self.setObjectName("meetingCard")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(get_meeting_card_stylesheet(selected=False))
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Top row: [Time] [Title] [Duration]
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # 1. Time (e.g. 10:32)
        time_text = format_meeting_time(self._metadata.started_at)
        time_label = QLabel(time_text, self)
        time_label.setStyleSheet(
            f'font-family: "Consolas", "Segoe UI", monospace; font-size: 12px; font-weight: 600; color: {COLOR_TEXT_SECONDARY};'
        )
        top_row.addWidget(time_label)

        # 2. Title
        title_label = QLabel(self._metadata.title, self)
        title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 14px; font-weight: 600; color: {COLOR_TEXT_PRIMARY};"
        )
        title_label.setWordWrap(False)
        top_row.addWidget(title_label, stretch=1)

        # 3. Duration (e.g. 42 min)
        dur_text = format_meeting_duration(self._metadata.duration_ms)
        dur_label = QLabel(dur_text, self)
        dur_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; font-weight: 500; color: {COLOR_TEXT_SECONDARY};"
        )
        top_row.addWidget(dur_label)

        layout.addLayout(top_row)

        # Bottom row: Platform • Languages • Segments count
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        # Platform chip
        platform = (
            self._metadata.source.get("platform")
            if isinstance(self._metadata.source, dict)
            else None
        )
        platform_text = str(platform) if platform else "Audio Session"
        if platform_text.lower() == "google-meet":
            platform_text = "Google Meet"

        platform_label = QLabel(platform_text, self)
        platform_label.setStyleSheet(
            f"""
            QLabel {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 4px;
                color: {COLOR_TEXT_SECONDARY};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: 500;
                padding: 1px 6px;
            }}
            """
        )
        bottom_row.addWidget(platform_label)

        # Separator bullet
        bullet = QLabel("•", self)
        bullet.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
        bottom_row.addWidget(bullet)

        # Language chip (e.g. RU / EN)
        langs = []
        if self._metadata.detected_languages:
            langs = [l.upper() for l in self._metadata.detected_languages]
        elif self._metadata.dominant_language:
            langs = [self._metadata.dominant_language.upper()]

        lang_text = " / ".join(langs) if langs else "AUTO"
        lang_label = QLabel(lang_text, self)
        lang_label.setStyleSheet(
            f"""
            QLabel {{
                background-color: {COLOR_PRIMARY_SOFT};
                color: {COLOR_PRIMARY};
                border-radius: 4px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: 600;
                padding: 1px 6px;
            }}
            """
        )
        bottom_row.addWidget(lang_label)

        # Segment count indicator
        if self._metadata.segment_count > 0:
            bullet2 = QLabel("•", self)
            bullet2.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
            bottom_row.addWidget(bullet2)

            count_label = QLabel(f"{self._metadata.segment_count} segments", self)
            count_label.setStyleSheet(
                f"font-family: {FONT_FAMILY}; font-size: 11px; color: {COLOR_TEXT_MUTED};"
            )
            bottom_row.addWidget(count_label)

        bottom_row.addStretch(1)
        layout.addLayout(bottom_row)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle click on meeting item to emit selection signal."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._metadata.meeting_id)
            event.accept()
        else:
            super().mousePressEvent(event)


class MeetingListView(QWidget):
    """Main view presenting searchable, date-grouped list of recorded meetings."""

    meeting_selected = Signal(str)

    def __init__(
        self,
        repository: MeetingRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._search_query: str = ""
        self._init_ui()
        self.reload_meetings()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(28, 24, 28, 20)
        root_layout.setSpacing(16)

        # 1. Header: "Meetings" title
        header_layout = QHBoxLayout()
        title_label = QLabel("Meetings", self)
        title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 22px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        root_layout.addLayout(header_layout)

        # 2. Search input field
        self._search_input = QLineEdit(self)
        self._search_input.setObjectName("searchMeetingsInput")
        self._search_input.setPlaceholderText("Search meetings by title, language, or platform...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(get_search_input_stylesheet())
        self._search_input.textChanged.connect(self._on_search_text_changed)
        root_layout.addWidget(self._search_input)

        # 3. Scrollable content container for date-grouped items
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setStyleSheet(f"background-color: {COLOR_BG_CARD};")

        self._list_container = QWidget()
        self._list_container.setStyleSheet(f"background-color: {COLOR_BG_CARD};")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 8, 8, 16)
        self._list_layout.setSpacing(10)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._scroll_area.setWidget(self._list_container)
        root_layout.addWidget(self._scroll_area, stretch=1)

    def _on_search_text_changed(self, text: str) -> None:
        """Filter meeting catalog when search query changes."""
        self._search_query = text.strip()
        self.reload_meetings()

    def reload_meetings(self) -> None:
        """Refresh meetings list from repository and rebuild UI."""
        # Clear existing items
        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        meetings = self._repository.list_meetings(search_query=self._search_query)

        # Empty state handling
        if not meetings:
            self._render_empty_state()
            return

        # Group meetings by date key: Today, Yesterday, Older
        grouped: dict[str, list[MeetingMetadata]] = {
            "Today": [],
            "Yesterday": [],
            "Older": [],
        }

        for m in meetings:
            group_key = get_date_group_key(m.started_at)
            grouped[group_key].append(m)

        # Render sections in order
        for section in ("Today", "Yesterday", "Older"):
            section_items = grouped[section]
            if not section_items:
                continue

            # Section header label
            sec_header = QLabel(section, self._list_container)
            sec_header.setStyleSheet(
                f"""
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 700;
                color: {COLOR_TEXT_SECONDARY};
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-top: 8px;
                margin-bottom: 2px;
                """
            )
            self._list_layout.addWidget(sec_header)

            # Meeting items in this section
            for m in section_items:
                card = MeetingCardWidget(m, self._list_container)
                card.clicked.connect(self.meeting_selected.emit)
                self._list_layout.addWidget(card)

    def _render_empty_state(self) -> None:
        """Render calm empty state when no meetings exist or search matches nothing."""
        empty_container = QWidget(self._list_container)
        layout = QVBoxLayout(empty_container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(20, 60, 20, 40)
        layout.setSpacing(10)

        if self._search_query:
            heading = "No matching meetings"
            subtext = f"No recorded meetings matched '{self._search_query}'."
        else:
            heading = EMPTY_HEADING
            subtext = EMPTY_SUBTEXT

        head_label = QLabel(heading, empty_container)
        head_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 16px; font-weight: 600; color: {COLOR_TEXT_PRIMARY};"
        )
        layout.addWidget(head_label)

        sub_label = QLabel(subtext, empty_container)
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 13px; color: {COLOR_TEXT_SECONDARY}; line-height: 1.4;"
        )
        layout.addWidget(sub_label)

        self._list_layout.addWidget(empty_container)

    @property
    def search_input(self) -> QLineEdit:
        """Return search QLineEdit for testing."""
        return self._search_input
