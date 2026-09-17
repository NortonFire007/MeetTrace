/**
 * Shared constants and configuration keys for MeetTrace Chrome extension.
 */

/* eslint-disable no-unused-vars */

const MEET_EVENTS = {
  MEETING_DETECTED: "MEETING_DETECTED",
  MEETING_STARTED: "MEETING_STARTED",
  MEETING_ENDED: "MEETING_ENDED",
  HEARTBEAT: "HEARTBEAT",
};

const DEFAULT_CONFIG = {
  host: "127.0.0.1",
  port: 38281,
  apiBasePath: "/api/v1",
  eventsPath: "/api/v1/meetings/events",
  statusPath: "/api/v1/status",
};

const STORAGE_KEYS = {
  TOKEN: "meettrace_bridge_token",
  PORT: "meettrace_bridge_port",
};

// Export for Node/Jest testing environments while working seamlessly in browser globals
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    MEET_EVENTS,
    DEFAULT_CONFIG,
    STORAGE_KEYS,
  };
}
