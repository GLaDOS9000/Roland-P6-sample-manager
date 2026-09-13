"""Spectrum waterfall display widget for PyP6 wavetable visualisation.

Renders a 2-D magnitude heatmap of the frequency content across all 255
wavetable segments:

    X-axis — harmonic bins 1 .. min(64, L//2)
    Y-axis — segment index 0 (top) .. 254 (bottom)
    Color  — Viridis-inspired 8-point LUT, dark = silent, bright = loud

Rendering pipeline (pure numpy + Tkinter, no PIL/Pillow):

    pcm_int16 (255*L,) int16
        → reshape (255, L) float64 / 32767.0
        → rfft(axis=1) → magnitude  (255, L//2+1)
        → drop DC bin, keep bins 1..N_BINS (default 64)
        → 20·log10(|·| + ε)  [dB]
        → clip to [-80, 0] dB, normalise to [0, 1]
        → map through 8-point Viridis LUT → (255, N_BINS, 3) uint8
        → nearest-neighbour resize to canvas pixels via numpy fancy-indexing
        → PPM bytes ("P6\\n{W} {H}\\n255\\n" + raw RGB)
        → tk.PhotoImage(data=ppm, format="PPM") → canvas.create_image()

Public API
----------
WaterfallCanvas(parent, *, parent_bg, width, height)
    .draw_waterfall(pcm_int16, meta) -> None
    .clear() -> None

WaterfallDialog(parent, sample_name, pcm_int16, meta)
    Modal Toplevel wrapping a WaterfallCanvas.
"""

import tkinter as tk

import numpy as np

from pyp6._theme_vars import (
    ACCENT_RED,
    BG_DARK,
    BG_INPUT,
    BORDER_COLOR,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
)
from pyp6.constants import UI_FAMILY, WT_SEGMENTS
from pyp6.ui.dialogs_common import (
    add_tooltip,
    center_toplevel_on_parent,
    style_label,
    style_toplevel,
)
from pyp6.ui.widgets import RoundedButton

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_N_BINS = 64  # max harmonic bins displayed on X axis
_DB_FLOOR = -80.0  # dB below which signal is treated as silent
_DB_CEIL = 0.0  # 0 dB reference (normalised peak)

# 8-point Viridis-inspired LUT, perceptually dark → bright
_VIRIDIS_LUT = np.array(
    [
        [68, 1, 84],  # 0/7 — deep purple  (silent)
        [59, 82, 139],  # 1/7 — blue
        [33, 145, 140],  # 2/7 — teal
        [94, 201, 98],  # 3/7 — green
        [253, 231, 37],  # 4/7 — yellow
        [230, 126, 34],  # 5/7 — orange
        [192, 57, 43],  # 6/7 — red
        [142, 37, 63],  # 7/7 — dark magenta (loud)
    ],
    dtype=np.uint8,
)

# Left/bottom margins reserved for axis labels (pixels)
_MARGIN_LEFT = 40
_MARGIN_BOTTOM = 20


# ---------------------------------------------------------------------------
# DSP helpers
# ---------------------------------------------------------------------------


def _compute_spectrogram(pcm_int16: np.ndarray, meta: dict) -> np.ndarray:
    """Return (255, N) float32 array of dB magnitudes, normalised to [0, 1].

    ``N = min(_N_BINS, L//2)`` where ``L = meta["L"]``.
    """
    L = int(meta["L"])
    frames = pcm_int16.reshape(WT_SEGMENTS, L).astype(np.float64) / 32767.0

    # rfft → magnitude, skip DC bin 0
    spec = np.abs(np.fft.rfft(frames, axis=1))[:, 1:]  # (255, L//2)

    n_bins = min(_N_BINS, spec.shape[1])
    spec = spec[:, :n_bins]  # (255, n_bins)

    db = 20.0 * np.log10(spec + 1e-9)
    db = np.clip(db, _DB_FLOOR, _DB_CEIL).astype(np.float32)
    return (db - _DB_FLOOR) / (_DB_CEIL - _DB_FLOOR)  # [0, 1]


def _apply_lut(norm: np.ndarray) -> np.ndarray:
    """Map (H, W) float32 [0, 1] array to (H, W, 3) uint8 via _VIRIDIS_LUT."""
    n = len(_VIRIDIS_LUT) - 1
    idx_f = norm * n  # float indices into LUT
    lo = np.clip(idx_f.astype(np.int32), 0, n)
    hi = np.minimum(lo + 1, n)
    frac = (idx_f - lo)[..., np.newaxis]  # fractional part
    rgb = (
        _VIRIDIS_LUT[lo].astype(np.float32) * (1.0 - frac)
        + _VIRIDIS_LUT[hi].astype(np.float32) * frac
    )
    return rgb.astype(np.uint8)


def _resize_nearest(rgb: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """Nearest-neighbour resize (H, W, 3) → (out_h, out_w, 3)."""
    in_h, in_w = rgb.shape[:2]
    row_idx = (np.arange(out_h) * in_h / out_h).astype(int)
    col_idx = (np.arange(out_w) * in_w / out_w).astype(int)
    return rgb[np.ix_(row_idx, col_idx)]


def _to_ppm(rgb: np.ndarray) -> bytes:
    """Convert (H, W, 3) uint8 array to PPM binary bytes (P6 format)."""
    h, w = rgb.shape[:2]
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    return header + rgb.tobytes()


# ---------------------------------------------------------------------------
# WaterfallCanvas
# ---------------------------------------------------------------------------


class WaterfallCanvas(tk.Frame):
    """Spectrum waterfall heatmap widget.

    Displays magnitude spectrum (dB) of a 255-segment wavetable as a 2-D
    colour image on a Tkinter Canvas.  No external image libraries required.
    """

    def __init__(self, parent, *, parent_bg=BG_DARK, width=500, height=180):
        super().__init__(parent, bg=parent_bg)

        self._plot_h = height
        self._cached_spec: np.ndarray | None = None  # last computed (255, N)
        self._photo = None  # keep PhotoImage alive

        # Canvas: the actual heatmap sits inside the left/bottom margins
        self._canvas = tk.Canvas(
            self,
            bg=WAVE_BG,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            height=height + _MARGIN_BOTTOM,
            width=width,
        )
        self._canvas.pack(fill="x", expand=True)
        self._canvas.bind("<Configure>", self._on_resize)

        self._draw_placeholder()

    # -- public ---------------------------------------------------------------

    def draw_waterfall(self, pcm_int16: np.ndarray, meta: dict) -> None:
        """Compute spectrogram from wavetable data and render the heatmap."""
        self._cached_spec = _compute_spectrogram(pcm_int16, meta)
        self._render()

    def clear(self) -> None:
        """Reset to empty placeholder state."""
        self._cached_spec = None
        self._photo = None
        self._canvas.delete("all")
        self._draw_placeholder()

    # -- private --------------------------------------------------------------

    def _on_resize(self, _event) -> None:
        if self._cached_spec is not None:
            self._render()

    def _plot_width(self) -> int:
        """Pixel width of the heatmap area (canvas width minus left margin)."""
        return max(1, self._canvas.winfo_width() - _MARGIN_LEFT)

    def _render(self) -> None:
        if self._cached_spec is None:
            return

        pw = self._plot_width()
        ph = self._plot_h

        # Build RGB image
        rgb = _apply_lut(self._cached_spec)  # (255, N_bins, 3)
        rgb_scaled = _resize_nearest(rgb, ph, pw)  # (ph, pw, 3)
        ppm = _to_ppm(rgb_scaled)

        self._photo = tk.PhotoImage(data=ppm, format="PPM")
        c = self._canvas
        c.delete("all")
        c.create_image(_MARGIN_LEFT, 0, anchor="nw", image=self._photo)

        self._draw_axes(pw, ph, self._cached_spec.shape[1])

    def _draw_placeholder(self) -> None:
        self._canvas.create_text(
            _MARGIN_LEFT + 10,
            self._plot_h // 2,
            text="No spectrum computed yet — click Compute Spectrum.",
            anchor="w",
            fill=FG_MUTED,
            font=(UI_FAMILY, 8),
        )

    def _draw_axes(self, pw: int, ph: int, n_bins: int) -> None:
        c = self._canvas

        # Y-axis label
        c.create_text(
            8,
            ph // 2,
            text="Seg",
            anchor="center",
            fill=FG_MUTED,
            font=(UI_FAMILY, 7),
            angle=90,
        )

        # Y-axis ticks: segments 0, 64, 128, 192, 254
        for seg in (0, 64, 128, 192, 254):
            y = int(seg / 254.0 * (ph - 1))
            c.create_line(_MARGIN_LEFT - 4, y, _MARGIN_LEFT, y, fill=FG_MUTED)
            c.create_text(
                _MARGIN_LEFT - 6,
                y,
                text=str(seg),
                anchor="e",
                fill=FG_MUTED,
                font=(UI_FAMILY, 7),
            )

        # X-axis: harmonic bins
        x_ticks = [b for b in (1, 8, 16, 32, 64) if b <= n_bins]
        for bin_n in x_ticks:
            x = _MARGIN_LEFT + int((bin_n - 1) / max(n_bins - 1, 1) * (pw - 1))
            c.create_line(x, ph, x, ph + 3, fill=FG_MUTED)
            c.create_text(
                x,
                ph + 10,
                text=str(bin_n),
                anchor="center",
                fill=FG_MUTED,
                font=(UI_FAMILY, 7),
            )

        c.create_text(
            _MARGIN_LEFT + pw // 2,
            ph + _MARGIN_BOTTOM - 2,
            text="Harmonic bin",
            anchor="center",
            fill=FG_MUTED,
            font=(UI_FAMILY, 7),
        )

        # Border line between margin and plot
        c.create_line(_MARGIN_LEFT, 0, _MARGIN_LEFT, ph, fill=BORDER_COLOR)
        c.create_line(_MARGIN_LEFT, ph, _MARGIN_LEFT + pw, ph, fill=BORDER_COLOR)


# ---------------------------------------------------------------------------
# WaterfallDialog
# ---------------------------------------------------------------------------


class WaterfallDialog(tk.Toplevel):
    """Modal dialog showing a WaterfallCanvas for a loaded wavetable pad."""

    def __init__(
        self,
        parent: tk.Misc,
        sample_name: str,
        pcm_int16: np.ndarray,
        meta: dict,
    ) -> None:
        super().__init__(parent)
        style_toplevel(self)
        self.title(f"Spectrum  —  {sample_name}")
        self.transient(parent)
        self.resizable(True, False)

        root = tk.Frame(self, bg=BG_DARK, padx=12, pady=12)
        root.pack(fill="both", expand=True)

        # Info line
        L = meta.get("L", "?")
        cycles = meta.get("cycles", "?")
        f_real = meta.get("f_real", 0.0)
        info_lbl = tk.Label(
            root,
            text=(
                f"Segment length: {L} samples  │  Cycles: {cycles}  │  Base freq: {f_real:.1f} Hz"
            ),
            anchor="w",
        )
        style_label(info_lbl, bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8))
        info_lbl.pack(fill="x", pady=(0, 8))

        # Waterfall
        self._waterfall = WaterfallCanvas(root, parent_bg=BG_DARK, width=600, height=220)
        self._waterfall.pack(fill="x", pady=(0, 8))
        add_tooltip(
            self._waterfall,
            f"Magnitude spectrum (dB) across all 255 wavetable segments.\n"
            f"X: harmonic bin (1–{_N_BINS}), Y: segment (0–254).\n"
            f"Bright = loud, dark = silent.",
        )

        try:
            self._waterfall.draw_waterfall(pcm_int16, meta)
        except Exception as exc:
            err_lbl = tk.Label(root, text=f"Could not compute spectrum: {exc}")
            style_label(err_lbl, bg=BG_DARK, fg=ACCENT_RED, font=(UI_FAMILY, 8))
            err_lbl.pack()

        # Close button
        close_btn = RoundedButton(
            root,
            text="Close",
            command=self.destroy,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
            height=26,
        )
        close_btn.pack(pady=(4, 0))

        center_toplevel_on_parent(self, parent)
        self.grab_set()
