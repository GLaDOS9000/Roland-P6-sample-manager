"""Waveform drawing helpers for Tkinter canvases."""

from pyp6._theme_vars import (
    ACCENT_ORANGE,
    BG_DARK,
    TRUNCATE_TINT_STIPPLE,
    WAVE_COLOR,
)
from pyp6.constants import MIN_TRIM_SECONDS, MIN_VISIBLE_SECONDS


def draw_bracket_marker(canvas, x, height_px, color, side, width_px=3, arm_len=10, tag="marker"):
    """Draws a trim marker shaped like a square bracket ('[' or ']') - a
    thick vertical line with short horizontal arms at top/bottom pointing
    into the selected region, so it reads clearly as 'the edge of the
    selection' instead of a thin, easy-to-miss line.
    side: 'start' (arms point right, like '[') or 'end' (arms point left,
    like ']')."""
    canvas.create_line(x, 0, x, height_px, fill=color, width=width_px, tags=tag)
    direction = 1 if side == "start" else -1
    x2 = x + direction * arm_len
    canvas.create_line(x, 1, x2, 1, fill=color, width=width_px, tags=tag)
    canvas.create_line(x, height_px - 1, x2, height_px - 1, fill=color, width=width_px, tags=tag)


def max_zoom_for(duration_seconds):
    """Highest zoom factor that still makes sense for this file.

    A fixed cap is the same mistake the trim minimum used to make: 30x of a
    three-minute track still shows nearly five seconds across the canvas, so
    a 10 ms selection would be two pixels wide and impossible to place. The
    cap scales with the file instead, so the narrowest view is always about
    the same number of milliseconds regardless of how long the source is.
    """
    if not duration_seconds or duration_seconds <= 0:
        return 30.0
    return max(30.0, float(duration_seconds) / MIN_VISIBLE_SECONDS)


def min_trim_fraction(duration_seconds):
    """Smallest gap the two trim markers may have, as a fraction.

    Expressed in seconds and converted here, because a fixed fraction scales
    with the file: 1% of a three-minute track is 1.8 s, which makes it
    impossible to grab a short hit out of a long recording. Falls back to a
    fraction when the duration is not known yet, and never exceeds half the
    file so the markers stay usable on very short samples.
    """
    if not duration_seconds or duration_seconds <= 0:
        return 0.01
    return min(0.5, MIN_TRIM_SECONDS / float(duration_seconds))


def draw_waveform_on_canvas(
    canvas,
    data,
    start_frac=0.0,
    end_frac=1.0,
    width_px=480,
    height_px=80,
    color=WAVE_COLOR,
    tag="waveform",
    y_offset=0,
    clear=True,
):
    """Draws a waveform directly on a Tkinter canvas as a single filled
    polygon (min/max envelope per pixel column). This replaces the previous
    matplotlib -> PNG file -> PhotoImage round-trip, which was by far the
    slowest part of the UI (figure creation, disk I/O, PNG decode on every
    redraw). Pure in-memory numpy + one canvas.create_polygon() call.

    y_offset/height_px let you draw into a sub-region of a taller canvas
    (used to stack left/right channels for stereo samples). clear=False lets
    you draw a second waveform under the same tag without wiping the first."""
    if clear:
        canvas.delete(tag)
    if data is None:
        return
    n = len(data)
    if n == 0:
        return
    start_i = max(0, min(int(start_frac * n), n - 1))
    end_i = max(start_i + 1, min(int(end_frac * n), n))
    segment = data[start_i:end_i]
    seg_len = len(segment)
    if seg_len == 0:
        return

    width_px = max(1, int(width_px))
    mid_y = y_offset + height_px / 2.0
    scale = (height_px / 2.0) * 0.95

    if seg_len <= width_px:
        # Too few samples to fill every column - just draw the raw points.
        points = []
        for i in range(seg_len):
            x = (i / max(seg_len - 1, 1)) * width_px
            y = mid_y - float(segment[i]) * scale
            points.extend([x, y])
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=1, tags=tag)
        return

    samples_per_px = seg_len / width_px
    top_points = []
    bottom_points = []
    for px in range(width_px):
        lo = int(px * samples_per_px)
        hi = int((px + 1) * samples_per_px)
        hi = max(hi, lo + 1)
        hi = min(hi, seg_len)
        if lo >= seg_len:
            break
        chunk = segment[lo:hi]
        if len(chunk) == 0:
            v_min = v_max = 0.0
        else:
            v_min = float(chunk.min())
            v_max = float(chunk.max())
        top_points.append((px, mid_y - v_max * scale))
        bottom_points.append((px, mid_y - v_min * scale))

    if not top_points:
        return

    poly = []
    for x, y in top_points:
        poly.extend([x, y])
    for x, y in reversed(bottom_points):
        poly.extend([x, y])

    canvas.create_polygon(*poly, fill=color, outline=color, tags=tag)


def draw_truncate_overlay(canvas, x_cut, x_right, height_px, tag="truncate"):
    """Dark wash + orange tint over [x_cut, x_right] plus a dashed cutoff
    line - the app-wide visual language for "the P-6 will cut this off".

    Shared by the main waveform, the pad mini waveforms, the pad editor and
    the Chop view so all four look identical; callers only work out where
    the cut is, never how it's drawn. Purely additive - clearing the tag is
    left to the caller, so a caller that needs several shaded regions in one
    redraw can just call this repeatedly."""
    if x_right <= x_cut:
        return
    canvas.create_rectangle(
        x_cut, 0, x_right, height_px, fill=BG_DARK, stipple="gray50", outline="", tags=tag
    )
    canvas.create_rectangle(
        x_cut,
        0,
        x_right,
        height_px,
        fill=ACCENT_ORANGE,
        stipple=TRUNCATE_TINT_STIPPLE,
        outline="",
        tags=tag,
    )
    canvas.create_line(
        x_cut, 0, x_cut, height_px, fill=ACCENT_ORANGE, width=1, dash=(3, 2), tags=tag
    )
