# Development

← [Back to README](../README.md)

---

## Project Layout

```
src/pyp6/
  __init__.py / __main__.py    entry point
  constants.py                 app-wide constants (BANKS, PADS, TARGET_RATES, …)
  config.py                    config file, presets, manifest I/O
  theme.py                     6 built-in themes + colour helpers
  log.py                       loguru logger setup, --debug / --log-level flags
  audio/                       info, processing, conversion, playback
  synth/                       WTSynth engine, 16 waveform families, MIDI helpers
  ui/
    widgets.py                 RoundedButton, RoundedDropdown, RoundedPanel, Tooltip
    dialogs_common.py          themed message/input dialogs + shared helpers
    waveform.py                waveform canvas drawing helpers
    nav_mixin.py               shared folder-navigation mixin
    dialogs/
      audio_preview.py         AudioPreviewDialog — file browser + waveform editor
      chop.py                  ChopDialog — multi-sample builder
      waveform_creator.py      WaveformCreatorDialog — draw/load single-cycle shapes
      synth_dialog.py          SynthDialog — wavetable builder
      audio.py                 re-export shim (AudioPreviewDialog, ChopDialog)
      synth.py                 re-export shim (SynthDialog, WaveformCreatorDialog)
  model/
    sample_slot.py             SampleSlot — one pad's state and actions
    app.py                     P6ManagerApp — root controller
tests/                         pytest suite (audio and synth; UI/model coverage is minimal)
```

---

## Running in Development

```bash
# Install runtime deps + test extras
uv sync --extra test

# Launch the app
uv run pyp6
# or
make start

# Run the test suite
uv run --extra test pytest
# or
make test
```

### CLI flags

```
uv run pyp6 --debug          # verbose log output to stderr
uv run pyp6 --log-level INFO  # set log level explicitly
```

A log file is written to `~/.pyp6/pyp6.log` on every run. **Settings → Open Log**
opens it directly.

---

## Makefile Targets

| Target | What it does |
|---|---|
| `make setup` | Create `.venv` with Python 3.13 via `uv venv` |
| `make install` | Install all runtime dependencies via `uv sync` |
| `make start` | Launch PyP6 via `uv run pyp6` |
| `make start-legacy` | Launch the original monolithic script (kept for reference) |
| `make test` | Run the pytest test suite |

---

## Tooling

| Tool | Purpose |
|---|---|
| `uv` | Dependency management + venv |
| `hatchling` | Build backend |
| `ruff` | Linting (pre-commit hook) |
| `pytest` | Test runner |
| `loguru` | Logging |
| `pedalboard` | DSP (resample, normalize, fade) |
| `sounddevice` / `soundfile` | Audio playback and file I/O |
| `tkinterdnd2` | Drag-and-drop support (optional) |

---

## Building a Standalone Windows Executable

If you want to produce your own `.exe` after modifying the source:

```
pip install pyinstaller

python -m PyInstaller PyP6-Roland-P6-Sample-Manager_3_0_0.py -y -w --onefile ^
  --icon=icon.ico ^
  --collect-data tkinterdnd2 ^
  --add-binary "C:\ffmpeg\bin\ffmpeg.exe;." ^
  --add-binary "C:\ffmpeg\bin\ffprobe.exe;." ^
  --clean
```

Notes:

- Use `;` as the separator for `--add-binary` on Windows (not `:`, which is for
  Unix/macOS paths).
- `--collect-data tkinterdnd2` is required for drag & drop; omit it and the build
  works fine, it just won't accept dropped files.
- `--clean` clears PyInstaller's cache — use it whenever you've changed the source.
- The app resolves bundled files via `sys._MEIPASS` at runtime, so ffmpeg is found
  automatically without a system PATH entry.
- Some antivirus software may flag a bundled `ffmpeg.exe` extracted at runtime;
  check Windows Defender protection history if ffmpeg-dependent features stop working.

---

## Known Weaknesses

- Test coverage ~1–10% (audio/synth functions only; zero UI/model coverage)
- No CI/CD (pre-commit hooks only, local)
- No type annotations
- Legacy monolithic script still in repo root
