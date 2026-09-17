# MeetTrace User Guide

Comprehensive guide to installing, configuring, and using MeetTrace on Windows 10/11.

---

## 1. Prerequisites

- **Operating System:** Windows 10 or Windows 11 (64-bit).
- **Audio Hardware:** Any standard microphone and speaker/headphone device supported by Windows Core Audio (WASAPI).
- **Google Chrome:** Version 110+ (for the optional Google Meet integration extension).
- **Python Environment (if running from source):** Python 3.12+ (below 3.14) and [`uv`](https://docs.astral.sh/uv/) package manager.

---

## 2. Installation & Quick Start

### Option A: Standalone Executable (Recommended for users)

1. Download or build `MeetTrace.exe` (see [Packaging](#building-standalone-executable)).
2. Place `MeetTrace.exe` in any convenient directory (e.g. `C:\Users\<User>\AppData\Local\Programs\MeetTrace` or Desktop).
3. Double-click `MeetTrace.exe` to launch.
4. MeetTrace will start in the system tray and display the compact floating recording bar.

### Option B: Running from Source (Recommended for developers)

1. Clone or navigate to the repository:
   ```powershell
   git clone https://github.com/your-org/MeetTrace.git
   cd MeetTrace
   ```

2. Initialize virtual environment and dependencies using `uv`:
   ```powershell
   uv venv
   uv sync --dev
   ```

3. Launch the desktop application:
   ```powershell
   uv run python -m meettrace.ui.app
   ```

---

## 3. Chrome Extension Setup

The companion Chrome extension enables MeetTrace to automatically detect active Google Meet meetings, extract meeting titles and URLs, and update the floating toolbar context.

> **Zero Audio Access:** The extension does **NOT** capture or stream audio. It only communicates meeting lifecycle metadata (start, stop, title, URL) to the local desktop app over an authenticated localhost port.

### Step-by-Step Extension Installation

1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Toggle on **Developer mode** in the top-right corner.
3. Click **Load unpacked** in the top-left corner.
4. Select the `extension/` directory within the MeetTrace repository (or packaged release).
5. Open MeetTrace desktop app, navigate to **Settings (⚙)**, and locate the **Localhost Bridge Secret Token**.
6. Click **Copy Token**.
7. Click the MeetTrace puzzle piece / icon in Chrome, paste the token into the extension popup, and click **Save & Connect**.
8. The extension badge will turn green (**ON**), indicating a secure connection to `127.0.0.1:38281`.

---

## 4. First-Run Meeting Workflow

### Automatic Google Meet Flow

1. With MeetTrace running, open Google Chrome and join a Google Meet room (`https://meet.google.com/xxx-yyyy-zzz`).
2. The Chrome extension detects the meeting and sends the title and room URL to the desktop app.
3. The floating recording bar automatically highlights the meeting title with a soft violet accent.
4. Click the **Record (●)** button on the floating bar (or click "Record Meeting" from the tray).
5. MeetTrace records both your microphone and computer audio (other participants) simultaneously.
6. Real-time transcription is processed locally on your CPU/GPU without cloud latency.
7. Click **Pause (⏸)** if you need to discuss something off-the-record, then click **Resume (▶)**.
8. When the meeting concludes, click **Stop (⏹)**.
9. MeetTrace writes durable meeting artifacts (`transcript.json` and `meeting.md`) into your local storage archive.

### Manual Fallback Flow

If you are not using Google Meet, or prefer not to install the Chrome extension:
1. Click **Record (●)** on the floating recording bar anytime.
2. The session starts immediately under the title `"Audio Session"`.
3. You can rename or view the meeting later in the **Meetings (📋)** tab.

---

## 5. Whisper Model Management

MeetTrace uses [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) for high-performance offline speech recognition.

### Supported Models

| Model | Size | RAM / VRAM | Accuracy | Best For |
|---|---|---|---|---|
| `base` (default) | ~140 MB | ~1 GB | Good | Everyday meetings, low latency, modest hardware |
| `small` | ~460 MB | ~2 GB | High | Multi-speaker, technical terminology, mixed EN/RU/UK |
| `medium` | ~1.5 GB | ~4 GB | Very High | Complex domain discussions, noisy backgrounds |

### First-Time Download
On first recording, faster-whisper will automatically download the chosen model from Hugging Face Hub. Downloaded models are cached locally in:
```text
%USERPROFILE%\.cache\huggingface\hub\
```

### CPU vs CUDA (NVIDIA GPU)
- **CPU (Default):** Runs on INT8 / FP32 instructions. Fully optimized for modern multi-core x86-64 CPUs.
- **CUDA:** If an NVIDIA GPU with cuDNN libraries is detected, MeetTrace can utilize FP16 GPU inference. If CUDA initialization fails, it automatically falls back to CPU execution without interrupting the user.

---

## 6. Optional Gemini Summarization

MeetTrace can generate executive summaries, decision records, and action items using Google Gemini API once a meeting ends.

### Configuration

1. Obtain a free or paid Gemini API key from [Google AI Studio](https://aistudio.google.com/).
2. In MeetTrace, click **Settings (⚙)** -> **AI Summarization**.
3. Enter your Gemini API key and choose the model (`gemini-2.5-flash` recommended).
4. Alternatively, set the environment variable:
   ```powershell
   [System.Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your-api-key-here", "User")
   ```

### Generating a Summary

1. In the MeetTrace main window, navigate to **Meetings (📋)**.
2. Select any recorded meeting.
3. Click **✨ Generate Summary** in the top action bar.
4. MeetTrace asynchronously contacts Gemini, structures the response, and merges it into `meeting.md` and `transcript.json`.
5. The raw transcript segments are never modified or overwritten.

---

## 7. Storage Layout & Artifact Schema

Meetings are stored strictly on your local filesystem under:
```text
%USERPROFILE%\MeetTrace\meetings\YYYY\MM\DD\<meeting-id>\
```

Each meeting directory contains two synchronized files:

### 1. `transcript.json`
Machine-readable source of truth containing:
- `meeting_id`: Unique identifier (`YYYYMMDD_HHMMSS_<rand>`).
- `metadata`: Dominant language, detected language confidence map, total duration, model name, and start/stop timestamps.
- `segments`: Ordered list of transcript segments with millisecond offsets `start_ms`, `end_ms`, `text`, `confidence`, and `language`.
- `source`: Platform metadata (e.g. `platform: google-meet`, `url: ...`, `meeting_code: ...`).
- `summary`: Structured AI summary fields (summary narrative, decisions, action items, open questions, follow-ups).

### 2. `meeting.md`
Human-readable, portable Markdown document:
- YAML Frontmatter with meeting ID, duration, languages, platform, and Meet URL.
- AI Summary (Summary, Decisions, Action Items) if generated.
- Timestamped transcript entries: `[HH:MM:SS] Segment text...`.

---

## 8. Application Logging

MeetTrace maintains structured, size-capped logs in:
```text
%USERPROFILE%\.meettrace\logs\meettrace.log
```

- **Rotation:** Maximum 10 MB per file, keeping 5 historical backups (`meettrace.log.1`, etc.).
- **Privacy Filtering:** All Bearer tokens and Gemini API keys are automatically redacted from log entries (`Bearer tok_...***`, `AIzaSy...***`).
- **Log Level:** `INFO` by default. Set `MEETTRACE_DEBUG=1` in your environment to enable verbose `DEBUG` logging.

---

## 9. Troubleshooting & FAQ

### Audio Not Capturing / Zero Segments Recorded
- **Check Microphone Permissions:** In Windows Settings -> Privacy & Security -> Microphone, ensure "Let desktop apps access your microphone" is turned **ON**.
- **WASAPI Default Devices:** MeetTrace records from the default Windows playback and recording endpoints. Verify in Windows Sound Settings that your active headphones/speakers are set as the "Default Device".

### Extension Shows "Disconnected" (Red Badge)
- Verify MeetTrace is running (check system tray).
- Open Settings in MeetTrace, click **Copy Token**, and re-paste into the Chrome extension popup.
- Check that port `38281` is not blocked by a third-party firewall.

### Whisper Model Download Error
- If Hugging Face Hub is unreachable due to corporate proxy or offline environment, models can be manually placed in `%USERPROFILE%\.cache\huggingface\hub\`.

---

## 10. Building Standalone Executable

To package MeetTrace into a single Windows executable:
```powershell
uv run python scripts/build_windows_exe.py
```
The resulting executable will be created at `dist/MeetTrace/MeetTrace.exe`.
