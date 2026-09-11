# Troubleshooting

← [Back to README](../README.md)

---

| Symptom | Likely cause / fix |
|---|---|
| `SyntaxError: invalid syntax` on `pip install ...` | You typed the command inside the Python console (`>>>`). Run `exit()` first, then use a regular terminal. |
| `'pip' is not recognized` | Use `python -m pip install ...` instead. |
| `ModuleNotFoundError: No module named 'audioop'` | Python 3.13+: run `pip install audioop-lts`. Not applicable with the prebuilt executable. |
| A feature is silently missing | Open **Settings → About** — it reports what actually loaded. Installing into the wrong venv is the most common cause. |
| pydub missing warning | Run `pip install pydub` (and `audioop-lts` on Python 3.13+). Should not occur with the prebuilt executable. |
| ffmpeg warning, but conversion still works | You may be running a stale build/cache — rebuild with `--clean`, or check Settings for a stale manual ffmpeg path override. About shows the path actually in use. |
| MP3 preview/conversion fails | ffmpeg not installed or not on PATH; verify with `ffmpeg -version`. Not applicable with the prebuilt executable. |
| `'pyinstaller' is not recognized` | Its Scripts folder isn't on PATH; run `python -m PyInstaller ...` instead. |
| Windows flags the executable as unrecognized | Expected for an unsigned third-party `.exe`; choose **Run anyway** in SmartScreen if you trust the source. |
| Samples not detected on the device | Confirm the IMPORT folder path via Settings. |
| A pad went empty on its own | Its sample was an edited file in the temp folder, which was cleared. Save edited samples into a preset to keep them. |
| Chop output sounds heavily cut off | Slice count too high for the sample length/rate; reduce the slice count or use a lower sample rate / mono. Anything shaded orange in the waveform is what gets cut. |
| Samples not transferring to the P-6 | Only a configurable amount (default 10 MB warning threshold) can be transferred at once; export banks in smaller groups. |
| Dropping files onto pads never works | **Settings → About**: if it says `tkinterdnd2 not available`, run `pip install tkinterdnd2` into the venv you actually start the app from. |
| A drop is occasionally missed on Linux | Known under Wayland; About will show drag & drop as `active`. Drag the file again, or use the pad's **Load** button. |
| Startup problems you want to diagnose | Launch with `--debug` flag or set `--log-level DEBUG`. The log file at `~/.pyp6/pyp6.log` records every phase. |
| The wavetable sounds wrong on the device | **SIZE must be 1.** At any other SIZE the loop covers more or less than one waveform and the pitch is off. |
| START at maximum sounds an octave up | Position 255 is past the last waveform. Use 0–254. |
| A family barely changes across its steps | Give it more room by putting fewer families in the step order. |
| Load and Chop are greyed out on a pad | It holds a wavetable. Eject it to use the pad for a normal sample; Synth stays available for rebuilding the table. |
| Someone else's preset is missing a waveform | It was saved with a version that didn't store waveforms, or the shape data was lost. The preset check names the family; ask for a re-save. |
| A loaded single-cycle file sounds dull | Short files carry less detail — that is the file, not the app. |

---

If none of these apply, open **Settings → About**, click **Copy Info**, and include that
in your bug report at the project's issue tracker.
