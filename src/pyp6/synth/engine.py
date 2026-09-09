"""Wavetable synth engine: WTSynth, build, render, PRM sidecar."""

import os
import wave

import numpy as np

from pyp6.constants import (
    BANKS,
    NOTE_NAMES,
    PADS,
    PRM_DEFAULTS,
    PRM_TEMPLATES,
    WT_MAX_SECONDS,
    WT_MAX_SEG_FRAMES,
    WT_PEAK,
    WT_PREVIEW_SECONDS,
    WT_SEGMENTS,
    WT_SR,
)
from pyp6.synth.waveforms import (
    wt_family_entry,
    wt_selection_names,
)


def midi_to_hz(m, a4=440.0):
    return a4 * 2.0 ** ((m - 69) / 12.0)


def midi_to_name(m):
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def name_to_midi(name):
    for m in range(128):
        if midi_to_name(m) == name:
            return m
    raise ValueError(name)


def wt_tuning_info(midi, cycles, a4=440.0):
    """Segment length, actual frequency and tuning error in cents."""
    f_ideal = midi_to_hz(midi, a4)
    L = int(round(cycles * WT_SR / f_ideal))
    f_real = WT_SR * cycles / L
    return L, float(f_real), float(1200.0 * np.log2(f_real / f_ideal))


class WTSynth:
    """Generates waveforms of length L containing R cycles."""

    def __init__(self, L, R, h):
        self.L, self.R, self.h = L, R, h
        self.t = (np.arange(L) / L) * R
        self.tf = self.t % 1.0
        self.k = np.arange(1, h + 1, dtype=float)
        arg = 2 * np.pi * np.outer(self.k, self.t)
        self.sin_b = np.sin(arg)
        self.cos_b = np.cos(arg)

    def add(self, amps, phases=None):
        a = np.zeros(self.h)
        n = min(len(amps), self.h)
        a[:n] = np.asarray(amps, dtype=float)[:n]
        if phases is None:
            return a @ self.sin_b
        p = np.zeros(self.h)
        p[: min(len(phases), self.h)] = np.asarray(phases, dtype=float)[: self.h]
        return (a * np.cos(p)) @ self.sin_b + (a * np.sin(p)) @ self.cos_b

    def add_sc(self, amps_sin, amps_cos):
        s = np.zeros(self.h)
        s[: min(len(amps_sin), self.h)] = amps_sin[: self.h]
        c = np.zeros(self.h)
        c[: min(len(amps_cos), self.h)] = amps_cos[: self.h]
        return s @ self.sin_b + c @ self.cos_b

    def band_limit(self, w):
        spec = np.fft.rfft(w)
        spec[0] = 0.0
        cut = int(self.h * self.R)
        if cut + 1 < len(spec):
            spec[cut + 1 :] = 0.0
        return np.fft.irfft(spec, n=self.L)

    def formant(self, f0, centers, gains, bws, tilt=1.0):
        freqs = self.k * f0
        env = np.zeros(self.h)
        for fc, g, bw in zip(centers, gains, bws):
            env += g * np.exp(-0.5 * ((freqs - fc) / bw) ** 2)
        env += 0.02
        return (1.0 / self.k**tilt) * env


def wt_split_steps(n_families, total=WT_SEGMENTS):
    if n_families <= 0:
        return []
    base, rem = divmod(total, n_families)
    return [base + (1 if i < rem else 0) for i in range(n_families)]


def wt_harmonics_for(L, cycles, up_semitones):
    h_max = L // (2 * cycles)
    return max(4, min(h_max, int(h_max / 2.0 ** (up_semitones / 12.0)))), h_max


def wt_build(selection, midi, cycles, up_semitones, progress=None):
    """Returns (pcm_int16, rows, meta)."""
    L, f_real, cents = wt_tuning_info(midi, cycles)
    if L > WT_MAX_SEG_FRAMES:
        raise ValueError(
            f"Segment would be {L} frames, maximum is {WT_MAX_SEG_FRAMES} "
            f"({WT_MAX_SECONDS} s / {WT_SEGMENTS}). Pick a higher root note."
        )
    h, h_max = wt_harmonics_for(L, cycles, up_semitones)

    s = WTSynth(L, cycles, h)
    counts = wt_split_steps(len(selection))
    segs, rows = [], []
    step = 0
    total_steps = max(1, sum(counts))
    for item, count in zip(selection, counts):
        fam_name, fn = wt_family_entry(item)
        for j in range(count):
            m = 0.5 if count == 1 else j / (count - 1)
            w, desc = fn(s, m, f_real)
            w = s.band_limit(np.asarray(w, dtype=np.float64))
            peak = np.max(np.abs(w))
            if peak > 1e-12:
                w = w / peak
            segs.append(w * WT_PEAK)
            rows.append([step, fam_name, f"{m:.4f}", desc, step * L, f"{step * L / WT_SR:.6f}"])
            step += 1
        if progress:
            progress(step / total_steps)

    audio = np.concatenate(segs)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    meta = dict(
        L=int(L),
        cycles=int(cycles),
        f_real=float(f_real),
        cents=float(cents),
        h=int(h),
        h_max=int(h_max),
        total_frames=int(len(audio)),
        seconds=float(len(audio) / WT_SR),
        step_ms=float(L / WT_SR * 1000.0),
        top_hz=float(h * f_real),
        counts=[int(c) for c in counts],
        families=wt_selection_names(selection),
    )
    return pcm, rows, meta


def wt_render_sweep(family, midi, cycles, up_semitones, steps, seconds=WT_PREVIEW_SECONDS):
    """A morph sweep through one family."""
    L, f_real, _ = wt_tuning_info(midi, cycles)
    h, _ = wt_harmonics_for(L, cycles, up_semitones)
    Lp = max(16, int(round(WT_SR / f_real)))
    s = WTSynth(Lp, 1, max(1, min(h, Lp // 2)))
    _name, fn = wt_family_entry(family)

    steps = max(1, int(steps))
    tabs = np.empty((steps, Lp))
    for j in range(steps):
        m = 0.5 if steps == 1 else j / (steps - 1)
        w, _d = fn(s, m, f_real)
        w = s.band_limit(np.asarray(w, dtype=np.float64))
        pk = np.max(np.abs(w))
        tabs[j] = w / pk if pk > 1e-12 else w

    n = int(seconds * WT_SR)
    t = np.arange(n)
    if steps == 1:
        out = tabs[0][t % Lp]
    else:
        tp = t * ((steps - 1) / (n - 1))
        i0 = np.clip(np.floor(tp).astype(int), 0, steps - 1)
        i1 = np.clip(i0 + 1, 0, steps - 1)
        fr = tp - i0
        out = tabs[i0, t % Lp] * (1 - fr) + tabs[i1, t % Lp] * fr

    ramp = int(0.015 * WT_SR)
    env = np.ones(n)
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    return (out * env * WT_PEAK).astype(np.float32)


# ---------------------------------------------------------------------------
# .PRM sidecar
# ---------------------------------------------------------------------------


def phrase_number(bank, pad):
    """PHRASE = bank index * 6 + (pad - 1). Bank 'A', pad 1 -> 0."""
    return BANKS.index(bank) * len(PADS) + (pad - 1)


def render_prm(
    bank, pad, start_frame, size_frames, total_frames, template="Init", poly=None, overrides=None
):
    """The .PRM text for one pad."""
    values = dict(PRM_DEFAULTS)
    values.update(PRM_TEMPLATES[template])
    values["PHRASE"] = phrase_number(bank, pad)
    values["START_POS"] = int(start_frame)
    values["SIZE"] = int(size_frames)
    values["LOOP_SIZE"] = int(total_frames)
    if poly is not None:
        values["MONO_POLY"] = 1 if poly else 0
    if overrides:
        values.update(overrides)
    return "".join(f"{k}\t= {values[k]}\n" for k, _v in PRM_DEFAULTS)


def write_wavetable_files(pcm, wav_path, prm_text=None):
    with wave.open(wav_path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(WT_SR)
        f.writeframes(pcm.tobytes())
    if prm_text is not None:
        with open(os.path.splitext(wav_path)[0] + ".PRM", "w", newline="") as f:
            f.write(prm_text)


def write_wavetable_map(rows, meta, csv_path):
    import csv as _csv

    with open(csv_path, "w", newline="") as f:
        wr = _csv.writer(f)
        wr.writerow(["# root", f"{meta['f_real']:.3f} Hz", f"{meta['cents']:+.2f} cents"])
        wr.writerow(
            [
                "# segment",
                f"{meta['L']} frames",
                f"{meta['cycles']} cycles",
                f"{meta['step_ms']:.3f} ms",
            ]
        )
        wr.writerow(["# harmonics", meta["h"], f"top {meta['top_hz'] / 1000:.2f} kHz"])
        wr.writerow(
            [
                "# device",
                f"SIZE = {meta['L']}",
                f"START 0-{WT_SEGMENTS - 1} (255 is the file end, not a segment)",
            ]
        )
        wr.writerow([])
        wr.writerow(["start_pos", "family", "morph", "waveform", "start_frame", "start_sec"])
        wr.writerows(rows)


def wavetable_summary(cfg, meta):
    """Two short lines for the pad's mini display."""
    fams = meta.get("families") or []
    counts = meta.get("counts") or []
    per = (
        "-"
        if not counts
        else (str(counts[0]) if len(set(counts)) == 1 else f"{min(counts)}-{max(counts)}")
    )
    dot = " \u00b7 "
    span = f"{dot}+{cfg['up']} st" if cfg.get("up") else ""
    return [
        f"{cfg['register']}{dot}{cfg['note']}{dot}{meta['f_real']:.2f} Hz{span}",
        f"{len(fams)} famil{'y' if len(fams) == 1 else 'ies'}{dot}~{per} steps",
    ]
