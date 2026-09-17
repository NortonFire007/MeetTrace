"""Recording state presentation mapping for MeetTrace UI.

Reuses the domain CaptureState model and maps backend states directly to
human-readable presentation labels, indicator colors, and control action permissions
without introducing a duplicate state machine.
"""

from __future__ import annotations

from meettrace.capture.models import CaptureState
from meettrace.ui.theme import (
    COLOR_BG_CARD,
    COLOR_BORDER_DEFAULT,
    COLOR_ERROR_BG,
    COLOR_ERROR_BORDER,
    COLOR_ERROR_RED,
    COLOR_IDLE_SLATE,
    COLOR_PAUSED_AMBER,
    COLOR_PAUSED_AMBER_BORDER,
    COLOR_PAUSED_AMBER_SOFT,
    COLOR_PRIMARY,
    COLOR_PRIMARY_SOFT,
    COLOR_PRIMARY_SOFT_BORDER,
    COLOR_REBINDING_VIOLET,
    COLOR_RECORDING_RED,
    COLOR_RECORDING_RED_BORDER,
    COLOR_RECORDING_RED_SOFT,
    StatusIndicatorStyle,
)

# Canonical presentation mapping from backend CaptureState to UI display text
_STATE_LABELS: dict[CaptureState, str] = {
    CaptureState.IDLE: "Ready",
    CaptureState.STARTING: "Starting...",
    CaptureState.RECORDING: "Recording",
    CaptureState.REBINDING: "Reconnecting...",
    CaptureState.PAUSED: "Paused",
    CaptureState.STOPPED: "Stopped",
    CaptureState.ERROR: "Error",
}

# Indicator dot and badge styling per CaptureState
_STATE_STYLES: dict[CaptureState, StatusIndicatorStyle] = {
    CaptureState.IDLE: StatusIndicatorStyle(
        color=COLOR_IDLE_SLATE,
        bg_soft=COLOR_BG_CARD,
        border_color=COLOR_BORDER_DEFAULT,
        label_text="Ready",
    ),
    CaptureState.STARTING: StatusIndicatorStyle(
        color=COLOR_PRIMARY,
        bg_soft=COLOR_PRIMARY_SOFT,
        border_color=COLOR_PRIMARY_SOFT_BORDER,
        label_text="Starting...",
    ),
    CaptureState.RECORDING: StatusIndicatorStyle(
        color=COLOR_RECORDING_RED,
        bg_soft=COLOR_RECORDING_RED_SOFT,
        border_color=COLOR_RECORDING_RED_BORDER,
        label_text="Recording",
    ),
    CaptureState.REBINDING: StatusIndicatorStyle(
        color=COLOR_REBINDING_VIOLET,
        bg_soft=COLOR_RECORDING_RED_SOFT,
        border_color=COLOR_PRIMARY_SOFT_BORDER,
        label_text="Reconnecting...",
    ),
    CaptureState.PAUSED: StatusIndicatorStyle(
        color=COLOR_PAUSED_AMBER,
        bg_soft=COLOR_PAUSED_AMBER_SOFT,
        border_color=COLOR_PAUSED_AMBER_BORDER,
        label_text="Paused",
    ),
    CaptureState.STOPPED: StatusIndicatorStyle(
        color=COLOR_IDLE_SLATE,
        bg_soft=COLOR_BG_CARD,
        border_color=COLOR_BORDER_DEFAULT,
        label_text="Stopped",
    ),
    CaptureState.ERROR: StatusIndicatorStyle(
        color=COLOR_ERROR_RED,
        bg_soft=COLOR_ERROR_BG,
        border_color=COLOR_ERROR_BORDER,
        label_text="Error",
    ),
}


def get_state_label(state: CaptureState) -> str:
    """Return the user-facing presentation label for a given CaptureState."""
    return _STATE_LABELS.get(state, state.value.capitalize())


def get_state_style(state: CaptureState) -> StatusIndicatorStyle:
    """Return the indicator color and badge styling for a given CaptureState."""
    return _STATE_STYLES.get(
        state,
        StatusIndicatorStyle(
            color=COLOR_IDLE_SLATE,
            bg_soft=COLOR_BG_CARD,
            border_color=COLOR_BORDER_DEFAULT,
            label_text=state.value.capitalize(),
        ),
    )


def can_start_recording(state: CaptureState) -> bool:
    """Determine whether the 'Start Recording' action is permitted in the given state."""
    return state in (CaptureState.IDLE, CaptureState.STOPPED, CaptureState.ERROR)


def can_pause_recording(state: CaptureState) -> bool:
    """Determine whether the 'Pause' action is permitted in the given state."""
    return state in (CaptureState.RECORDING, CaptureState.REBINDING)


def can_resume_recording(state: CaptureState) -> bool:
    """Determine whether the 'Resume' action is permitted in the given state."""
    return state == CaptureState.PAUSED


def can_stop_recording(state: CaptureState) -> bool:
    """Determine whether the 'Stop' action is permitted in the given state."""
    return state in (CaptureState.RECORDING, CaptureState.REBINDING, CaptureState.PAUSED)
