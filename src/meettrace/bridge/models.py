"""Data models, enums, and sanitizers for Google Meet bridge events."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

ROOM_CODE_REGEX = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$", re.IGNORECASE)
CONTROL_CHARS_REGEX = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class MeetEventType(str, Enum):
    """Google Meet lifecycle event types emitted by the extension."""

    MEETING_DETECTED = "MEETING_DETECTED"
    MEETING_STARTED = "MEETING_STARTED"
    MEETING_ENDED = "MEETING_ENDED"
    HEARTBEAT = "HEARTBEAT"


def sanitize_title(raw_title: str | None, max_length: int = 200) -> str:
    """Sanitize arbitrary user or DOM meeting title to prevent control characters and overflow.

    Args:
        raw_title: Raw title string from browser DOM.
        max_length: Maximum allowed character length.

    Returns:
        Sanitized, single-line clean title string.
    """
    if not raw_title or not isinstance(raw_title, str):
        return "Google Meet"

    # Remove null bytes and control characters
    clean = CONTROL_CHARS_REGEX.sub("", raw_title)
    # Collapse multiple whitespace
    clean = " ".join(clean.split()).strip()

    if not clean:
        return "Google Meet"

    return clean[:max_length]


def sanitize_url(raw_url: str | None, max_length: int = 500) -> str:
    """Validate and sanitize Google Meet URL.

    Args:
        raw_url: Raw URL string.
        max_length: Maximum length limit.

    Returns:
        Cleaned URL string, or empty string if invalid.
    """
    if not raw_url or not isinstance(raw_url, str):
        return ""

    clean = raw_url.strip()[:max_length]
    # Ensure it belongs to Google Meet domain or localhost mock
    if clean.startswith(("https://meet.google.com/", "http://127.0.0.1")):
        return clean

    return ""


def sanitize_meeting_code(raw_code: str | None) -> str:
    """Sanitize room code (e.g. 'abc-defg-hij')."""
    if not raw_code or not isinstance(raw_code, str):
        return ""

    clean = raw_code.strip().lower()[:50]
    # Allow standard format or alphanumeric with dashes
    if re.match(r"^[a-z0-9-]+$", clean):
        return clean
    return ""


@dataclass(frozen=True, slots=True)
class MeetMetadata:
    """Meeting metadata extracted by the Chrome extension."""

    url: str
    title: str = "Google Meet"
    meeting_code: str = ""
    detected_at: str = ""
    browser: str = "chrome"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetMetadata:
        """Parse and sanitize untrusted dictionary from extension payload."""
        url = sanitize_url(data.get("url"))
        title = sanitize_title(data.get("title"))

        code = sanitize_meeting_code(data.get("meeting_code"))
        if not code and url:
            # Attempt to extract room code from URL pathname
            match = re.search(r"/([a-z]{3}-[a-z]{4}-[a-z]{3})", url, re.IGNORECASE)
            if match:
                code = match.group(1).lower()

        detected_at = str(data.get("detected_at", ""))
        if not detected_at:
            detected_at = datetime.now(UTC).isoformat()

        browser = str(data.get("browser", "chrome")).strip()[:30]

        return cls(
            url=url,
            title=title,
            meeting_code=code,
            detected_at=detected_at,
            browser=browser,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MeetEventPayload:
    """Validated event received from Chrome extension over loopback HTTP."""

    event: MeetEventType
    meeting: MeetMetadata

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetEventPayload:
        """Parse and validate untrusted JSON dictionary.

        Raises:
            ValueError: If event type is missing or unsupported, or payload is malformed.
        """
        if not isinstance(data, dict):
            raise TypeError("Payload must be a JSON object.")

        raw_event = data.get("event")
        if not raw_event or not isinstance(raw_event, str):
            raise ValueError("Missing or invalid 'event' field.")

        try:
            event_type = MeetEventType(raw_event)
        except ValueError as exc:
            raise ValueError(f"Unsupported event type: '{raw_event}'") from exc

        meeting_data = data.get("meeting", {})
        if not isinstance(meeting_data, dict):
            raise TypeError("'meeting' field must be an object.")

        meeting = MeetMetadata.from_dict(meeting_data)
        return cls(event=event_type, meeting=meeting)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.value,
            "meeting": self.meeting.to_dict(),
        }
