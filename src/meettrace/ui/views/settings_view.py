"""Settings placeholder view for MeetTrace desktop application."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BORDER_DEFAULT,
    COLOR_PRIMARY_SOFT,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_FAMILY,
)


class SettingsView(QWidget):
    """Clean placeholder for application settings."""

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
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_label = QLabel("Settings", self)
        title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 22px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        layout.addWidget(title_label)

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
        card_layout.setSpacing(8)

        card_title = QLabel("General Preferences", card)
        card_title.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 14px; font-weight: 600; color: {COLOR_TEXT_PRIMARY};"
        )
        card_layout.addWidget(card_title)

        card_desc = QLabel(
            "Settings such as language overrides, Whisper model selection, and Gemini API keys "
            "will be configurable here in upcoming phases.",
            card,
        )
        card_desc.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12.5px; color: {COLOR_TEXT_SECONDARY};"
        )
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        path_hint = QLabel(f"Current archive root: {self._storage_root}", card)
        path_hint.setStyleSheet(
            f'font-family: "Consolas", monospace; font-size: 11.5px; color: {COLOR_TEXT_SECONDARY}; background-color: {COLOR_PRIMARY_SOFT}; border-radius: 4px; padding: 4px 8px;'
        )
        card_layout.addWidget(path_hint)

        layout.addWidget(card)
