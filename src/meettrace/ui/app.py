"""Desktop application shell and lifecycle coordinator for MeetTrace.

Initializes the PySide6 QApplication, AudioCaptureService, RecordingSessionController,
floating recording toolbar, and persistent system tray manager with graceful lifecycle handling.
"""

from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from meettrace.capture.protocol import AudioCapture
from meettrace.capture.service import AudioCaptureService
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.state import can_stop_recording
from meettrace.ui.toolbar import FloatingRecordingToolbar
from meettrace.ui.tray import SystemTrayManager

logger = logging.getLogger(__name__)


class MeetTraceApp:
    """Main desktop application shell coordinating UI components and audio capture."""

    def __init__(
        self,
        capture_service: AudioCapture | None = None,
        qapp: QApplication | None = None,
    ) -> None:
        # Initialize or reuse QApplication instance
        self._app = qapp or QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("MeetTrace")
        self._app.setApplicationDisplayName("MeetTrace")

        # Crucial for system tray persistence: do not terminate when windows close
        self._app.setQuitOnLastWindowClosed(False)

        # Initialize audio capture subsystem and controller
        self._capture_service = (
            capture_service if capture_service is not None else AudioCaptureService()
        )
        self._controller = RecordingSessionController(self._capture_service)

        # Initialize floating toolbar utility overlay
        self._toolbar = FloatingRecordingToolbar(self._controller)
        self._position_toolbar_default()

        # Initialize system tray integration
        self._tray_manager = SystemTrayManager(
            controller=self._controller,
            on_open=self.show_toolbar,
            on_exit=self.exit,
        )

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

    def exit(self) -> None:
        """Perform clean application shutdown."""
        logger.info("MeetTraceApp shutting down cleanly...")
        if can_stop_recording(self._controller.state):
            try:
                self._controller.stop()
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug("Error stopping capture during shutdown: %s", exc)

        self._controller.cleanup()
        self._tray_manager.cleanup()
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


def main() -> int:
    """Entry point for running MeetTrace desktop application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = MeetTraceApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
