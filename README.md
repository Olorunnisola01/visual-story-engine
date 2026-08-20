# Visual Story Engine

A Windows desktop app for building narrated video stories: generate clips through
Google Flow automation, then import, caption, and stitch them into a finished
video.

Built with PySide6 (Qt) and PyInstaller.

## Download

A prebuilt single-file exe is on the
[Releases page](../../releases/latest) — no Python
install required. It bundles ffmpeg and ffprobe.

## Features

- **Prompts tab** — write and manage the prompts that drive clip generation
- **Automation** — drives Google Flow in a Playwright browser session to
  generate clips and download them automatically
- **Gallery / Import** — browse generated clips and pull them into a project
- **Video tab** — transcribe audio, generate captions, and stitch clips into a
  final video with ffmpeg

Transcription uses Deepgram, and caption refinement uses an LLM endpoint. Both
keys are entered in the app at runtime and stored in local config — they are
never committed to this repository.

## Running from source

```bash
pip install -r requirements.txt
playwright install chromium
```

`assets\ffmpeg.exe` and `assets\ffprobe.exe` are gitignored because of their
size (~175 MB together). Download a Windows build from
[ffmpeg.org](https://ffmpeg.org/download.html) and place both in `assets\`
before running.

Then:

```bash
python main.py
```

or double-click `run.bat`.

## Building the exe

```bash
build_exe.bat
```

This runs PyInstaller against `Visual Story Engine.spec` and writes
`dist\Visual Story Engine.exe`.

## Notes

- Windows only — the app shells out to bundled Windows ffmpeg binaries and the
  spec files target Windows.
- The released exe is unsigned, so SmartScreen warns on first run.
- Google Flow automation depends on that site's DOM. If Flow's UI changes, the
  selector lists in `automation/flow_automation.py` need updating.
- ffmpeg and ffprobe are redistributed inside the released exe under their own
  licences.
