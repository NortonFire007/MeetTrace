/**
 * Options and popup logic for configuring MeetTrace bridge settings.
 */

const STORAGE_KEYS = {
  TOKEN: "meettrace_bridge_token",
  PORT: "meettrace_bridge_port",
};

const tokenInput = document.getElementById("tokenInput");
const portInput = document.getElementById("portInput");
const saveBtn = document.getElementById("saveBtn");
const testBtn = document.getElementById("testBtn");
const statusMessage = document.getElementById("statusMessage");

function showStatus(text, isSuccess) {
  statusMessage.textContent = text;
  statusMessage.className = isSuccess ? "success" : "error";
}

// Load saved preferences
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get([STORAGE_KEYS.TOKEN, STORAGE_KEYS.PORT], (result) => {
    if (result[STORAGE_KEYS.TOKEN]) {
      tokenInput.value = result[STORAGE_KEYS.TOKEN];
    }
    if (result[STORAGE_KEYS.PORT]) {
      portInput.value = result[STORAGE_KEYS.PORT];
    }
  });
});

// Save preferences
saveBtn.addEventListener("click", () => {
  const token = tokenInput.value.trim();
  const port = parseInt(portInput.value.trim(), 10) || 38281;

  if (!token) {
    showStatus("Please paste a valid bridge token from MeetTrace Settings.", false);
    return;
  }

  chrome.storage.local.set(
    {
      [STORAGE_KEYS.TOKEN]: token,
      [STORAGE_KEYS.PORT]: port,
    },
    () => {
      showStatus("Settings saved successfully!", true);
    }
  );
});

// Test connection
testBtn.addEventListener("click", () => {
  statusMessage.style.display = "none";
  testBtn.disabled = true;
  testBtn.textContent = "Checking...";

  chrome.runtime.sendMessage({ type: "TEST_CONNECTION" }, (response) => {
    testBtn.disabled = false;
    testBtn.textContent = "Test Connection";

    if (!response) {
      showStatus("Could not communicate with extension background worker.", false);
      return;
    }

    if (response.connected) {
      const state = response.data ? response.data.recording_state : "ready";
      showStatus(`Connected to MeetTrace Desktop! (App state: ${state})`, true);
    } else {
      showStatus(response.error || "Connection failed.", false);
    }
  });
});
