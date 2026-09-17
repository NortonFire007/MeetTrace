# MeetTrace Google Meet Chrome Extension

A lightweight, privacy-preserving Google Chrome Manifest V3 extension designed to detect Google Meet lifecycle events and meeting metadata, forwarding them to the local **MeetTrace** desktop application.

---

## Key Principles & Privacy Guarantee

- **No Audio/Video Capture**: The extension strictly does NOT request `tabCapture`, `desktopCapture`, microphone, or camera permissions. Audio capture remains 100% inside the desktop application via Windows Core Audio (WASAPI).
- **Minimal Permissions**: The extension only requires `storage` (to save the desktop pairing token and port) and host access to `https://meet.google.com/*` and `http://127.0.0.1/*`.
- **Authenticated Loopback Bridge**: All communication with the desktop app is sent over `127.0.0.1` using HTTP and validated with a secret shared bearer token.
- **Independent Recording Lifecycle**: MeetTrace recording can be started or stopped completely manually without the extension. If the extension is disabled or disconnected, desktop recording remains fully operational.

---

## Installation & Setup

### 1. Load the Unpacked Extension in Chrome

1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** toggle in the top-right corner.
3. Click the **Load unpacked** button.
4. Select the `extension/` folder inside the MeetTrace repository:
   ```text
   e:\Programming\pythonProj\year_2026\MeetTrace\extension
   ```
5. The extension **MeetTrace - Google Meet Bridge** will appear in your extensions list.

### 2. Connect with MeetTrace Desktop

1. Open MeetTrace desktop app and navigate to **Settings** > **Chrome Google Meet Bridge**.
2. Click **Copy Token** to copy your unique localhost bridge token.
3. Click the MeetTrace extension icon in the Chrome toolbar (or right-click the extension and choose **Options**).
4. Paste the token into the **Bridge Authentication Token** field.
5. Click **Save Settings**, then click **Test Connection** to verify that the desktop application is connected.

---

## Supported Lifecycle Events

- `MEETING_DETECTED`: Emitted when visiting a Google Meet room (`https://meet.google.com/xxx-yyyy-zzz`) in the pre-call lobby.
- `MEETING_STARTED`: Emitted when you enter an active call (call controls bar active).
- `MEETING_ENDED`: Emitted when leaving the call or navigating away.

---

## File Structure

```text
extension/
├── manifest.json                  # Manifest V3 configuration
├── README.md                      # Extension documentation & setup
├── icons/                         # 16x16, 48x48, 128x128 icons
└── src/
    ├── shared/
    │   └── constants.js           # Shared event names and defaults
    ├── content/
    │   └── meet_detector.js       # Non-invasive DOM & SPA lifecycle detector
    ├── background/
    │   └── service_worker.js      # Authenticated localhost HTTP bridge client
    └── options/
        ├── options.html           # Bridge configuration UI
        └── options.js             # Token saving and connection test
```
