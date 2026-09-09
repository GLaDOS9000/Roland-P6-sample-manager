"""Wavetable waveform families and morph functions."""

import numpy as np

from pyp6.constants import WT_DRAW_POINTS, WT_CYCLE_SANE_MAX, WT_SR


def _wt_fold(x, gain):
    y = x * gain
    return 2.0 * np.abs(2.0 * (y / 4.0 - np.floor(y / 4.0 + 0.5))) - 1.0


def _wt_lerp(a, b, m):
    return a + (b - a) * m


def _wt_geom(a, b, m):
    return a * (b / a) ** m


# --- Waveform families: (synth, morph 0..1, fundamental Hz) -> (wave, desc)


def _wtf_saw(s, m, f0):
    a = _wt_lerp(1.45, 0.55, m)
    return s.add(s.k ** (-a)), f"tilt k^-{a:.2f}"


def _wtf_pulse(s, m, f0):
    d = _wt_geom(0.50, 0.015, m)
    b = 2 * np.pi * s.k * d
    return s.add_sc((1 - np.cos(b)) / s.k, np.sin(b) / s.k), f"{d*100:.2f}%"


def _wtf_triangle(s, m, f0):
    sk = _wt_lerp(0.5, 0.06, m)
    raw = np.where(s.tf < sk, s.tf / sk, 1.0 - (s.tf - sk) / (1.0 - sk)) * 2 - 1
    return s.band_limit(raw), f"skew {sk:.2f}"


def _wtf_sine(s, m, f0):
    amps = np.zeros(8)
    amps[0] = 1.0
    for j, k in enumerate([2, 3, 4, 6, 8]):
        amps[k - 1] = m ** (1.0 + 0.5 * j)
    return s.add(amps), f"stack {m:.2f}"


def _wtf_folder(s, m, f0):
    g = _wt_lerp(1.0, 8.0, m)
    return s.band_limit(_wt_fold(np.sin(2 * np.pi * s.t), g)), f"fold {g:.2f}"


def _wtf_sync(s, m, f0):
    r = _wt_lerp(1.0, 6.0, m)
    return s.band_limit(np.sin(2 * np.pi * r * s.tf)), f"ratio {r:.2f}"


def _wtf_fm(s, m, f0):
    idx = _wt_lerp(0.0, 8.0, m)
    return (s.band_limit(np.sin(2 * np.pi * s.t + idx * np.sin(4 * np.pi * s.t))),
            f"C:M 1:2 I={idx:.2f}")


def _wtf_phasedist(s, m, f0):
    bp = _wt_lerp(0.5, 0.96, m)
    pd = np.where(s.tf < bp, 0.5 * s.tf / bp, 0.5 + 0.5 * (s.tf - bp) / (1 - bp))
    return s.band_limit(np.sin(2 * np.pi * pd)), f"bp {bp:.2f}"


def _wtf_staircase(s, m, f0):
    lv = max(2, int(round(_wt_geom(32, 2, m))))
    raw = np.round((2 * s.tf - 1) * (lv / 2)) / (lv / 2)
    return s.band_limit(raw), f"{lv} levels"


_WT_VOWELS = [
    ("A", [730, 1090, 2440], [1.0, 0.50, 0.22], [110, 160, 240]),
    ("E", [530, 1840, 2480], [1.0, 0.42, 0.28], [90, 180, 250]),
    ("I", [270, 2290, 3010], [1.0, 0.35, 0.30], [70, 200, 260]),
    ("O", [570, 840, 2410], [1.0, 0.60, 0.14], [90, 130, 240]),
    ("U", [300, 870, 2240], [1.0, 0.30, 0.10], [70, 120, 230]),
]


def _wtf_vowel(s, m, f0):
    x = m * (len(_WT_VOWELS) - 1)
    i = min(int(x), len(_WT_VOWELS) - 2)
    fr = x - i
    n1, c1, g1, b1 = _WT_VOWELS[i]
    n2, c2, g2, b2 = _WT_VOWELS[i + 1]
    cen = [_wt_lerp(a, b, fr) for a, b in zip(c1, c2)]
    gai = [_wt_lerp(a, b, fr) for a, b in zip(g1, g2)]
    bws = [_wt_lerp(a, b, fr) for a, b in zip(b1, b2)]
    return s.add(s.formant(f0, cen, gai, bws, tilt=0.7)), f"{n1}>{n2} {fr:.2f}"


def _wtf_organ(s, m, f0):
    stops = [1, 2, 3, 4, 6, 8, 12, 16]
    amps = np.zeros(max(stops))
    for j, k in enumerate(stops):
        w = np.clip(m * (len(stops) - 1) - j + 1.0, 0.0, 1.0)
        amps[k - 1] = w / (1.0 + 0.25 * j)
    return s.add(amps), f"drawbars {m:.2f}"


def _wtf_piano(s, m, f0):
    tilt = _wt_lerp(1.9, 1.05, m)
    amps = s.k ** (-tilt)
    amps = amps * (1.0 + 0.45 * np.exp(-0.5 * ((s.k - 3) / 1.6) ** 2))
    amps = amps * (1.0 - 0.30 * (s.k % 2 == 0))
    amps = amps * np.exp(-(s.k * f0 / _wt_lerp(3500, 11000, m)) ** 2)
    return s.add(amps), f"hardness {m:.2f}"


def _wtf_strings(s, m, f0):
    """Bowed string, morphing by bow position rather than by brightness."""
    beta = _wt_lerp(0.26, 0.055, m)
    comb = np.abs(np.sin(np.pi * s.k * beta)) / s.k
    body = s.formant(f0, [420, 1100, 2600], [1.0, 0.55, 0.30],
                     [180, 320, 700], tilt=0.6)
    peak = float(np.max(body))
    if peak > 1e-12:
        body = body / peak
    amps = comb * (0.30 + 0.70 * body)
    amps = amps * np.exp(-(s.k * f0 / _wt_lerp(3200, 11000, m)) ** 1.6)
    return s.add(amps, phases=0.35 * np.sin(s.k)), f"bow {beta:.3f}"


def _wtf_brass(s, m, f0):
    fc = _wt_lerp(500, 3200, m)
    amps = s.formant(f0, [fc, fc * 2.1], [1.0, 0.35], [fc * 0.55, fc * 0.8], tilt=0.9)
    amps = amps * np.exp(-(s.k * f0 / _wt_lerp(2200, 9000, m)) ** 2)
    return s.add(amps), f"blow {m:.2f}"


def _wtf_bell(s, m, f0):
    partials = [1, 2, 3, 5, 7, 9, 13, 17, 23]
    amps = np.zeros(max(partials))
    ph = np.zeros(max(partials))
    rng = np.random.default_rng(77)
    for j, k in enumerate(partials):
        w = np.clip(m * len(partials) - j + 1.0, 0.0, 1.0)
        amps[k - 1] = w / (1.0 + 0.55 * j)
        ph[k - 1] = rng.random() * 2 * np.pi
    return s.add(amps, ph), f"partials {m:.2f}"


def _wtf_noise(s, m, f0):
    km = max(2, int(round(_wt_geom(3, s.h, m))))
    rng = np.random.default_rng(2024)
    amps = np.zeros(s.h)
    amps[:km] = 1.0 / np.arange(1, km + 1) ** 0.5
    return s.add(amps, rng.random(s.h) * 2 * np.pi), f"{km} harm"


WT_FAMILIES = [
    ("Saw", _wtf_saw),
    ("Pulse / PWM", _wtf_pulse),
    ("Triangle", _wtf_triangle),
    ("Sine", _wtf_sine),
    ("Wavefolder", _wtf_folder),
    ("Hard Sync", _wtf_sync),
    ("FM", _wtf_fm),
    ("Phase Distortion", _wtf_phasedist),
    ("Staircase", _wtf_staircase),
    ("Vowel Formant", _wtf_vowel),
    ("Organ", _wtf_organ),
    ("Piano", _wtf_piano),
    ("Strings", _wtf_strings),
    ("Brass", _wtf_brass),
    ("Bell / Metal", _wtf_bell),
    ("Noise Morph", _wtf_noise),
]
WT_FAMILY_MAP = dict(WT_FAMILIES)


def wt_resample_cycle(values, points=None):
    """Resamples one cycle to `points` values without aliasing."""
    points = points or WT_DRAW_POINTS
    v = np.asarray(values, dtype=np.float64)
    if v.size == points:
        return v
    if v.size < 2:
        return np.zeros(points)
    spec = np.fft.rfft(v)
    keep = min(len(spec), points // 2 + 1)
    out = np.zeros(points // 2 + 1, dtype=complex)
    out[:keep] = spec[:keep]
    return np.fft.irfft(out, n=points) * (points / float(v.size))


def wt_cycle_tone(values, hz, seconds=None, sr=WT_SR):
    """Turns one cycle into a sustained note, for auditioning."""
    from pyp6.constants import CYCLE_AUDITION_SECONDS
    seconds = seconds or CYCLE_AUDITION_SECONDS
    period = max(4, int(round(sr / float(hz))))
    cycle = wt_resample_cycle(values, period)
    peak = float(np.max(np.abs(cycle)))
    if peak > 1e-12:
        cycle = cycle / peak * 0.85
    reps = max(1, int(round(seconds * sr / period)))
    tone = np.tile(cycle, reps)
    edge = min(int(0.01 * sr), len(tone) // 4)
    if edge > 1:
        ramp = np.linspace(0.0, 1.0, edge)
        tone[:edge] *= ramp
        tone[-edge:] *= ramp[::-1]
    return tone.astype(np.float32)


def wt_load_cycle_file(path, points=None):
    """Reads a single-cycle WAV as a shape."""
    import contextlib
    import wave

    points = points or WT_DRAW_POINTS
    data, rate = None, None
    try:
        import soundfile as _sf
        data, rate = _sf.read(path, dtype="float64", always_2d=True)
        data = data.mean(axis=1)
    except Exception:
        with contextlib.closing(wave.open(path, "rb")) as wf:
            rate = wf.getframerate()
            width = wf.getsampwidth()
            n = wf.getnframes()
            raw = wf.readframes(n)
        dt = {1: np.uint8, 2: "<i2", 4: "<i4"}.get(width)
        if dt is None:
            raise ValueError(f"{width * 8}-bit WAV is not supported")
        arr = np.frombuffer(raw, dtype=dt).astype(np.float64)
        if width == 1:
            arr = (arr - 128.0) / 128.0
        else:
            arr = arr / float(2 ** (width * 8 - 1))
        ch = max(1, len(arr) // max(1, n))
        data = arr.reshape(-1, ch).mean(axis=1) if ch > 1 else arr

    frames = int(len(data))
    if frames < 4:
        raise ValueError("file is too short to be a waveform cycle")
    peak = float(np.max(np.abs(data)))
    if peak < 1e-9:
        raise ValueError("file is silent")

    resampled = wt_resample_cycle(data, points)
    peak = float(np.max(np.abs(resampled)))
    if peak > 1e-12:
        resampled = resampled / peak
    info = {"frames": frames, "rate": rate,
            "harmonics": min(frames // 2, points // 2),
            "long": frames > WT_CYCLE_SANE_MAX}
    return [round(float(v), 4) for v in resampled], info


def wt_points_to_cycle(points, s):
    """Turns a drawn polyline into a band-limited segment for WTSynth `s`."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.size < 4:
        return np.zeros(s.L)
    spec = np.fft.rfft(pts) / pts.size
    usable = min(int(s.h), pts.size // 2, len(spec) - 1)
    if usable < 1:
        return np.zeros(s.L)
    amps = 2.0 * np.abs(spec[1:usable + 1])
    phs = np.angle(spec[1:usable + 1])
    ca = (amps * np.cos(phs))[:, None] * s.cos_b[:usable]
    sa = (amps * np.sin(phs))[:, None] * s.sin_b[:usable]
    w = (ca - sa).sum(axis=0)
    peak = np.max(np.abs(w))
    return w / peak if peak > 1e-12 else w


def wt_drawn_family(entry):
    """Builds a render function for a hand-drawn family."""
    name = entry.get("name") or "Custom"
    pa = entry.get("a") or []
    pb = entry.get("b") or pa

    def render(s, m, f0, _cache={}):
        key = (s.L, s.R, s.h)
        if key not in _cache:
            _cache.clear()
            _cache[key] = (wt_points_to_cycle(pa, s), wt_points_to_cycle(pb, s))
        ca, cb = _cache[key]
        w = ca * (1.0 - m) + cb * m
        return w, f"{name} {m:.2f}"

    return render


def wt_family_entry(item):
    """Normalises one selection entry to (display_name, render_fn)."""
    if isinstance(item, dict):
        return (item.get("name") or "Custom"), wt_drawn_family(item)
    return item, WT_FAMILY_MAP[item]


def wt_selection_names(selection):
    return [(i.get("name") or "Custom") if isinstance(i, dict) else i
            for i in selection]
