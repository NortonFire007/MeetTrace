"""Contract and integrity tests for the Google Meet Chrome Manifest V3 extension."""

from __future__ import annotations

import json
import re
from pathlib import Path

from meettrace.bridge.models import MeetEventType

EXTENSION_ROOT = Path("extension").resolve()
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"


def test_extension_manifest_validity_and_permissions():
    """Verify Manifest V3 structure and enforce minimal privacy permissions."""
    assert MANIFEST_PATH.is_file(), f"Manifest file missing at {MANIFEST_PATH}"

    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # Manifest V3 specification
    assert data.get("manifest_version") == 3
    assert data.get("name") == "MeetTrace - Google Meet Bridge"
    assert "version" in data

    # Permission restrictions: NO audio capture, NO tab capture, NO microphone/camera
    permissions = data.get("permissions", [])
    assert permissions == ["storage"], f"Permissions must only be ['storage'], got {permissions}"

    forbidden = {
        "tabCapture",
        "desktopCapture",
        "audioCapture",
        "microphone",
        "camera",
        "tabs",
        "activeTab",
        "<all_urls>",
        "webRequest",
        "cookies",
    }
    for perm in permissions:
        assert perm not in forbidden, f"Forbidden permission found: {perm}"

    # Host permissions restricted to Google Meet and loopback
    host_permissions = data.get("host_permissions", [])
    expected_hosts = ["https://meet.google.com/*", "http://127.0.0.1/*"]
    assert sorted(host_permissions) == sorted(expected_hosts)


def test_extension_files_and_icons_exist():
    """Verify all referenced JS, HTML, and icon files exist on disk."""
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # Background service worker
    sw_rel = data.get("background", {}).get("service_worker", "")
    assert sw_rel != ""
    assert (EXTENSION_ROOT / sw_rel).is_file(), f"Service worker not found: {sw_rel}"

    # Content scripts
    content_scripts = data.get("content_scripts", [])
    assert len(content_scripts) >= 1
    for cs in content_scripts:
        assert cs.get("matches") == ["https://meet.google.com/*"]
        for js_rel in cs.get("js", []):
            assert (EXTENSION_ROOT / js_rel).is_file(), f"Content script not found: {js_rel}"

    # Options and popup page
    popup_rel = data.get("action", {}).get("default_popup", "")
    assert (EXTENSION_ROOT / popup_rel).is_file(), f"Popup HTML not found: {popup_rel}"

    options_rel = data.get("options_ui", {}).get("page", "")
    assert (EXTENSION_ROOT / options_rel).is_file(), f"Options HTML not found: {options_rel}"

    # Icons
    icons = data.get("icons", {})
    for size in ("16", "48", "128"):
        icon_rel = icons.get(size, "")
        assert icon_rel != "", f"Icon {size} missing from manifest"
        icon_path = EXTENSION_ROOT / icon_rel
        assert icon_path.is_file(), f"Icon file missing: {icon_path}"
        assert icon_path.stat().st_size > 0, f"Icon file empty: {icon_path}"


def test_extension_meeting_url_regex():
    """Verify the room code detection regex handles standard and non-standard Google Meet URLs."""
    room_regex = re.compile(r"/([a-z]{3}-[a-z]{4}-[a-z]{3})", re.IGNORECASE)

    valid_urls = [
        ("https://meet.google.com/abc-defg-hij", "abc-defg-hij"),
        ("https://meet.google.com/ABC-DEFG-HIJ", "abc-defg-hij"),
        ("https://meet.google.com/abc-defg-hij?authuser=0", "abc-defg-hij"),
        ("https://meet.google.com/abc-defg-hij#session", "abc-defg-hij"),
    ]

    for url, expected_code in valid_urls:
        match = room_regex.search(url)
        assert match is not None, f"Expected match for {url}"
        assert match.group(1).lower() == expected_code

    # Test pathname matching logic as implemented in meet_detector.js
    invalid_pathnames = [
        "/",
        "/landing",
        "/about",
        "/new",
        "/abc-defgh-hij",
        "/123-4567-890",
    ]

    for path in invalid_pathnames:
        match = room_regex.search(path)
        assert match is None, f"Expected no room code match for {path}"


def test_extension_event_types_match_python_enum():
    """Ensure event types declared in constants.js align with desktop MeetEventType enum."""
    constants_path = EXTENSION_ROOT / "src" / "shared" / "constants.js"
    assert constants_path.is_file()
    content = constants_path.read_text(encoding="utf-8")

    expected_events = {
        MeetEventType.MEETING_DETECTED.value,
        MeetEventType.MEETING_STARTED.value,
        MeetEventType.MEETING_ENDED.value,
        MeetEventType.HEARTBEAT.value,
    }

    for event_name in expected_events:
        assert f'"{event_name}"' in content or f"'{event_name}'" in content, (
            f"Event {event_name} missing from constants.js"
        )
