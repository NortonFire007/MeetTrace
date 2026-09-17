"""System tray integration and lifecycle menu for MeetTrace.

Provides a persistent Windows system tray icon with dynamic recording badge,
context menu (Start Recording, Stop Recording, Open MeetTrace, Exit), and
lifecycle management allowing MeetTrace to remain running in the background.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from meettrace.capture.models import CaptureState
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.state import can_start_recording, can_stop_recording
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BORDER_DEFAULT,
    COLOR_PRIMARY,
    COLOR_RECORDING_RED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_WHITE,
)

logger = logging.getLogger(__name__)


def create_tray_icon(is_recording: bool = False) -> QIcon:
    """Generate a clean, programmatic 32x32 tray icon without external image files."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Base rounded tile in soft violet
    painter.setBrush(QBrush(QColor(COLOR_PRIMARY)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 28, 28, 7, 7)

    # Stylized audio waveform lines in clean white
    pen = QPen(QColor(COLOR_TEXT_WHITE))
    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    painter.drawLine(9, 18, 9, 14)
    painter.drawLine(14, 22, 14, 10)
    painter.drawLine(18, 21, 18, 11)
    painter.drawLine(23, 17, 23, 15)

    # Dynamic red recording badge in top right corner if actively recording
    if is_recording:
        painter.setBrush(QBrush(QColor(COLOR_RECORDING_RED)))
        badge_pen = QPen(QColor(COLOR_TEXT_WHITE))
        badge_pen.setWidth(1)
        painter.setPen(badge_pen)
        painter.drawEllipse(21, 2, 9, 9)

    painter.end()
    return QIcon(pixmap)


class SystemTrayManager(QObject):
    """Manages system tray icon, context menu, and background lifecycle actions."""

    open_requested = Signal()
    exit_requested = Signal()

    def __init__(
        self,
        controller: RecordingSessionController,
        on_open: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller

        if on_open is not None:
            self.open_requested.connect(on_open)
        if on_exit is not None:
            self.exit_requested.connect(on_exit)

        self._init_menu()
        self._init_tray_icon()
        self._connect_signals()
        self._update_state(self._controller.state)

    def _init_menu(self) -> None:
        """Construct the system tray context menu."""
        self._menu = QMenu()
        self._menu.setObjectName("trayMenu")
        self._menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_BORDER_DEFAULT};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {COLOR_TEXT_PRIMARY};
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: #F1EEFE;
                color: {COLOR_PRIMARY};
            }}
            QMenu::item:disabled {{
                color: #94A3B8;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {COLOR_BORDER_DEFAULT};
                margin: 4px 6px;
            }}
            """
        )

        self._start_action = QAction("Start Recording", self._menu)
        self._start_action.triggered.connect(self._on_start_triggered)
        self._menu.addAction(self._start_action)

        self._stop_action = QAction("Stop Recording", self._menu)
        self._stop_action.triggered.connect(self._on_stop_triggered)
        self._menu.addAction(self._stop_action)

        self._menu.addSeparator()

        self._open_action = QAction("Open MeetTrace", self._menu)
        self._open_action.triggered.connect(self.open_requested.emit)
        self._menu.addAction(self._open_action)

        self._menu.addSeparator()

        self._exit_action = QAction("Exit", self._menu)
        self._exit_action.triggered.connect(self.exit_requested.emit)
        self._menu.addAction(self._exit_action)

    def _init_tray_icon(self) -> None:
        """Create and display the QSystemTrayIcon."""
        self._tray_icon = QSystemTrayIcon(create_tray_icon(is_recording=False), self)
        self._tray_icon.setContextMenu(self._menu)
        self._tray_icon.setToolTip("MeetTrace - Ready")
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _connect_signals(self) -> None:
        """Connect to controller signals to reflect recording state in tray menu."""
        self._controller.state_changed.connect(self._update_state)

    def _on_start_triggered(self) -> None:
        """Handle Start Recording clicked from tray menu."""
        self._controller.start()

    def _on_stop_triggered(self) -> None:
        """Handle Stop Recording clicked from tray menu."""
        self._controller.stop()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon click or double-click to restore/focus toolbar."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def _update_state(self, state: CaptureState) -> None:
        """Update tray menu action states and tooltip according to CaptureState."""
        is_recording = state in (
            CaptureState.RECORDING,
            CaptureState.REBINDING,
            CaptureState.PAUSED,
        )

        self._start_action.setEnabled(can_start_recording(state))
        self._stop_action.setEnabled(can_stop_recording(state))

        # Dynamic tray icon with red dot if active
        self._tray_icon.setIcon(create_tray_icon(is_recording=is_recording))

        if state in (CaptureState.RECORDING, CaptureState.REBINDING):
            self._tray_icon.setToolTip("MeetTrace - Recording")
        elif state == CaptureState.PAUSED:
            self._tray_icon.setToolTip("MeetTrace - Paused")
        elif state == CaptureState.ERROR:
            self._tray_icon.setToolTip("MeetTrace - Error")
        else:
            self._tray_icon.setToolTip("MeetTrace - Ready")

    @property
    def tray_icon(self) -> QSystemTrayIcon:
        """Return the underlying QSystemTrayIcon instance."""
        return self._tray_icon

    @property
    def start_action(self) -> QAction:
        """Return the Start Recording QAction."""
        return self._start_action

    @property
    def stop_action(self) -> QAction:
        """Return the Stop Recording QAction."""
        return self._stop_action

    @property
    def open_action(self) -> QAction:
        """Return the Open MeetTrace QAction."""
        return self._open_action

    @property
    def exit_action(self) -> QAction:
        """Return the Exit QAction."""
        return self._exit_action

    def cleanup(self) -> None:
        """Clean up tray icon on shutdown."""
        self._tray_icon.hide()
