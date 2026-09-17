"""Floating recording toolbar for MeetTrace.

A compact, always-on-top, draggable utility overlay designed to stay visible
over Google Meet or desktop browser windows without obstructing content or stealing focus.
"""

from __future__ import annotations

import logging
from typing import Final

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from meettrace.capture.models import CaptureError, CaptureState
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.state import get_state_label, get_state_style
from meettrace.ui.theme import (
    SHADOW_BLUR_RADIUS,
    SHADOW_COLOR_ALPHA,
    SHADOW_Y_OFFSET,
    get_toolbar_stylesheet,
)

logger = logging.getLogger(__name__)

CONTAINER_MARGIN: Final[int] = 8


class FloatingRecordingToolbar(QWidget):
    """Compact, draggable, always-on-top recording toolbar overlay."""

    open_history_requested = Signal()

    def __init__(
        self,
        controller: RecordingSessionController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._is_collapsed: bool = False
        self._drag_start_pos: QPoint | None = None

        self._init_window_attributes()
        self._init_ui()
        self._apply_theme()
        self._connect_signals()
        self._update_state_ui(self._controller.state)
        self._update_meet_ui()

    def _init_window_attributes(self) -> None:
        """Configure Qt window flags and attributes for a non-activating floating utility tool."""
        # Frameless, always-on-top, utility tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("MeetTrace Recording Toolbar")

    def _init_ui(self) -> None:
        """Create and layout the toolbar widgets."""
        # Outer root layout providing space for the drop shadow
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(
            CONTAINER_MARGIN, CONTAINER_MARGIN, CONTAINER_MARGIN, CONTAINER_MARGIN
        )

        # Central rounded card container
        self._container = QWidget(self)
        self._container.setObjectName("toolbarRoot")

        # Subtle shadow effect
        shadow = QGraphicsDropShadowEffect(self._container)
        shadow.setBlurRadius(SHADOW_BLUR_RADIUS)
        shadow.setColor(QColor(0, 0, 0, SHADOW_COLOR_ALPHA))
        shadow.setOffset(0, SHADOW_Y_OFFSET)
        self._container.setGraphicsEffect(shadow)

        # Container content layout (horizontal)
        self._content_layout = QHBoxLayout(self._container)
        self._content_layout.setContentsMargins(12, 6, 10, 6)
        self._content_layout.setSpacing(8)

        # 1. State indicator dot
        self._indicator_dot = QLabel(self._container)
        self._indicator_dot.setObjectName("stateIndicatorDot")
        self._indicator_dot.setFixedSize(8, 8)
        self._content_layout.addWidget(self._indicator_dot)

        # 2. State text label (e.g. "Ready", "Recording", "Paused")
        self._status_label = QLabel("Ready", self._container)
        self._status_label.setObjectName("statusText")
        self._content_layout.addWidget(self._status_label)

        # 3. Elapsed timer label (e.g. "24:17")
        self._timer_label = QLabel("00:00", self._container)
        self._timer_label.setObjectName("timerLabel")
        self._timer_label.setVisible(False)
        self._content_layout.addWidget(self._timer_label)

        # 4. Google Meet integration chip
        self._meet_chip = QLabel("Meet: Standby", self._container)
        self._meet_chip.setObjectName("meetChip")
        self._meet_chip.setToolTip(
            "Google Meet integration: Not detected (Manual recording fully functional)"
        )
        self._content_layout.addWidget(self._meet_chip)

        # 5. Action buttons container
        self._controls_widget = QWidget(self._container)
        self._controls_layout = QHBoxLayout(self._controls_widget)
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_layout.setSpacing(6)

        # Start button
        self._start_button = QPushButton("▶ Start", self._controls_widget)
        self._start_button.setObjectName("primaryButton")
        self._start_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._start_button.setToolTip("Start recording session")
        self._start_button.clicked.connect(self._on_start_clicked)
        self._controls_layout.addWidget(self._start_button)

        # Pause / Resume button
        self._pause_resume_button = QPushButton("❚❚", self._controls_widget)
        self._pause_resume_button.setObjectName("secondaryButton")
        self._pause_resume_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pause_resume_button.setToolTip("Pause recording")
        self._pause_resume_button.clicked.connect(self._on_pause_resume_clicked)
        self._controls_layout.addWidget(self._pause_resume_button)

        # Stop button
        self._stop_button = QPushButton("■", self._controls_widget)
        self._stop_button.setObjectName("stopButton")
        self._stop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stop_button.setToolTip("Stop recording session")
        self._stop_button.clicked.connect(self._on_stop_clicked)
        self._controls_layout.addWidget(self._stop_button)

        self._content_layout.addWidget(self._controls_widget)

        # 5. Open MeetTrace history/main window button
        self._open_history_button = QToolButton(self._container)
        self._open_history_button.setObjectName("ghostButton")
        self._open_history_button.setText("📋")
        self._open_history_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._open_history_button.setToolTip("Open MeetTrace window")
        self._open_history_button.clicked.connect(self.open_history_requested.emit)
        self._content_layout.addWidget(self._open_history_button)

        # 6. Compact / Collapse toggle button
        self._collapse_button = QToolButton(self._container)
        self._collapse_button.setObjectName("ghostButton")
        self._collapse_button.setText("◂")
        self._collapse_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._collapse_button.setToolTip("Collapse toolbar")
        self._collapse_button.clicked.connect(self.toggle_collapse)
        self._content_layout.addWidget(self._collapse_button)

        outer_layout.addWidget(self._container)

    def _apply_theme(self) -> None:
        """Apply centralized design tokens and styles."""
        self.setStyleSheet(get_toolbar_stylesheet())

    def _connect_signals(self) -> None:
        """Wire signals between controller and toolbar widgets."""
        self._controller.state_changed.connect(self._update_state_ui)
        self._controller.elapsed_time_changed.connect(self._update_elapsed_time)
        self._controller.error_occurred.connect(self._on_error_occurred)
        self._controller.meet_context_changed.connect(self._on_meet_context_changed)
        self._controller.bridge_status_changed.connect(self._on_bridge_status_changed)

    # -------------------------------------------------------------------------
    # Dragging implementation without stealing keyboard focus
    # -------------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Capture drag start position when clicking anywhere on toolbar background."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move toolbar window while dragging."""
        if self._drag_start_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Reset drag position on mouse release."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # -------------------------------------------------------------------------
    # State and UI updates
    # -------------------------------------------------------------------------
    def _update_state_ui(self, state: CaptureState) -> None:
        """Update indicator, text, timer visibility, and button visibility based on CaptureState."""
        label_text = get_state_label(state)
        style = get_state_style(state)

        # Update status text
        self._status_label.setText(label_text)

        # Update indicator dot color
        self._indicator_dot.setStyleSheet(f"background-color: {style.color}; border-radius: 4px;")

        # Clear error tooltips if transitioning away from Error
        if state != CaptureState.ERROR:
            self._status_label.setToolTip("")

        # Handle UI layout per state
        if state == CaptureState.IDLE:
            self._timer_label.setVisible(False)
            self._start_button.setVisible(True)
            self._start_button.setText("▶ Start")
            self._start_button.setEnabled(True)
            self._pause_resume_button.setVisible(False)
            self._stop_button.setVisible(False)

        elif state == CaptureState.STARTING:
            self._timer_label.setVisible(False)
            self._start_button.setVisible(True)
            self._start_button.setText("Starting...")
            self._start_button.setEnabled(False)
            self._pause_resume_button.setVisible(False)
            self._stop_button.setVisible(False)

        elif state == CaptureState.RECORDING:
            self._timer_label.setVisible(True)
            self._start_button.setVisible(False)
            self._pause_resume_button.setVisible(True)
            self._pause_resume_button.setText("❚❚")
            self._pause_resume_button.setToolTip("Pause recording")
            self._pause_resume_button.setObjectName("secondaryButton")
            self._pause_resume_button.style().unpolish(self._pause_resume_button)
            self._pause_resume_button.style().polish(self._pause_resume_button)
            self._pause_resume_button.setEnabled(True)
            self._stop_button.setVisible(True)
            self._stop_button.setEnabled(True)

        elif state == CaptureState.REBINDING:
            # Sub-state of recording: preserve timer, controls remain active
            self._timer_label.setVisible(True)
            self._start_button.setVisible(False)
            self._pause_resume_button.setVisible(True)
            self._stop_button.setVisible(True)

        elif state == CaptureState.PAUSED:
            self._timer_label.setVisible(True)
            self._start_button.setVisible(False)
            self._pause_resume_button.setVisible(True)
            self._pause_resume_button.setText("▶")
            self._pause_resume_button.setToolTip("Resume recording")
            self._pause_resume_button.setObjectName("primaryButton")
            self._pause_resume_button.style().unpolish(self._pause_resume_button)
            self._pause_resume_button.style().polish(self._pause_resume_button)
            self._pause_resume_button.setEnabled(True)
            self._stop_button.setVisible(True)
            self._stop_button.setEnabled(True)

        elif state == CaptureState.STOPPED:
            self._timer_label.setVisible(False)
            self._start_button.setVisible(True)
            self._start_button.setText("▶ Start")
            self._start_button.setEnabled(True)
            self._pause_resume_button.setVisible(False)
            self._stop_button.setVisible(False)

        elif state == CaptureState.ERROR:
            self._timer_label.setVisible(False)
            self._start_button.setVisible(True)
            self._start_button.setText("▶ Retry")
            self._start_button.setEnabled(True)
            self._pause_resume_button.setVisible(False)
            self._stop_button.setVisible(False)

        self._container.adjustSize()
        self.adjustSize()

    def _update_elapsed_time(self, seconds: int, formatted_time: str) -> None:
        """Update elapsed timer display."""
        self._timer_label.setText(formatted_time)

    def _on_error_occurred(self, error: CaptureError) -> None:
        """Surface error message calmly without disrupting layout."""
        logger.warning("Toolbar received error: %s", error.message)
        self._status_label.setToolTip(f"Error: {error.message}")

    # -------------------------------------------------------------------------
    # User actions
    # -------------------------------------------------------------------------
    def _on_start_clicked(self) -> None:
        """Handle user click on Start button."""
        self._controller.start()

    def _on_pause_resume_clicked(self) -> None:
        """Handle user click on Pause/Resume button."""
        self._controller.toggle_pause()

    def _on_stop_clicked(self) -> None:
        """Handle user click on Stop button."""
        self._controller.stop()

    def _on_meet_context_changed(self, _metadata: object) -> None:
        """Update Google Meet chip when meet context changes."""
        self._update_meet_ui()

    def _on_bridge_status_changed(self, _is_connected: bool, _message: str) -> None:
        """Update Google Meet chip when bridge status changes."""
        self._update_meet_ui()

    def _update_meet_ui(self) -> None:
        """Update Google Meet chip text, styling, and tooltip."""
        ctx = self._controller.current_meet_context or self._controller.pending_meet_context
        if ctx is not None:
            code_str = f" ({ctx.meeting_code})" if ctx.meeting_code else ""
            self._meet_chip.setText(f"Meet{code_str}")
            self._meet_chip.setToolTip(
                f"Google Meet integration: Connected\nTitle: {ctx.title}\nURL: {ctx.url}"
            )
            self._meet_chip.setStyleSheet(
                "background-color: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0;"
            )
        elif self._controller.bridge_connected:
            self._meet_chip.setText("Meet: Ready")
            self._meet_chip.setToolTip(
                f"Google Meet integration: Connected ({self._controller.bridge_status_message})\nWaiting for Google Meet tab."
            )
            self._meet_chip.setStyleSheet("")
        else:
            self._meet_chip.setText("Meet: Standby")
            self._meet_chip.setToolTip(
                "Google Meet integration: Not detected (Manual recording fully functional)"
            )
            self._meet_chip.setStyleSheet("")
        self._container.adjustSize()
        self.adjustSize()

    def toggle_collapse(self) -> None:
        """Toggle between full controls and compact pill mode."""
        self._is_collapsed = not self._is_collapsed
        if self._is_collapsed:
            self._controls_widget.setVisible(False)
            self._open_history_button.setVisible(False)
            self._meet_chip.setVisible(False)
            self._collapse_button.setText("▸")
            self._collapse_button.setToolTip("Expand toolbar")
        else:
            self._controls_widget.setVisible(True)
            self._open_history_button.setVisible(True)
            self._meet_chip.setVisible(True)
            self._collapse_button.setText("◂")
            self._collapse_button.setToolTip("Collapse toolbar")

        self._container.adjustSize()
        self.adjustSize()

    @property
    def meet_chip(self) -> QLabel:
        """Return the Google Meet status chip widget."""
        return self._meet_chip

    @property
    def open_history_button(self) -> QToolButton:
        """Return open history button instance for testing."""
        return self._open_history_button

    @property
    def is_collapsed(self) -> bool:
        """Whether the toolbar is currently in compact/collapsed mode."""
        return self._is_collapsed
