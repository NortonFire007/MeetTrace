/**
 * MeetTrace Chrome Extension Background Service Worker (Manifest V3).
 *
 * Coordinates authenticated communication between content scripts and the local
 * MeetTrace desktop application via loopback HTTP (127.0.0.1:38281).
 */

const DEFAULT_PORT = 38281;
const STORAGE_KEYS = {
  TOKEN: "meettrace_bridge_token",
  PORT: "meettrace_bridge_port",
};

/**
 * Fetch bridge configuration from local storage.
 */
async function getBridgeConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get([STORAGE_KEYS.TOKEN, STORAGE_KEYS.PORT], (result) => {
      resolve({
        token: result[STORAGE_KEYS.TOKEN] || "",
        port: parseInt(result[STORAGE_KEYS.PORT], 10) || DEFAULT_PORT,
      });
    });
  });
}

/**
 * Send an authenticated event to the MeetTrace desktop bridge.
 */
async function sendEventToBridge(eventPayload) {
  const config = await getBridgeConfig();
  if (!config.token) {
    console.debug("[MeetTrace Extension] No bridge token configured. Event dropped.");
    return { success: false, error: "TOKEN_MISSING" };
  }

  const endpoint = `http://127.0.0.1:${config.port}/api/v1/meetings/events`;

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${config.token}`,
      },
      body: JSON.stringify(eventPayload),
    });

    if (!response.ok) {
      console.warn(`[MeetTrace Extension] Bridge returned HTTP ${response.status}`);
      return { success: false, status: response.status };
    }

    const data = await response.json();
    console.debug("[MeetTrace Extension] Event delivered successfully:", eventPayload.event);
    return { success: true, data };
  } catch (err) {
    // Expected when MeetTrace desktop app is not running
    console.debug("[MeetTrace Extension] Bridge unreachable on 127.0.0.1:", err.message);
    return { success: false, error: "NETWORK_ERROR", message: err.message };
  }
}

/**
 * Test connectivity with the desktop bridge server.
 */
async function testConnection() {
  const config = await getBridgeConfig();
  if (!config.token) {
    return { connected: false, error: "Please enter a bridge token first." };
  }

  const endpoint = `http://127.0.0.1:${config.port}/api/v1/status`;

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${config.token}`,
      },
    });

    if (response.status === 401) {
      return { connected: false, error: "Invalid bridge token. Check Settings in MeetTrace." };
    }

    if (!response.ok) {
      return { connected: false, error: `Bridge returned status ${response.status}` };
    }

    const data = await response.json();
    return { connected: true, data };
  } catch (err) {
    return {
      connected: false,
      error: "Could not connect to MeetTrace desktop app. Ensure it is running.",
    };
  }
}

// Listen for messages from content scripts and options page
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "TEST_CONNECTION") {
    testConnection().then(sendResponse);
    return true; // Keep message channel open for async response
  }

  if (message.event) {
    sendEventToBridge(message).then(sendResponse);
    return true;
  }

  return false;
});

// Self-check on installation
chrome.runtime.onInstalled.addListener(() => {
  console.log("[MeetTrace Extension] Installed successfully.");
});
