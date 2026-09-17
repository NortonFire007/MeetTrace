"""Desktop application shell and lifecycle coordinator for MeetTrace.

Initializes the PySide6 QApplication, AudioCaptureService, RecordingSessionController,
floating recording toolbar, and persistent system tray manager with graceful lifecycle handling.
"""

from __future__ import annotations

import logging
import signal
import sys
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from meettrace.bridge.adapter import MeetBridgeQtAdapter
from meettrace.bridge.server import BridgeServer
from meettrace.bridge.token import get_or_create_bridge_token
from meettrace.capture.protocol import AudioCapture
from meettrace.capture.service import AudioCaptureService
from meettrace.config import load_dotenv
from meettrace.logging import setup_logging
from meettrace.storage.repository import MeetingRepository
from meettrace.storage.store import MeetingArtifactStore
from meettrace.transcription.service import TranscriptionService
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.main_window import MainWindow
from meettrace.ui.state import can_stop_recording
from meettrace.ui.toolbar import FloatingRecordingToolbar
from meettrace.ui.tray import SystemTrayManager

logger = logging.getLogger(__name__)


class MeetTraceApp:
    """Main desktop application shell coordinating UI components and audio capture."""

    def __init__(
        self,
        capture_service: AudioCapture | None = None,
        repository: MeetingRepository | None = None,
        bridge_server: BridgeServer | None = None,
        start_bridge: bool = True,
        qapp: QApplication | None = None,
    ) -> None:
        # Load environment variables from .env if present
        load_dotenv()

        # Initialize or reuse QApplication instance
        self._app = qapp or QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("MeetTrace")
        self._app.setApplicationDisplayName("MeetTrace")

        # Crucial for system tray persistence: do not terminate when windows close
        self._app.setQuitOnLastWindowClosed(False)

        # Initialize meeting repository and durable artifact store
        self._repository = repository if repository is not None else MeetingRepository()
        self._artifact_store = MeetingArtifactStore(storage_root=self._repository.storage_root)
        self._main_window = MainWindow(self._repository)

        # Initialize audio capture subsystem
        self._capture_service = (
            capture_service if capture_service is not None else AudioCaptureService()
        )

        # Initialize speech transcription service and connect to audio capture
        self._transcription_service = TranscriptionService()
        self._capture_service.add_observer(self._transcription_service)

        # Initialize controller with capture, transcription, and storage services
        self._controller = RecordingSessionController(
            capture_service=self._capture_service,
            transcription_service=self._transcription_service,
            artifact_store=self._artifact_store,
            repository=self._repository,
        )
        self._controller.meeting_saved.connect(self._on_meeting_saved)

        # Initialize floating toolbar utility overlay
        self._toolbar = FloatingRecordingToolbar(self._controller)
        self._position_toolbar_default()
        self._toolbar.open_history_requested.connect(self.show_main_window)

        # Initialize system tray integration: "Open MeetTrace" opens main window
        self._tray_manager = SystemTrayManager(
            controller=self._controller,
            on_open=self.show_main_window,
            on_exit=self.exit,
        )

        # Initialize Google Meet localhost bridge adapter and HTTP server
        self._bridge_token = get_or_create_bridge_token()
        self._bridge_adapter = MeetBridgeQtAdapter(self._toolbar)
        self._bridge_adapter.meeting_detected.connect(self._controller.on_meeting_detected)
        self._bridge_adapter.meeting_started.connect(self._controller.on_meeting_started)
        self._bridge_adapter.meeting_ended.connect(self._controller.on_meeting_ended)
        self._bridge_adapter.bridge_status_changed.connect(
            self._controller.on_bridge_status_changed
        )

        if bridge_server is not None:
            self._bridge_server = bridge_server
        else:
            self._bridge_server = BridgeServer(
                token=self._bridge_token,
                on_event=self._bridge_adapter.handle_event,
                get_status=self._get_bridge_status,
            )

        if start_bridge:
            bridge_started = self._bridge_server.start()
            status_msg = (
                f"Active on 127.0.0.1:{self._bridge_server.port}"
                if bridge_started
                else (self._bridge_server.last_error or "Bridge server unavailable")
            )
            self._bridge_adapter.set_bridge_status(bridge_started, status_msg)
            self._main_window.settings_view.set_bridge_status(bridge_started, status_msg)

        # Allow terminal Ctrl+C (SIGINT) to be caught gracefully by Python
        self._sigint_timer = QTimer(self._toolbar)
        self._sigint_timer.setInterval(500)
        self._sigint_timer.timeout.connect(lambda: None)
        self._sigint_timer.start()

        self._setup_signal_handling()

    def _setup_signal_handling(self) -> None:
        """Register POSIX/Win32 signal handler for SIGINT."""
        try:
            signal.signal(signal.SIGINT, lambda _sig, _frame: self.exit())
        except (ValueError, AttributeError):
            pass

    def _position_toolbar_default(self) -> None:
        """Position the floating toolbar near the top-center of the primary display."""
        screen = self._app.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            toolbar_width = 320
            x = available.x() + (available.width() - toolbar_width) // 2
            y = available.y() + 24
            self._toolbar.move(x, y)

    def show_toolbar(self) -> None:
        """Show and bring the floating toolbar to the top without stealing keyboard focus."""
        self._toolbar.show()
        self._toolbar.raise_()

    def hide_toolbar(self) -> None:
        """Hide the floating toolbar."""
        self._toolbar.hide()

    def show_main_window(self) -> None:
        """Display the main MeetTrace history/reader window and bring it to focus."""
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def hide_main_window(self) -> None:
        """Hide the main MeetTrace history/reader window."""
        self._main_window.hide()

    def refresh_history(self) -> None:
        """Refresh meetings catalog and views in the main window."""
        self._main_window.refresh_meetings()

    def _on_meeting_saved(self, meeting_id: str) -> None:
        """Handle automatic refresh and notification when a meeting is saved."""
        logger.info("Meeting saved successfully: %s", meeting_id)
        self.refresh_history()
        meta = self._repository.get_meeting(meeting_id)
        title = meta.title if meta else "Meeting"
        self._tray_manager.show_notification(
            "Meeting Saved",
            f"Meeting '{title}' saved to local archive.",
        )

    def _get_bridge_status(self) -> dict[str, Any]:
        """Query desktop app operational state for the extension status check."""
        return {
            "recording_state": self._controller.state.value,
            "elapsed_seconds": self._controller.elapsed_seconds,
            "has_meet_context": self._controller.current_meet_context is not None,
        }

    def exit(self) -> None:
        """Perform clean application shutdown."""
        logger.info("MeetTraceApp shutting down cleanly...")
        if can_stop_recording(self._controller.state):
            try:
                self._controller.stop()
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug("Error stopping capture during shutdown: %s", exc)

        self._bridge_server.stop()
        self._controller.cleanup()
        self._tray_manager.cleanup()
        self._main_window.close()
        self._toolbar.close()
        self._app.quit()

    def run(self) -> int:
        """Display the floating toolbar and start the Qt event loop."""
        self.show_toolbar()
        logger.info("MeetTrace application running.")
        return self._app.exec()

    @property
    def qapp(self) -> QApplication:
        """Return the underlying QApplication instance."""
        return self._app

    @property
    def controller(self) -> RecordingSessionController:
        """Return the recording controller instance."""
        return self._controller

    @property
    def toolbar(self) -> FloatingRecordingToolbar:
        """Return the floating toolbar instance."""
        return self._toolbar

    @property
    def tray_manager(self) -> SystemTrayManager:
        """Return the system tray manager instance."""
        return self._tray_manager

    @property
    def main_window(self) -> MainWindow:
        """Return the main window instance."""
        return self._main_window

    @property
    def repository(self) -> MeetingRepository:
        """Return the meeting repository instance."""
        return self._repository

    @property
    def bridge_server(self) -> BridgeServer:
        """Return the localhost bridge server instance."""
        return self._bridge_server

    @property
    def bridge_adapter(self) -> MeetBridgeQtAdapter:
        """Return the bridge Qt adapter instance."""
        return self._bridge_adapter

    @property
    def artifact_store(self) -> MeetingArtifactStore:
        """Return the meeting artifact store instance."""
        return self._artifact_store

    @property
    def transcription_service(self) -> TranscriptionService:
        """Return the transcription service instance."""
        return self._transcription_service


def main() -> int:
    """Entry point for running MeetTrace desktop application."""
    if "--version" in sys.argv:
        print("MeetTrace v0.1.0")
        return 0

    log_path = setup_logging()
    logger.info("MeetTrace starting (log file: %s)", log_path)

    if "--check-startup" in sys.argv:
        logger.info("MeetTrace startup check OK")
        print("MeetTrace startup check OK")
        return 0

    app = MeetTraceApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
