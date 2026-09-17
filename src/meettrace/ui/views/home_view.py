"""Home overview view for MeetTrace desktop application."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BG_SURFACE,
    COLOR_BORDER_DEFAULT,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_SOFT,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_FAMILY,
)


class HomeView(QWidget):
    """Overview dashboard view introducing MeetTrace and quick actions."""

    go_to_meetings_requested = Signal()

    def __init__(
        self,
        storage_root: Path | str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._storage_root = str(storage_root)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. Welcome Title & Subtitle
        title_label = QLabel("Welcome to MeetTrace", self)
        title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 22px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Your private, offline-first meeting companion. Record audio, transcribe locally, "
            "and browse human-readable notes anytime.",
            self,
        )
        desc_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 13px; color: {COLOR_TEXT_SECONDARY}; line-height: 1.5;"
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # 2. Quick Action Card
        card = QFrame(self)
        card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 10px;
                padding: 16px 20px;
            }}
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

        card_title = QLabel("Recorded Meetings", card)
        card_title.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 15px; font-weight: 600; color: {COLOR_TEXT_PRIMARY};"
        )
        card_layout.addWidget(card_title)

        card_desc = QLabel(
            "Browse your past meetings, read timestamped transcripts, copy Markdown notes, "
            "or locate files on your computer.",
            card,
        )
        card_desc.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; color: {COLOR_TEXT_SECONDARY};"
        )
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        action_row = QHBoxLayout()
        view_button = QPushButton("Open Meetings Catalog →", card)
        view_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        view_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_TEXT_WHITE};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                font-weight: 600;
                border: 1px solid {COLOR_PRIMARY};
                border-radius: 6px;
                padding: 7px 16px;
            }}

            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
                border: 1px solid {COLOR_PRIMARY_HOVER};
            }}
            """
        )
        view_button.clicked.connect(self.go_to_meetings_requested.emit)
        action_row.addWidget(view_button)
        action_row.addStretch(1)
        card_layout.addLayout(action_row)

        layout.addWidget(card)

        # 3. Archive Storage info card
        info_card = QFrame(self)
        info_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 8px;
                padding: 12px 16px;
            }}
            """
        )
        info_layout = QVBoxLayout(info_card)
        info_layout.setSpacing(4)

        info_header = QLabel("Archive Directory", info_card)
        info_header.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 11px; font-weight: 700; color: {COLOR_TEXT_SECONDARY}; text-transform: uppercase;"
        )
        info_layout.addWidget(info_header)

        path_label = QLabel(self._storage_root, info_card)
        path_label.setStyleSheet(
            f'font-family: "Consolas", monospace; font-size: 12px; color: {COLOR_PRIMARY}; background-color: {COLOR_PRIMARY_SOFT}; border-radius: 4px; padding: 4px 8px;'
        )
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(path_label)

        layout.addWidget(info_card)
