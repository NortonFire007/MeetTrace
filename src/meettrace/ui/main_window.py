"""Main window with sidebar navigation and content views for MeetTrace.

Provides clean light theme with soft violet accents, Home / Meetings / Settings
sidebar navigation, geometry persistence, and independent lifecycle from tray and toolbar.
"""

from __future__ import annotations

import logging
from typing import Final

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent, QCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from meettrace.storage.repository import MeetingRepository
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    FONT_FAMILY,
    get_main_window_stylesheet,
)
from meettrace.ui.tray import create_tray_icon
from meettrace.ui.views.home_view import HomeView
from meettrace.ui.views.meeting_list_view import MeetingListView
from meettrace.ui.views.meeting_reader_view import MeetingReaderView
from meettrace.ui.views.settings_view import SettingsView

logger = logging.getLogger(__name__)

DEFAULT_WIDTH: Final[int] = 980
DEFAULT_HEIGHT: Final[int] = 680
MIN_WIDTH: Final[int] = 880
MIN_HEIGHT: Final[int] = 560


class MainWindow(QMainWindow):
    """Primary application window hosting sidebar navigation and main content views."""

    def __init__(
        self,
        repository: MeetingRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._settings = QSettings("MeetTrace", "MeetTrace")

        self._init_window()
        self._init_ui()
        self._restore_window_state()

    def _init_window(self) -> None:
        """Configure window properties, title, icon, and styling."""
        self.setWindowTitle("MeetTrace")
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        # Set programmatic app icon
        app_icon = create_tray_icon(is_recording=False)
        self.setWindowIcon(app_icon)

        # Central widget
        self._central_widget = QWidget(self)
        self._central_widget.setObjectName("mainRoot")
        self.setCentralWidget(self._central_widget)

        # Apply global theme stylesheet
        self.setStyleSheet(get_main_window_stylesheet())

    def _init_ui(self) -> None:
        """Construct sidebar and stacked views."""
        root_layout = QHBoxLayout(self._central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------------------------------------------------------------------
        # 1. Sidebar Navigation
        # ---------------------------------------------------------------------
        self._sidebar = QWidget(self._central_widget)
        self._sidebar.setObjectName("sidebarRoot")
        self._sidebar.setFixedWidth(210)

        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 20)
        sidebar_layout.setSpacing(12)

        # App Brand Header
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(2)

        app_name = QLabel("MeetTrace", self._sidebar)
        app_name.setObjectName("appName")
        app_name.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 16px; font-weight: 700; color: {COLOR_TEXT_PRIMARY};"
        )
        brand_layout.addWidget(app_name)

        app_sub = QLabel("Local Meeting Archive", self._sidebar)
        app_sub.setObjectName("appSubtitle")
        app_sub.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 11px; font-weight: 500; color: {COLOR_TEXT_MUTED};"
        )
        brand_layout.addWidget(app_sub)

        sidebar_layout.addLayout(brand_layout)
        sidebar_layout.addSpacing(16)

        # Nav Buttons (Home, Meetings, Settings)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self._home_btn = QPushButton("🏠  Home", self._sidebar)
        self._home_btn.setObjectName("navButton")
        self._home_btn.setCheckable(True)
        self._home_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._nav_group.addButton(self._home_btn, 0)
        sidebar_layout.addWidget(self._home_btn)

        self._meetings_btn = QPushButton("📋  Meetings", self._sidebar)
        self._meetings_btn.setObjectName("navButton")
        self._meetings_btn.setCheckable(True)
        self._meetings_btn.setChecked(True)  # Default active tab
        self._meetings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._nav_group.addButton(self._meetings_btn, 1)
        sidebar_layout.addWidget(self._meetings_btn)

        self._settings_btn = QPushButton("⚙  Settings", self._sidebar)
        self._settings_btn.setObjectName("navButton")
        self._settings_btn.setCheckable(True)
        self._settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._nav_group.addButton(self._settings_btn, 2)
        sidebar_layout.addWidget(self._settings_btn)

        sidebar_layout.addStretch(1)

        # Bottom version badge
        ver_label = QLabel("v0.1.0 • Offline", self._sidebar)
        ver_label.setStyleSheet(
            f"font-family: {FONT_FAMILY}; font-size: 11px; color: {COLOR_TEXT_MUTED};"
        )
        sidebar_layout.addWidget(ver_label)

        root_layout.addWidget(self._sidebar)

        # ---------------------------------------------------------------------
        # 2. Main Content Stack
        # ---------------------------------------------------------------------
        self._content_stack = QStackedWidget(self._central_widget)
        self._content_stack.setStyleSheet(f"background-color: {COLOR_BG_CARD};")

        # Page 0: Home
        self._home_view = HomeView(
            storage_root=self._repository.storage_root,
            parent=self._content_stack,
        )
        self._home_view.go_to_meetings_requested.connect(self.show_meetings_list)
        self._content_stack.addWidget(self._home_view)

        # Page 1: Meetings Stack (List <-> Reader)
        self._meetings_stack = QStackedWidget(self._content_stack)

        self._meeting_list_view = MeetingListView(
            repository=self._repository,
            parent=self._meetings_stack,
        )
        self._meeting_list_view.meeting_selected.connect(self.open_meeting_reader)
        self._meetings_stack.addWidget(self._meeting_list_view)

        self._meeting_reader_view = MeetingReaderView(
            repository=self._repository,
            parent=self._meetings_stack,
        )
        self._meeting_reader_view.back_requested.connect(self.show_meetings_list)
        self._meetings_stack.addWidget(self._meeting_reader_view)

        self._content_stack.addWidget(self._meetings_stack)

        # Page 2: Settings
        self._settings_view = SettingsView(
            storage_root=self._repository.storage_root,
            parent=self._content_stack,
        )
        self._content_stack.addWidget(self._settings_view)

        # Connect nav group
        self._nav_group.idClicked.connect(self._on_nav_clicked)

        root_layout.addWidget(self._content_stack, stretch=1)

        # Show Meetings by default
        self._content_stack.setCurrentIndex(1)
        self._meetings_stack.setCurrentIndex(0)

    def _on_nav_clicked(self, nav_id: int) -> None:
        """Switch main content stack based on navigation button clicked."""
        self._content_stack.setCurrentIndex(nav_id)
        if nav_id == 1:
            # When clicking Meetings in sidebar, return to list view
            self._meetings_stack.setCurrentIndex(0)
            self._meeting_list_view.reload_meetings()

    def show_meetings_list(self) -> None:
        """Switch view to the Meetings list."""
        self._meetings_btn.setChecked(True)
        self._content_stack.setCurrentIndex(1)
        self._meetings_stack.setCurrentIndex(0)
        self._meeting_list_view.reload_meetings()

    def open_meeting_reader(self, meeting_id: str) -> None:
        """Open and display the detail reader for a specific meeting."""
        self._meetings_btn.setChecked(True)
        self._content_stack.setCurrentIndex(1)
        self._meeting_reader_view.load_meeting(meeting_id)
        self._meetings_stack.setCurrentIndex(1)

    def refresh_meetings(self) -> None:
        """Refresh the repository catalog and reload the current view."""
        self._repository.refresh()
        self._meeting_list_view.reload_meetings()
        if self._meetings_stack.currentIndex() == 1 and self._meeting_reader_view._meeting_id:
            self._meeting_reader_view.load_meeting(self._meeting_reader_view._meeting_id)

    # -------------------------------------------------------------------------
    # Window lifecycle and geometry persistence
    # -------------------------------------------------------------------------
    def _restore_window_state(self) -> None:
        """Restore window size and position from persistent settings."""
        geometry = self._settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save geometry and close window without terminating application."""
        self._settings.setValue("window_geometry", self.saveGeometry())
        super().closeEvent(event)

    @property
    def meeting_list_view(self) -> MeetingListView:
        """Return MeetingListView for testing."""
        return self._meeting_list_view

    @property
    def meeting_reader_view(self) -> MeetingReaderView:
        """Return MeetingReaderView for testing."""
        return self._meeting_reader_view

    @property
    def home_view(self) -> HomeView:
        """Return HomeView for testing."""
        return self._home_view

    @property
    def settings_view(self) -> SettingsView:
        """Return SettingsView for testing."""
        return self._settings_view
