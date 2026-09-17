"""Unit and UI tests for SystemTrayManager and MeetTraceApp shell."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from meettrace.capture.models import CaptureState
from meettrace.ui.app import MeetTraceApp
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.tray import SystemTrayManager, create_tray_icon
from tests.test_ui_controller import DummyAudioCapture


def test_create_tray_icon() -> None:
    """Verify programmatic tray icon generation for idle and active recording states."""
    icon_idle = create_tray_icon(is_recording=False)
    assert not icon_idle.isNull()

    icon_rec = create_tray_icon(is_recording=True)
    assert not icon_rec.isNull()


def test_tray_menu_actions_and_state_transitions(qtbot) -> None:
    """Verify tray menu actions enabled/disabled state follows recording state."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    tray = SystemTrayManager(controller=controller)

    # Initial IDLE state
    assert tray.start_action.isEnabled()
    assert not tray.stop_action.isEnabled()
    assert tray.open_action.isEnabled()
    assert tray.exit_action.isEnabled()

    # Transition to RECORDING
    controller.start()
    assert not tray.start_action.isEnabled()
    assert tray.stop_action.isEnabled()

    # Transition to PAUSED
    controller.pause()
    assert not tray.start_action.isEnabled()
    assert tray.stop_action.isEnabled()

    # Transition to STOPPED
    controller.stop()
    assert tray.start_action.isEnabled()
    assert not tray.stop_action.isEnabled()

    tray.cleanup()
    controller.cleanup()


def test_tray_action_triggering(qtbot) -> None:
    """Verify triggering tray menu actions invokes controller methods."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    tray = SystemTrayManager(controller=controller)

    # Trigger Start
    tray.start_action.trigger()
    assert controller.state == CaptureState.RECORDING

    # Trigger Stop
    tray.stop_action.trigger()
    assert controller.state == CaptureState.STOPPED

    tray.cleanup()
    controller.cleanup()


def test_tray_open_and_exit_signals(qtbot) -> None:
    """Verify open and exit tray menu items emit expected signals."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)

    open_calls = 0
    exit_calls = 0

    def on_open() -> None:
        nonlocal open_calls
        open_calls += 1

    def on_exit() -> None:
        nonlocal exit_calls
        exit_calls += 1

    tray = SystemTrayManager(
        controller=controller,
        on_open=on_open,
        on_exit=on_exit,
    )

    tray.open_action.trigger()
    assert open_calls == 1

    tray.exit_action.trigger()
    assert exit_calls == 1

    tray.cleanup()
    controller.cleanup()


def test_meettrace_app_initialization_and_lifecycle(qtbot) -> None:
    """Verify application shell setup, quitOnLastWindowClosed, and clean exit."""
    qapp = QApplication.instance() or QApplication([])
    capture = DummyAudioCapture()

    app = MeetTraceApp(capture_service=capture, qapp=qapp)

    # Background tray persistence requirement
    assert app.qapp.quitOnLastWindowClosed() is False

    assert app.controller is not None
    assert app.toolbar is not None
    assert app.tray_manager is not None

    # Toolbar visibility
    app.show_toolbar()
    assert app.toolbar.isVisible()

    app.hide_toolbar()
    assert not app.toolbar.isVisible()

    # Start capture and then test clean exit
    app.controller.start()
    assert app.controller.state == CaptureState.RECORDING

    app.exit()
    assert app.controller.state == CaptureState.STOPPED
