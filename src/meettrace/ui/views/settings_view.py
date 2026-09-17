"""Settings placeholder view for MeetTrace desktop application."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from meettrace.summary.gemini import (
    AVAILABLE_GEMINI_MODELS,
    DEFAULT_GEMINI_MODEL,
    GeminiConfig,
    mask_api_key,
)
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BORDER_DEFAULT,
    COLOR_PRIMARY_SOFT,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_FAMILY,
    get_search_input_stylesheet,
)


class SettingsView(QWidget):
    """Configuration view for MeetTrace preferences and Gemini AI integration."""

    def __init__(
        self,
        storage_root: Path | str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._storage_root = str(storage_root)
        self._settings = QSettings("MeetTrace", "MeetTrace")
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_label = QLabel("Settings", self)
        title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 22px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        layout.addWidget(title_label)

        # ---------------------------------------------------------------------
        # 1. Gemini AI Configuration Card
        # ---------------------------------------------------------------------
        ai_card = QFrame(self)
        ai_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 10px;
                padding: 18px 20px;
            }}
            """
        )
        ai_layout = QVBoxLayout(ai_card)
        ai_layout.setSpacing(12)

        ai_title = QLabel("AI Summarization (Google Gemini)", ai_card)
        ai_title.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 15px; font-weight: 600; color: {COLOR_TEXT_PRIMARY};"
        )
        ai_layout.addWidget(ai_title)

        ai_desc = QLabel(
            "Configure your Gemini API key to enable executive meeting summaries, decisions, "
            "action items, and follow-ups. If left blank, MeetTrace checks the GEMINI_API_KEY "
            "environment variable.",
            ai_card,
        )
        ai_desc.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; color: {COLOR_TEXT_SECONDARY}; line-height: 1.4;"
        )
        ai_desc.setWordWrap(True)
        ai_layout.addWidget(ai_desc)

        # API Key input
        key_label = QLabel("Gemini API Key", ai_card)
        key_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; font-weight: 600; color: {COLOR_TEXT_PRIMARY};"
        )
        ai_layout.addWidget(key_label)

        key_row = QHBoxLayout()
        self._key_input = QLineEdit(ai_card)
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setStyleSheet(get_search_input_stylesheet())
        saved_key = str(self._settings.value("gemini_api_key", ""))
        env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if saved_key:
            self._key_input.setText(saved_key)
        elif env_key:
            self._key_input.setPlaceholderText(f"Configured in .env ({mask_api_key(env_key)})")
        else:
            self._key_input.setPlaceholderText("Enter your Gemini API key (or configure in .env)")
        self._key_input.textChanged.connect(self._on_key_changed)
        key_row.addWidget(self._key_input, stretch=1)

        self._show_key_btn = QPushButton("Show", ai_card)
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 6px;
                color: {COLOR_TEXT_SECONDARY};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                padding: 6px 12px;
            }}
            """
        )
        self._show_key_btn.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self._show_key_btn)

        ai_layout.addLayout(key_row)

        # Model selection
        model_label = QLabel("Gemini Model", ai_card)
        model_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; font-weight: 600; color: {COLOR_TEXT_PRIMARY}; margin-top: 4px;"
        )
        ai_layout.addWidget(model_label)

        self._model_combo = QComboBox(ai_card)
        self._model_combo.addItems(list(AVAILABLE_GEMINI_MODELS))
        saved_model = str(self._settings.value("gemini_model", DEFAULT_GEMINI_MODEL))
        idx = self._model_combo.findText(saved_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._model_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 12px;
                font-family: {FONT_FAMILY};
                font-size: 12px;
                color: {COLOR_TEXT_PRIMARY};
            }}
            """
        )
        ai_layout.addWidget(self._model_combo)

        layout.addWidget(ai_card)

        # ---------------------------------------------------------------------
        # 2. General Preferences Card
        # ---------------------------------------------------------------------
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
            "Local audio capture, Whisper transcription, and meeting archive directory.",
            card,
        )
        card_desc.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 12px; color: {COLOR_TEXT_SECONDARY};"
        )
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        path_hint = QLabel(f"Archive root: {self._storage_root}", card)
        path_hint.setStyleSheet(
            f'font-family: "Consolas", monospace; font-size: 11px; color: {COLOR_TEXT_SECONDARY}; background-color: {COLOR_PRIMARY_SOFT}; border-radius: 4px; padding: 4px 8px;'
        )
        card_layout.addWidget(path_hint)

        layout.addWidget(card)

    def _on_key_changed(self, text: str) -> None:
        """Persist API key to QSettings."""
        self._settings.setValue("gemini_api_key", text.strip())

    def _on_model_changed(self, _index: int) -> None:
        """Persist model selection to QSettings."""
        model = self._model_combo.currentText()
        self._settings.setValue("gemini_model", model)

    def _toggle_key_visibility(self, checked: bool) -> None:
        """Toggle echo mode between Password and Normal."""
        if checked:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_key_btn.setText("Hide")
        else:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_key_btn.setText("Show")

    def get_gemini_config(self) -> GeminiConfig:
        """Return GeminiConfig constructed from user settings."""
        saved_key = str(self._settings.value("gemini_api_key", "")).strip() or None
        saved_model = str(self._settings.value("gemini_model", DEFAULT_GEMINI_MODEL)).strip()
        return GeminiConfig(api_key=saved_key, model=saved_model)

    @property
    def gemini_key_input(self) -> QLineEdit:
        """Return API key input widget for testing."""
        return self._key_input

    @property
    def gemini_model_combo(self) -> QComboBox:
        """Return model combobox for testing."""
        return self._model_combo
