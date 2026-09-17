"""UI foundation and theme system for MeetTrace.

Centralizes color palettes, typography, spacing, corner radii, shadow styling,
and status indicator visual configurations for a calm, modern, professional desktop UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Primary soft violet accent palette (restrained, calm, non-neon)
COLOR_PRIMARY: Final[str] = "#7C5CFC"
COLOR_PRIMARY_HOVER: Final[str] = "#6D4CE8"
COLOR_PRIMARY_ACTIVE: Final[str] = "#5B3AC7"
COLOR_PRIMARY_SOFT: Final[str] = "#F1EEFE"
COLOR_PRIMARY_SOFT_BORDER: Final[str] = "#DDD6FE"

# Light theme neutrals
COLOR_BG_CARD: Final[str] = "#FFFFFF"
COLOR_BG_SURFACE: Final[str] = "#F8FAFC"
COLOR_BG_SURFACE_HOVER: Final[str] = "#F1F5F9"
COLOR_BG_SURFACE_ACTIVE: Final[str] = "#E2E8F0"

COLOR_BORDER_DEFAULT: Final[str] = "#E2E8F0"
COLOR_BORDER_SUBTLE: Final[str] = "#F1F5F9"

COLOR_TEXT_PRIMARY: Final[str] = "#0F172A"
COLOR_TEXT_SECONDARY: Final[str] = "#64748B"
COLOR_TEXT_MUTED: Final[str] = "#94A3B8"
COLOR_TEXT_WHITE: Final[str] = "#FFFFFF"

# State & semantic colors (restrained red for recording / stop affordance)
COLOR_RECORDING_RED: Final[str] = "#EF4444"
COLOR_RECORDING_RED_HOVER: Final[str] = "#DC2626"
COLOR_RECORDING_RED_SOFT: Final[str] = "#FEF2F2"
COLOR_RECORDING_RED_BORDER: Final[str] = "#FECACA"

COLOR_PAUSED_AMBER: Final[str] = "#F59E0B"
COLOR_PAUSED_AMBER_SOFT: Final[str] = "#FFFBEB"
COLOR_PAUSED_AMBER_BORDER: Final[str] = "#FDE68A"

COLOR_REBINDING_VIOLET: Final[str] = "#8B5CF6"

COLOR_IDLE_SLATE: Final[str] = "#94A3B8"

COLOR_ERROR_RED: Final[str] = "#DC2626"
COLOR_ERROR_BG: Final[str] = "#FEF2F2"
COLOR_ERROR_BORDER: Final[str] = "#FCA5A5"

# Typography constants
FONT_FAMILY: Final[str] = 'Segoe UI, -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif'
FONT_SIZE_TITLE: Final[int] = 13
FONT_SIZE_BODY: Final[int] = 12
FONT_SIZE_CAPTION: Final[int] = 11
FONT_SIZE_TIMER: Final[int] = 13

# Spacing & Radii
RADIUS_CONTAINER: Final[int] = 14
RADIUS_BUTTON: Final[int] = 7
RADIUS_BADGE: Final[int] = 6
RADIUS_DOT: Final[int] = 4

SHADOW_BLUR_RADIUS: Final[int] = 16
SHADOW_COLOR_ALPHA: Final[int] = 28  # ~11% black shadow for clean subtlety
SHADOW_Y_OFFSET: Final[int] = 3


@dataclass(frozen=True, slots=True)
class StatusIndicatorStyle:
    """Styling properties for recording state indicators."""

    color: str
    bg_soft: str
    border_color: str
    label_text: str


def get_toolbar_stylesheet() -> str:
    """Generate the root stylesheet for the floating recording toolbar and its controls."""
    return f"""
    QWidget#toolbarRoot {{
        background-color: {COLOR_BG_CARD};
        border: 1px solid {COLOR_BORDER_DEFAULT};
        border-radius: {RADIUS_CONTAINER}px;
    }}

    QLabel#statusText {{
        color: {COLOR_TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
        background: transparent;
    }}

    QLabel#timerLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-family: "Consolas", "Cascadia Code", "Segoe UI", monospace;
        font-size: {FONT_SIZE_TIMER}px;
        font-weight: 600;
        letter-spacing: 0.5px;
        background: transparent;
        padding-left: 2px;
        padding-right: 2px;
    }}

    QLabel#stateIndicatorDot {{
        border-radius: {RADIUS_DOT}px;
        min-width: 8px;
        max-width: 8px;
        min-height: 8px;
        max-height: 8px;
    }}

    /* Base control button styling */
    QToolButton, QPushButton {{
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
        border-radius: {RADIUS_BUTTON}px;
        padding: 5px 10px;
        border: 1px solid transparent;
        outline: none;
    }}

    /* Primary Action Variant (Soft Violet) */
    QToolButton#primaryButton, QPushButton#primaryButton {{
        background-color: {COLOR_PRIMARY};
        color: {COLOR_TEXT_WHITE};
        border: 1px solid {COLOR_PRIMARY};
    }}
    QToolButton#primaryButton:hover, QPushButton#primaryButton:hover {{
        background-color: {COLOR_PRIMARY_HOVER};
        border: 1px solid {COLOR_PRIMARY_HOVER};
    }}
    QToolButton#primaryButton:pressed, QPushButton#primaryButton:pressed {{
        background-color: {COLOR_PRIMARY_ACTIVE};
        border: 1px solid {COLOR_PRIMARY_ACTIVE};
    }}
    QToolButton#primaryButton:disabled, QPushButton#primaryButton:disabled {{
        background-color: {COLOR_BG_SURFACE_HOVER};
        color: {COLOR_TEXT_MUTED};
        border: 1px solid {COLOR_BORDER_DEFAULT};
    }}

    /* Neutral / Secondary Variant */
    QToolButton#secondaryButton, QPushButton#secondaryButton {{
        background-color: {COLOR_BG_SURFACE};
        color: {COLOR_TEXT_PRIMARY};
        border: 1px solid {COLOR_BORDER_DEFAULT};
    }}
    QToolButton#secondaryButton:hover, QPushButton#secondaryButton:hover {{
        background-color: {COLOR_BG_SURFACE_HOVER};
        border: 1px solid {COLOR_BORDER_DEFAULT};
    }}
    QToolButton#secondaryButton:pressed, QPushButton#secondaryButton:pressed {{
        background-color: {COLOR_BG_SURFACE_ACTIVE};
    }}
    QToolButton#secondaryButton:disabled, QPushButton#secondaryButton:disabled {{
        color: {COLOR_TEXT_MUTED};
        background-color: {COLOR_BG_SURFACE};
        border: 1px solid {COLOR_BORDER_SUBTLE};
    }}

    /* Danger / Stop Affordance Variant */
    QToolButton#stopButton, QPushButton#stopButton {{
        background-color: {COLOR_RECORDING_RED_SOFT};
        color: {COLOR_RECORDING_RED};
        border: 1px solid {COLOR_RECORDING_RED_BORDER};
    }}
    QToolButton#stopButton:hover, QPushButton#stopButton:hover {{
        background-color: {COLOR_RECORDING_RED};
        color: {COLOR_TEXT_WHITE};
        border: 1px solid {COLOR_RECORDING_RED};
    }}
    QToolButton#stopButton:pressed, QPushButton#stopButton:pressed {{
        background-color: {COLOR_RECORDING_RED_HOVER};
        color: {COLOR_TEXT_WHITE};
    }}
    QToolButton#stopButton:disabled, QPushButton#stopButton:disabled {{
        background-color: {COLOR_BG_SURFACE};
        color: {COLOR_TEXT_MUTED};
        border: 1px solid {COLOR_BORDER_DEFAULT};
    }}

    /* Ghost / Icon-only Variant (e.g. Collapse/Expand Toggle) */
    QToolButton#ghostButton, QPushButton#ghostButton {{
        background-color: transparent;
        color: {COLOR_TEXT_SECONDARY};
        border: 1px solid transparent;
        padding: 4px 6px;
    }}
    QToolButton#ghostButton:hover, QPushButton#ghostButton:hover {{
        background-color: {COLOR_BG_SURFACE_HOVER};
        color: {COLOR_TEXT_PRIMARY};
        border: 1px solid {COLOR_BORDER_SUBTLE};
    }}
    QToolButton#ghostButton:pressed, QPushButton#ghostButton:pressed {{
        background-color: {COLOR_BG_SURFACE_ACTIVE};
    }}

    /* Drag handle */
    QLabel#dragHandle {{
        color: {COLOR_TEXT_MUTED};
        font-size: 10px;
        background: transparent;
    }}

    QToolTip {{
        background-color: {COLOR_TEXT_PRIMARY};
        color: {COLOR_TEXT_WHITE};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_CAPTION}px;
        border: none;
        border-radius: 4px;
        padding: 4px 8px;
    }}
    """


def get_main_window_stylesheet() -> str:
    """Generate global application stylesheet for the main window and views."""
    return f"""
    QMainWindow, QWidget#mainRoot {{
        background-color: {COLOR_BG_CARD};
        color: {COLOR_TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
    }}

    QWidget#sidebarRoot {{
        background-color: {COLOR_BG_SURFACE};
        border-right: 1px solid {COLOR_BORDER_DEFAULT};
    }}

    QLabel#appName {{
        font-family: {FONT_FAMILY};
        font-size: 15px;
        font-weight: 700;
        color: {COLOR_TEXT_PRIMARY};
    }}

    QLabel#appSubtitle {{
        font-family: {FONT_FAMILY};
        font-size: 11px;
        font-weight: 500;
        color: {COLOR_TEXT_MUTED};
    }}

    QPushButton#navButton {{
        text-align: left;
        padding: 9px 14px;
        border-radius: 7px;
        font-family: {FONT_FAMILY};
        font-size: 13px;
        font-weight: 500;
        color: {COLOR_TEXT_SECONDARY};
        background-color: transparent;
        border: 1px solid transparent;
    }}
    QPushButton#navButton:hover {{
        background-color: {COLOR_BG_SURFACE_HOVER};
        color: {COLOR_TEXT_PRIMARY};
    }}
    QPushButton#navButton:checked, QPushButton#navButton[active="true"] {{
        background-color: {COLOR_PRIMARY_SOFT};
        color: {COLOR_PRIMARY};
        font-weight: 600;
        border: 1px solid {COLOR_PRIMARY_SOFT_BORDER};
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #CBD5E1;
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #94A3B8;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        height: 0px;
    }}
    """


def get_search_input_stylesheet() -> str:
    """Stylesheet for clean search input field."""
    return f"""
    QLineEdit#searchMeetingsInput {{
        background-color: {COLOR_BG_CARD};
        color: {COLOR_TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: 13px;
        border: 1px solid {COLOR_BORDER_DEFAULT};
        border-radius: 8px;
        padding: 7px 12px;
        selection-background-color: {COLOR_PRIMARY_SOFT};
        selection-color: {COLOR_PRIMARY};
    }}
    QLineEdit#searchMeetingsInput:focus {{
        border: 1px solid {COLOR_PRIMARY};
    }}
    """


def get_meeting_card_stylesheet(selected: bool = False) -> str:
    """Stylesheet for meeting row items in the catalog list."""
    border = COLOR_PRIMARY if selected else COLOR_BORDER_DEFAULT
    bg = COLOR_PRIMARY_SOFT if selected else COLOR_BG_CARD
    return f"""
    QFrame#meetingCard {{
        background-color: {bg};
        border: 1px solid {border};
        border-radius: 9px;
        padding: 10px 14px;
    }}
    QFrame#meetingCard:hover {{
        background-color: #FAF9FF;
        border: 1px solid #CBD5E1;
    }}
    """


def get_reader_html_stylesheet() -> str:
    """Return CSS styles embedded into the QTextBrowser for transcript reading."""
    return f"""
    <style>
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 14px;
            line-height: 1.65;
            color: #1E293B;
            background-color: #FFFFFF;
            margin: 16px 20px;
        }}
        .segment {{
            margin-bottom: 12px;
        }}
        .timestamp {{
            font-family: 'Consolas', 'Cascadia Code', monospace;
            font-size: 12px;
            font-weight: 600;
            color: {COLOR_PRIMARY};
            background-color: {COLOR_PRIMARY_SOFT};
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 8px;
        }}
        .spoken-text {{
            color: #0F172A;
            font-weight: 400;
        }}
        .section-header {{
            font-size: 15px;
            font-weight: 700;
            color: #0F172A;
            margin-top: 18px;
            margin-bottom: 10px;
        }}
        .summary-card {{
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .summary-badge {{
            font-size: 11px;
            font-weight: 700;
            color: #7C5CFC;
            background-color: #F1EEFE;
            padding: 3px 8px;
            border-radius: 4px;
            margin-bottom: 12px;
        }}
        .summary-section {{
            margin-top: 10px;
            margin-bottom: 10px;
        }}
        .summary-section-title {{
            font-size: 13px;
            font-weight: 700;
            color: #0F172A;
            margin-bottom: 4px;
        }}
        .summary-text {{
            font-size: 13px;
            color: #334155;
            line-height: 1.5;
        }}
        .summary-list {{
            margin-top: 4px;
            margin-bottom: 6px;
            margin-left: 20px;
            color: #334155;
            font-size: 13px;
        }}
        .summary-list li {{
            margin-bottom: 4px;
        }}
        .section-divider {{
            border-top: 1px solid #E2E8F0;
            margin-top: 20px;
            margin-bottom: 16px;
        }}
        .empty-transcript {{
            color: #94A3B8;
            font-style: italic;
            padding: 24px;
            text-align: center;
        }}
    </style>
    """
