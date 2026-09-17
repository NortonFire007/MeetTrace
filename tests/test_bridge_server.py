"""Automated tests for the authenticated localhost HTTP bridge server."""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request

import pytest

from meettrace.bridge.models import MeetEventType
from meettrace.bridge.server import BridgeServer
from meettrace.bridge.token import get_or_create_bridge_token, verify_bridge_token


def find_free_port() -> int:
    """Find a free port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def test_token() -> str:
    return "test-secret-token-1234567890-abcdef"


@pytest.fixture
def bridge_server(test_token: str):
    port = find_free_port()
    events_received = []

    server = BridgeServer(
        token=test_token,
        host="127.0.0.1",
        port=port,
        on_event=events_received.append,
        get_status=lambda: {"mock_status": "ok", "active": True},
    )
    assert server.start() is True
    yield server, events_received, port, test_token
    server.stop()


def test_token_generation_and_verification(tmp_path):
    token_file = tmp_path / "test_token.txt"
    token = get_or_create_bridge_token(token_file)
    assert len(token) >= 32
    assert token_file.is_file()

    # Second call reuses persisted token
    token2 = get_or_create_bridge_token(token_file)
    assert token == token2

    # Verification
    assert verify_bridge_token(token, token) is True
    assert verify_bridge_token(f"Bearer {token}", token) is True
    assert verify_bridge_token("wrong-token", token) is False
    assert verify_bridge_token("", token) is False
    assert verify_bridge_token(None, token) is False


def test_bridge_server_rejects_non_loopback():
    with pytest.raises(ValueError, match="Security violation: Bridge must only bind to loopback"):
        BridgeServer(token="secret", host="0.0.0.0")


def test_bridge_server_status_authenticated(bridge_server):
    _, _, port, token = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/status"

    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        assert data["service"] == "MeetTrace Bridge"
        assert data["mock_status"] == "ok"
        assert data["active"] is True


def test_bridge_server_status_unauthorized(bridge_server):
    _, _, port, _ = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/status"

    # Missing token
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(url, timeout=2.0)
    assert exc_info.value.code == 401

    # Invalid token
    req = urllib.request.Request(url, headers={"Authorization": "Bearer wrong-token"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2.0)
    assert exc_info.value.code == 401


def test_bridge_server_post_event_authenticated(bridge_server):
    _, events_received, port, token = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/meetings/events"

    payload = {
        "event": "MEETING_STARTED",
        "meeting": {
            "url": "https://meet.google.com/abc-defg-hij",
            "title": "Sprint Planning",
            "meeting_code": "abc-defg-hij",
            "detected_at": "2026-09-17T12:00:00Z",
            "browser": "chrome",
        },
    }
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=2.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        assert data["event"] == "MEETING_STARTED"

    assert len(events_received) == 1
    received = events_received[0]
    assert received.event == MeetEventType.MEETING_STARTED
    assert received.meeting.title == "Sprint Planning"
    assert received.meeting.meeting_code == "abc-defg-hij"
    assert received.meeting.url == "https://meet.google.com/abc-defg-hij"


def test_bridge_server_post_event_unauthorized(bridge_server):
    _, events_received, port, _ = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/meetings/events"

    payload = {"event": "MEETING_STARTED", "meeting": {}}
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": "Bearer invalid-secret", "Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2.0)
    assert exc_info.value.code == 401
    assert len(events_received) == 0


def test_bridge_server_post_malformed_json(bridge_server):
    _, _, port, token = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/meetings/events"

    req = urllib.request.Request(
        url,
        data=b"not-json",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2.0)
    assert exc_info.value.code == 400


def test_bridge_server_post_unsupported_event(bridge_server):
    _, _, port, token = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/meetings/events"

    payload = {"event": "UNKNOWN_SIGNAL", "meeting": {}}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2.0)
    assert exc_info.value.code == 400


def test_bridge_server_post_payload_too_large(bridge_server):
    _, _, port, token = bridge_server
    url = f"http://127.0.0.1:{port}/api/v1/meetings/events"

    huge_payload = {"event": "MEETING_STARTED", "meeting": {"title": "A" * 70000}}
    req = urllib.request.Request(
        url,
        data=json.dumps(huge_payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=2.0)
    assert exc_info.value.code == 413


def test_bridge_server_cors_options(bridge_server):
    _, _, port, _ = bridge_server
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
    conn.request("OPTIONS", "/api/v1/meetings/events")
    resp = conn.getresponse()
    assert resp.status == 204
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert "POST" in resp.getheader("Access-Control-Allow-Methods")
    conn.close()


def test_bridge_server_port_collision_resilience():
    port = find_free_port()

    # First server occupies the port
    server1 = BridgeServer(token="secret1", port=port)
    assert server1.start() is True

    # Second server attempts to bind same port
    server2 = BridgeServer(token="secret2", port=port)
    success = server2.start()
    assert success is False
    assert server2.is_running is False
    assert server2.last_error is not None
    assert "unavailable" in server2.last_error.lower()

    # Clean up
    server1.stop()
    assert server1.is_running is False
