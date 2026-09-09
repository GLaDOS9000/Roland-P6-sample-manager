"""Theme system - color palettes and color utility functions."""

import colorsys

from pyp6.constants import BUTTON_SATURATION

# ---------------------------------------------------------------------------
# Color utility functions
# ---------------------------------------------------------------------------


def _relative_luminance(hex_color):
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(hex_a, hex_b):
    """WCAG contrast ratio between two colors (1.0 = identical, 21 = max)."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def blend_colors(hex_a, hex_b, t):
    """Mixes two colors, t=0 gives `hex_a` and t=1 gives `hex_b`."""
    a = hex_a.lstrip("#")
    b = hex_b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        ca, cb = int(a[i : i + 2], 16), int(b[i : i + 2], 16)
        out.append(int(round(ca + (cb - ca) * t)))
    return "#{:02x}{:02x}{:02x}".format(*out)


def readable_on(hex_color, background, target_ratio=4.5):
    """Nudges a color's lightness until it is readable on `background`.

    Keeps the hue so it still belongs to the palette; only moves as far as it
    has to. Used for small text drawn onto canvases, where a color picked for
    a filled shape is usually far too dark or too light to read.
    """
    if contrast_ratio(hex_color, background) >= target_ratio:
        return hex_color
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    hue, lig, sat = colorsys.rgb_to_hls(r, g, b)
    # Move away from the background: lighten on dark, darken on light.
    direction = 1.0 if _relative_luminance(background) < 0.5 else -1.0
    best = hex_color
    for step in range(1, 51):
        cand_l = min(1.0, max(0.0, lig + direction * step * 0.02))
        rr, gg, bb = colorsys.hls_to_rgb(hue, cand_l, sat)
        cand = f"#{int(rr * 255):02x}{int(gg * 255):02x}{int(bb * 255):02x}"
        best = cand
        if contrast_ratio(cand, background) >= target_ratio:
            return cand
    return best


def fill_for_white_text(hex_color, target_ratio=4.5, saturation_scale=BUTTON_SATURATION):
    """Turns an accent into a button fill that carries white text.

    Two steps, both in HLS so the hue never moves: pull the saturation back
    to `saturation_scale` of the original, then lower the lightness only as
    far as needed for white text to reach `target_ratio`. A large colored
    button is a much bigger block of color than the same accent used as a
    thin line of status text, and at full saturation those blocks shout -
    hence the first step, which applies on every theme.

    The order matters: desaturating changes luminance, so the contrast
    search has to run afterwards or the guarantee wouldn't hold."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    saturation *= saturation_scale

    def at(lum):
        rr, gg, bb = colorsys.hls_to_rgb(hue, lum, saturation)
        return f"#{round(rr * 255):02X}{round(gg * 255):02X}{round(bb * 255):02X}"

    if contrast_ratio(at(lightness), "#FFFFFF") >= target_ratio:
        return at(lightness)  # already dark enough; keep the original brightness

    lo, hi = 0.0, lightness
    for _ in range(24):  # binary search; 24 steps is far finer than 8-bit color
        mid = (lo + hi) / 2.0
        if contrast_ratio(at(mid), "#FFFFFF") >= target_ratio:
            lo = mid  # still readable - try to keep more of the original brightness
        else:
            hi = mid
    return at(lo)


# ---------------------------------------------------------------------------
# Theme palettes
# ---------------------------------------------------------------------------

dark = {
    "BG_DARK": "#1E1E24",
    "BG_PANEL": "#2A2A33",
    "BG_INPUT": "#33333E",
    "FG_TEXT": "#E8E8ED",
    "FG_MUTED": "#9A9AA5",
    "ACCENT_BLUE": "#5FA6C0",
    "ACCENT_GREEN": "#6BB06F",
    "ACCENT_RED": "#DD807C",
    "ACCENT_ORANGE": "#CC8A3D",
    "ACCENT_PURPLE": "#8C5A99",
    "SELECT_GREEN": "#3E7A3E",
    "BORDER_COLOR": "#3D3D48",
    "BORDER_LIGHT": "#5C5C6A",
    "WAVE_BG": "#33333E",
    "HOVER_BG": "#3B3B47",
}

bright = {
    "BG_DARK": "#EFF1F5",
    "BG_PANEL": "#FFFFFF",
    "BG_INPUT": "#E6E9EF",
    "FG_TEXT": "#4C4F69",
    "FG_MUTED": "#5C5F73",
    "ACCENT_BLUE": "#1B57CE",
    "ACCENT_GREEN": "#337524",
    "ACCENT_RED": "#C10E35",
    "ACCENT_ORANGE": "#A85107",
    "ACCENT_PURPLE": "#7B33D6",
    "SELECT_GREEN": "#CFE6C7",
    "BORDER_COLOR": "#CCD0DA",
    "BORDER_LIGHT": "#BCC0CC",
    "WAVE_BG": "#DCE0E8",
    "HOVER_BG": "#E1E4EA",
}

latte = {
    "BG_DARK": "#E4E6EC",
    "BG_PANEL": "#F2F3F7",
    "BG_INPUT": "#D8DBE3",
    "FG_TEXT": "#3F4256",
    "FG_MUTED": "#5C5F73",
    "ACCENT_BLUE": "#2F5FBF",
    "ACCENT_GREEN": "#396E2E",
    "ACCENT_RED": "#A8324A",
    "ACCENT_ORANGE": "#9A5518",
    "ACCENT_PURPLE": "#6B44AB",
    "SELECT_GREEN": "#C7DCC0",
    "BORDER_COLOR": "#C3C6D2",
    "BORDER_LIGHT": "#ACB0BE",
    "WAVE_BG": "#CCD0DA",
    "HOVER_BG": "#CFD3DC",
}

tokyo = {
    "BG_DARK": "#1A1B26",
    "BG_PANEL": "#24283B",
    "BG_INPUT": "#292E42",
    "FG_TEXT": "#C0CAF5",
    "FG_MUTED": "#8A8FAD",
    "ACCENT_BLUE": "#7AA2F7",
    "ACCENT_GREEN": "#9ECE6A",
    "ACCENT_RED": "#F7768E",
    "ACCENT_ORANGE": "#FF9E64",
    "ACCENT_PURPLE": "#BB9AF7",
    "SELECT_GREEN": "#2E4B36",
    "BORDER_COLOR": "#3B4261",
    "BORDER_LIGHT": "#545C7E",
    "WAVE_BG": "#16161E",
    "HOVER_BG": "#343A55",
}

dracula = {
    "BG_DARK": "#282A36",
    "BG_PANEL": "#343746",
    "BG_INPUT": "#44475A",
    "FG_TEXT": "#F8F8F2",
    "FG_MUTED": "#9CA0B0",
    "ACCENT_BLUE": "#8BE9FD",
    "ACCENT_GREEN": "#50FA7B",
    "ACCENT_RED": "#FF7B7B",
    "ACCENT_ORANGE": "#FFB86C",
    "ACCENT_PURPLE": "#BD93F9",
    "SELECT_GREEN": "#2F5D3F",
    "BORDER_COLOR": "#44475A",
    "BORDER_LIGHT": "#6272A4",
    "WAVE_BG": "#21222C",
    "HOVER_BG": "#4E5266",
}

modern = {
    "BG_DARK": "#1A1B23",
    "BG_PANEL": "#22232D",
    "BG_INPUT": "#2C2D38",
    "FG_TEXT": "#EDEDF2",
    "FG_MUTED": "#8E8FA3",
    "ACCENT_BLUE": "#6C8EEF",
    "ACCENT_GREEN": "#4ADE80",
    "ACCENT_RED": "#F87171",
    "ACCENT_ORANGE": "#FBBF6D",
    "ACCENT_PURPLE": "#C084FC",
    "SELECT_GREEN": "#1F4D34",
    "BORDER_COLOR": "#34353F",
    "BORDER_LIGHT": "#4A4B58",
    "WAVE_BG": "#2C2D38",
    "HOVER_BG": "#33343F",
}

THEMES = {
    "dark": dark,
    "bright": bright,
    "latte": latte,
    "tokyo": tokyo,
    "dracula": dracula,
    "modern": modern,
}
