"""Desktop UI module for MeetTrace.

Provides PySide6 application shell, system tray integration, floating recording
toolbar, and recording session controller.
"""

from meettrace.ui.app import MeetTraceApp, main
from meettrace.ui.bridge import AudioCaptureQtBridge
from meettrace.ui.controller import RecordingSessionController, format_duration
from meettrace.ui.main_window import MainWindow
from meettrace.ui.state import (
    can_pause_recording,
    can_resume_recording,
    can_start_recording,
    can_stop_recording,
    get_state_label,
    get_state_style,
)
from meettrace.ui.toolbar import FloatingRecordingToolbar
from meettrace.ui.tray import SystemTrayManager, create_tray_icon
from meettrace.ui.views import (
    HomeView,
    MeetingCardWidget,
    MeetingListView,
    MeetingReaderView,
    SettingsView,
)

__all__ = [
    "AudioCaptureQtBridge",
    "FloatingRecordingToolbar",
    "HomeView",
    "MainWindow",
    "MeetTraceApp",
    "MeetingCardWidget",
    "MeetingListView",
    "MeetingReaderView",
    "RecordingSessionController",
    "SettingsView",
    "SystemTrayManager",
    "can_pause_recording",
    "can_resume_recording",
    "can_start_recording",
    "can_stop_recording",
    "create_tray_icon",
    "format_duration",
    "get_state_label",
    "get_state_style",
    "main",
]
