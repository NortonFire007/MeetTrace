# MeetTrace

MeetTrace is a local-first hybrid meeting recorder and transcription app for Windows.

## MVP direction

- **Desktop app:** Python + PySide6.
- **Speech-to-text:** local Whisper-compatible engine (initial target: faster-whisper).
- **Meeting storage:** Markdown + JSON artifacts grouped by local date.
- **Summarization:** optional Gemini API after a meeting ends.
- **Google Meet integration:** a lightweight Chrome extension detects/associates the Meet page and communicates with the desktop app; audio capture remains in the desktop app.
- **UI:** system-tray app plus a small always-on-top floating recording bar.

The design intentionally keeps audio capture behind an interface until the Windows WASAPI/loopback spike identifies the most reliable implementation.

## Repository layout

```text
meettrace/
├── openspec/
│   ├── config.yaml
│   └── changes/001-mvp-foundation/
├── src/meettrace/
├── tests/
├── extension/
├── docs/
├── pyproject.toml
└── README.md
```

## Development

Python 3.12+ (below 3.14) is the current project target.

Recommended local workflow with `uv`:

```powershell
uv venv
uv sync --dev
```

Run tests:

```powershell
uv run pytest
```

## OpenSpec

OpenSpec is the source-of-truth workflow for planned changes. The current change is
`001-mvp-foundation` and its artifacts are under `openspec/changes/001-mvp-foundation/`.

Install the CLI on the development machine if needed:

```powershell
npm install -g @fission-ai/openspec@latest
openspec --version
```

Then initialize the repository for your AI tool (Cursor is supported):

```powershell
openspec init
```

Do not replace the existing change artifacts; use them as the current planning baseline.
