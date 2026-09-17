# MeetTrace

MeetTrace is a local-first hybrid meeting recorder and transcription app for Windows 10/11.

---

## Key Features

- **100% Local Audio & Transcription:** Dual-channel capture (microphone + WASAPI system loopback) transcribed on-device with `faster-whisper`. No cloud STT services or bots joining calls.
- **No Meeting Bots:** Records natively from your Windows Core Audio subsystem with zero participant injection.
- **Companion Chrome Extension:** A lightweight Manifest V3 extension detects active Google Meet tabs and synchronizes meeting titles and URLs with the desktop app over an authenticated localhost bridge.
- **Compact Floating Toolbar:** Unobtrusive, always-on-top pill bar with recording status, duration timer, pause/resume, and meeting context display.
- **Durable Meeting Archive:** Saves human-readable Markdown notes (`meeting.md`) and rich JSON transcripts (`transcript.json`) organized by local date (`%USERPROFILE%\MeetTrace\meetings\YYYY\MM\DD\<id>\`).
- **Optional Gemini Summarization:** Post-meeting executive summaries, decisions, and action items generated on-demand using Google Gemini API.
- **Privacy-First Architecture:** Zero audio capture in the browser extension; secret token authentication; automated token/key redaction in logs.

---

## Documentation

- 📖 **[User Guide & Installation Walkthrough](docs/USER_GUIDE.md)**: Detailed setup, Chrome extension pairing, Whisper model options, and troubleshooting.
- 🔒 **[Privacy & Security Architecture](docs/PRIVACY.md)**: Security boundaries, local-first guarantees, permissions breakdown, and secret redaction.
- 🎯 **[MVP Overview](docs/mvp.md)**: Product boundaries and user journey.

---

## Quick Start (Running from Source)

### Prerequisites
- Windows 10 or Windows 11 (64-bit)
- Python 3.12+ (below 3.14)
- [`uv`](https://docs.astral.sh/uv/) package manager

### 1. Setup Virtual Environment
```powershell
uv venv
uv sync --dev
```

### 2. Run Desktop App
```powershell
uv run python -m meettrace.ui.app
```

### 3. Setup Chrome Extension (Optional, for Google Meet)
1. Open Google Chrome and visit `chrome://extensions/`.
2. Enable **Developer mode** in the top right corner.
3. Click **Load unpacked** and select the `extension/` directory.
4. In MeetTrace desktop app, open **Settings (⚙)** and copy the **Bridge Secret Token**.
5. Click the MeetTrace extension icon in Chrome, paste the token, and click **Save & Connect**.

---

## Running Tests & Quality Checks

Run the automated test suite (including unit, integration, and stress tests):
```powershell
uv run pytest
```

Check code formatting and linting with Ruff:
```powershell
uv run ruff check .
uv run ruff format --check .
```

---

## Packaging Windows Executable

MeetTrace can be packaged into a standalone Windows executable (`MeetTrace.exe`):

```powershell
uv run python scripts/build_windows_exe.py
```

The output will be generated at `dist/MeetTrace/MeetTrace.exe`.

---

## OpenSpec

OpenSpec is the source-of-truth workflow for planned changes. The current change is
`001-mvp-foundation` under `openspec/changes/001-mvp-foundation/`.

Validate specification compliance:
```powershell
openspec validate --all
```
