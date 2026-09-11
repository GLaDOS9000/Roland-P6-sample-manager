# Installation

← [Back to README](../README.md)

---

## System Requirements

- **OS:** Windows, Linux (Ubuntu/Debian tested), macOS
- **Python:** 3.10 or newer (3.13+ requires one extra package — see below)
  *(not needed for the prebuilt Windows executable)*
- **Audio output device** (any)
- **ffmpeg** — required for MP3 support, pitch/rate/mono conversion, and Chop.
  WAV-only workflows run without it, with reduced functionality.
  Already bundled in the prebuilt Windows executable.
- **`tkinterdnd2`** *(optional)* — drag-and-drop from the file manager. Everything
  else works without it. Also bundled in the prebuilt executable.

---

## Windows

### Option A: Prebuilt Executable (recommended)

A standalone `.exe` is provided for 64-bit Windows. It bundles Python, all packages,
and **ffmpeg/ffprobe** — nothing else to install.

1. Download the `.exe`.
2. Double-click to run.
3. Windows SmartScreen may flag an unsigned executable on first run; choose **Run anyway**
   if you trust the source.

### Option B: Run from Source

#### 1. Install Python

Download Python 3.13 from [python.org](https://www.python.org/downloads/). Run
commands in **Command Prompt / PowerShell**, not inside the interactive `>>>` console.

#### 2. Install uv (recommended) or use pip

```
pip install uv
```

#### 3. Install packages

**With uv:**

```
uv sync
```

**With pip:**

```
pip install sounddevice soundfile numpy pydub tkinterdnd2 audioop-lts
```

> `audioop-lts` is only needed on Python 3.13+.

#### 4. Install ffmpeg

1. Download a Windows build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
   (the "essentials" or "full" build).
2. Extract to e.g. `C:\ffmpeg` so `C:\ffmpeg\bin` contains `ffmpeg.exe` and `ffprobe.exe`.
3. Add `C:\ffmpeg\bin` to your **Path** user environment variable:
   - Windows key → "environment variables" → User variables → **Path** → Edit → New →
     enter `C:\ffmpeg\bin` → OK
   - Reopen any terminal windows for the change to take effect.
4. Verify: `ffmpeg -version`

Alternatively, use **Settings → Audio Components** to point directly to
`ffmpeg.exe`/`ffprobe.exe` without modifying PATH.

#### 5. Launch

```
uv run pyp6
```

or

```
python -m pyp6
```

---

## Linux

```bash
sudo apt update
sudo apt install python3.13 ffmpeg libportaudio2 python3-tk
```

**With uv (recommended):**

```bash
pip install uv
cd Roland-P6-sample-manager
uv sync
uv run pyp6
```

**With pip / plain venv:**

```bash
python3.13 -m venv p6env
source p6env/bin/activate
pip install sounddevice soundfile pydub numpy audioop-lts tkinterdnd2
python3 -m pyp6
```

> The venv must be reactivated (`source p6env/bin/activate`) in every new terminal session.

> If a feature appears to be missing, open **Settings → About** — it reports what actually
> loaded. Installing into the wrong venv is the most common cause.

---

## Configuration Files

Everything lives under a single folder — no manual setup required:

```
~/.pyp6/config.json     settings (theme, paths, defaults, recent presets)
~/.pyp6/temp/           trimmed / normalized / faded / chopped samples
~/.pyp6/wavetables/     WAV and PRM files for wavetable pads
~/.pyp6/waveforms.json  waveforms you drew or loaded in the Waveform Creator
```

*(On Windows: `C:\Users\<you>\.pyp6\`)*

Delete `config.json` to reset all preferences to defaults. The temp folder can be
cleared from **Settings → Temporary Files**; pads pointing at deleted files are
cleared automatically, so save a preset first if you need those edits.
