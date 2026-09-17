"""Authenticated localhost HTTP bridge server for MeetTrace.

Binds exclusively to 127.0.0.1 to receive meeting lifecycle events from the
Chrome extension without exposing any endpoints to the external network.
"""

from __future__ import annotations

import http.server
import json
import logging
import socket
import threading
from collections.abc import Callable
from typing import Any

from meettrace.bridge.models import MeetEventPayload
from meettrace.bridge.token import verify_bridge_token

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 38281
MAX_PAYLOAD_BYTES = 65536  # 64 KB limit to prevent resource exhaustion


class BridgeRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for authenticated MeetTrace bridge endpoints."""

    server: BridgeHTTPServer  # Type hint for custom server attribute

    def log_message(self, format: str, *args: Any) -> None:
        """Override to prevent printing sensitive HTTP headers and suppress stdout noise."""
        logger.debug("Bridge HTTP %s - " + format, self.address_string(), *args)

    def _send_json_response(self, status_code: int, data: dict[str, Any]) -> None:
        """Send a JSON formatted response with appropriate headers."""
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            logger.debug("Connection closed while writing response: %s", exc)

    def _extract_bearer_token(self) -> str | None:
        """Extract Bearer token from the Authorization header."""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header:
            return None
        parts = auth_header.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return None

    def _is_authenticated(self) -> bool:
        """Check if incoming request provides the valid secret token."""
        token = self._extract_bearer_token()
        return verify_bridge_token(token, self.server.expected_token)

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests from browser extension."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        """Handle GET requests (e.g. /api/v1/status)."""
        if self.path in ("/api/v1/status", "/api/v1/status/"):
            if not self._is_authenticated():
                self._send_json_response(
                    401, {"error": "Unauthorized", "message": "Invalid or missing bridge token."}
                )
                return

            status_data = {
                "status": "ok",
                "service": "MeetTrace Bridge",
                "version": "1.0.0",
            }
            if self.server.get_status_callback:
                try:
                    extra = self.server.get_status_callback()
                    if isinstance(extra, dict):
                        status_data.update(extra)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error fetching bridge status details: %s", exc)

            self._send_json_response(200, status_data)
            return

        self._send_json_response(404, {"error": "Not Found"})

    def do_POST(self) -> None:
        """Handle POST requests (e.g. /api/v1/meetings/events)."""
        if self.path in ("/api/v1/meetings/events", "/api/v1/meetings/events/"):
            if not self._is_authenticated():
                self._send_json_response(
                    401, {"error": "Unauthorized", "message": "Invalid or missing bridge token."}
                )
                return

            try:
                content_length_str = self.headers.get("Content-Length", "0")
                content_length = int(content_length_str)
            except ValueError:
                self._send_json_response(400, {"error": "Invalid Content-Length header."})
                return

            if content_length > MAX_PAYLOAD_BYTES:
                self._send_json_response(413, {"error": "Payload too large."})
                return

            try:
                raw_body = self.rfile.read(content_length)
                payload_json = json.loads(raw_body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json_response(
                    400, {"error": "Malformed JSON payload.", "details": str(exc)}
                )
                return

            try:
                event_payload = MeetEventPayload.from_dict(payload_json)
            except ValueError as exc:
                self._send_json_response(
                    400, {"error": "Invalid event schema.", "details": str(exc)}
                )
                return

            # Dispatch to callback safely
            if self.server.on_event_callback:
                try:
                    self.server.on_event_callback(event_payload)
                except Exception:
                    logger.exception("Error in bridge event callback")
                    self._send_json_response(500, {"error": "Internal processing error."})
                    return

            self._send_json_response(200, {"status": "ok", "event": event_payload.event.value})
            return

        self._send_json_response(404, {"error": "Not Found"})


class BridgeHTTPServer(http.server.ThreadingHTTPServer):
    """Specialized ThreadingHTTPServer with custom authentication and event callbacks."""

    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        expected_token: str,
        on_event_callback: Callable[[MeetEventPayload], None] | None = None,
        get_status_callback: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.expected_token = expected_token
        self.on_event_callback = on_event_callback
        self.get_status_callback = get_status_callback
        self.daemon_threads = True
        super().__init__(server_address, BridgeRequestHandler)

    def server_bind(self) -> None:
        """Enforce exclusive address use on Windows to detect port collisions reliably."""
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


class BridgeServer:
    """Manages the lifecycle of the loopback HTTP bridge server."""

    def __init__(
        self,
        token: str,
        host: str = DEFAULT_BRIDGE_HOST,
        port: int = DEFAULT_BRIDGE_PORT,
        on_event: Callable[[MeetEventPayload], None] | None = None,
        get_status: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the bridge server.

        Args:
            token: Shared secret bearer token.
            host: Binding host. Must be 127.0.0.1 for local isolation.
            port: Local port number (default 38281).
            on_event: Callback invoked on validated meeting events.
            get_status: Callback invoked to query app recording state.
        """
        # Security invariant: never allow binding to any interface other than 127.0.0.1
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError(
                f"Security violation: Bridge must only bind to loopback 127.0.0.1, got {host}"
            )

        self._host = "127.0.0.1"
        self._port = port
        self._token = token
        self._on_event = on_event
        self._get_status = get_status

        self._http_server: BridgeHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._is_running = False
        self._last_error: str | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the bridge server is currently accepting connections."""
        return self._is_running

    @property
    def port(self) -> int:
        """Return the bound port number."""
        return self._port

    @property
    def last_error(self) -> str | None:
        """Return the last startup/operational error message, if any."""
        return self._last_error

    def start(self) -> bool:
        """Start the bridge server in a background daemon thread.

        Returns:
            True if started successfully, False if port is occupied or startup failed.
        """
        if self._is_running:
            return True

        self._last_error = None
        try:
            self._http_server = BridgeHTTPServer(
                (self._host, self._port),
                expected_token=self._token,
                on_event_callback=self._on_event,
                get_status_callback=self._get_status,
            )
        except OSError as exc:
            # Handle port collision gracefully without crashing the desktop app
            self._last_error = f"Port {self._port} is unavailable ({exc})"
            logger.warning("Could not start MeetTrace bridge server: %s", self._last_error)
            self._http_server = None
            return False

        self._is_running = True
        self._thread = threading.Thread(
            target=self._run_server,
            name="MeetTraceBridgeServerThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("MeetTrace bridge server running on http://%s:%d", self._host, self._port)
        return True

    def _run_server(self) -> None:
        """Internal server loop run inside daemon thread."""
        if self._http_server is None:
            return
        try:
            self._http_server.serve_forever(poll_interval=0.5)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Bridge server loop terminated: %s", exc)
        finally:
            self._is_running = False

    def stop(self, timeout: float = 2.0) -> None:
        """Cleanly shutdown the HTTP bridge server and join worker thread."""
        if not self._is_running and self._http_server is None:
            return

        logger.info("Stopping MeetTrace bridge server...")
        self._is_running = False

        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error shutting down http server: %s", exc)
            self._http_server = None

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            self._thread = None

        logger.info("MeetTrace bridge server stopped.")
