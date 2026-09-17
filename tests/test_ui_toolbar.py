"""UI tests for FloatingRecordingToolbar."""

from __future__ import annotations

from PySide6.QtCore import Qt

from meettrace.capture.models import CaptureError, CaptureErrorCategory, CaptureState
from meettrace.ui.controller import RecordingSessionController
from meettrace.ui.toolbar import FloatingRecordingToolbar
from tests.test_ui_controller import DummyAudioCapture


def test_toolbar_window_flags_and_attributes(qtbot) -> None:
    """Verify floating toolbar window flags, transparency, and non-stealing focus attributes."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)

    flags = toolbar.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & Qt.WindowType.Tool)

    assert toolbar.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert toolbar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    # Buttons should have NoFocus policy to avoid stealing keyboard focus from active call/browser
    assert toolbar._start_button.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert toolbar._pause_resume_button.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert toolbar._stop_button.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert toolbar._collapse_button.focusPolicy() == Qt.FocusPolicy.NoFocus

    controller.cleanup()


def test_toolbar_initial_idle_state(qtbot) -> None:
    """Verify initial Idle/Ready state rendering and control visibility."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    assert toolbar._status_label.text() == "Ready"
    assert not toolbar._timer_label.isVisible()
    assert toolbar._start_button.isVisible()
    assert toolbar._start_button.isEnabled()
    assert not toolbar._pause_resume_button.isVisible()
    assert not toolbar._stop_button.isVisible()

    controller.cleanup()


def test_toolbar_recording_state(qtbot) -> None:
    """Verify toolbar updates when entering Recording state."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    controller.start()

    assert toolbar._status_label.text() == "Recording"
    assert toolbar._timer_label.isVisible()
    assert not toolbar._start_button.isVisible()
    assert toolbar._pause_resume_button.isVisible()
    assert toolbar._pause_resume_button.text() == "❚❚"
    assert toolbar._pause_resume_button.isEnabled()
    assert toolbar._stop_button.isVisible()
    assert toolbar._stop_button.isEnabled()

    controller.cleanup()


def test_toolbar_paused_state(qtbot) -> None:
    """Verify toolbar updates when entering Paused state."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    controller.start()
    controller.pause()

    assert toolbar._status_label.text() == "Paused"
    assert toolbar._timer_label.isVisible()
    assert not toolbar._start_button.isVisible()
    assert toolbar._pause_resume_button.isVisible()
    assert toolbar._pause_resume_button.text() == "▶"
    assert toolbar._stop_button.isVisible()

    controller.cleanup()


def test_toolbar_rebinding_substate(qtbot) -> None:
    """Verify rebinding is rendered as a temporary sub-state of recording."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    controller.start()
    capture.emit_state(CaptureState.REBINDING)

    assert toolbar._status_label.text() == "Reconnecting..."
    assert toolbar._timer_label.isVisible()
    assert toolbar._pause_resume_button.isVisible()
    assert toolbar._stop_button.isVisible()

    controller.cleanup()


def test_toolbar_error_state(qtbot) -> None:
    """Verify error state surfaces error indicator and actionable retry button."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    capture.emit_state(CaptureState.ERROR)
    capture.emit_error(
        CaptureError(
            message="Endpoint failed",
            fatal=True,
            category=CaptureErrorCategory.STREAM_ERROR,
        )
    )

    assert toolbar._status_label.text() == "Error"
    assert "Endpoint failed" in toolbar._status_label.toolTip()
    assert toolbar._start_button.isVisible()
    assert toolbar._start_button.text() == "▶ Retry"
    assert not toolbar._pause_resume_button.isVisible()
    assert not toolbar._stop_button.isVisible()

    controller.cleanup()


def test_toolbar_elapsed_time_rendering(qtbot) -> None:
    """Verify elapsed timer label updates when controller emits elapsed_time_changed."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    controller.start()
    controller.elapsed_time_changed.emit(83, "01:23")

    assert toolbar._timer_label.text() == "01:23"

    controller.cleanup()


def test_toolbar_collapse_toggle(qtbot) -> None:
    """Verify toggling collapsed pill mode hides/shows the action controls."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)
    toolbar.show()

    assert not toolbar.is_collapsed
    assert toolbar._controls_widget.isVisible()

    toolbar.toggle_collapse()
    assert toolbar.is_collapsed
    assert not toolbar._controls_widget.isVisible()
    assert toolbar._collapse_button.text() == "▸"

    toolbar.toggle_collapse()
    assert not toolbar.is_collapsed
    assert toolbar._controls_widget.isVisible()
    assert toolbar._collapse_button.text() == "◂"

    controller.cleanup()


def test_toolbar_button_click_actions(qtbot) -> None:
    """Verify clicking toolbar buttons invokes corresponding controller methods."""
    capture = DummyAudioCapture()
    controller = RecordingSessionController(capture)
    toolbar = FloatingRecordingToolbar(controller)
    qtbot.addWidget(toolbar)

    # 1. Click Start
    qtbot.mouseClick(toolbar._start_button, Qt.MouseButton.LeftButton)
    assert controller.state == CaptureState.RECORDING

    # 2. Click Pause
    qtbot.mouseClick(toolbar._pause_resume_button, Qt.MouseButton.LeftButton)
    assert controller.state == CaptureState.PAUSED

    # 3. Click Resume
    qtbot.mouseClick(toolbar._pause_resume_button, Qt.MouseButton.LeftButton)
    assert controller.state == CaptureState.RECORDING

    # 4. Click Stop
    qtbot.mouseClick(toolbar._stop_button, Qt.MouseButton.LeftButton)
    assert controller.state == CaptureState.STOPPED

    controller.cleanup()
