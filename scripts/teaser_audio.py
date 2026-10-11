"""Synthesise the teaser's score and key clicks.

Everything here is generated from oscillators and noise, so there is no
sample, no loop pack and no licence to honour. The only inputs are the scene
timings in ``teaser``.

The score is deliberately restrained. A product introduction competes with
its own voiceover and with whatever the viewer is half-listening to, so the
music holds a slow harmonic bed and stays out of the way; the only element
that moves quickly is the typing, which is diegetic -- it is the product
being used.

Key clicks are placed from the same timing data that drives the animation,
so they cannot drift out of sync: one character is one frame, and a click is
scheduled at the frame its character appears.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 44_100
FPS = 30
DURATION = 25.0
N = int(SR * DURATION)

rng = np.random.default_rng(20261011)


# ------------------------------------------------------------------ helpers
def t_axis(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR


def adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """Attack/decay/sustain/release envelope over ``n`` samples."""
    env = np.zeros(n)
    ai, di, ri = int(a * SR), int(d * SR), int(r * SR)
    ai, di = min(ai, n), min(di, max(0, n - ai))
    si = max(0, n - ai - di - ri)
    ri = max(0, n - ai - di - si)
    idx = 0
    if ai:
        env[idx:idx + ai] = np.linspace(0, 1, ai); idx += ai
    if di:
        env[idx:idx + di] = np.linspace(1, s, di); idx += di
    if si:
        env[idx:idx + si] = s; idx += si
    if ri:
        env[idx:idx + ri] = np.linspace(s, 0, ri)
    return env


def one_pole_lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """Cheap warmth. Not a filter design exercise -- it only needs to take the
    edge off the saw stack so the pad sits behind the clicks."""
    alpha = np.exp(-2.0 * np.pi * cutoff / SR)
    out = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1.0 - alpha) * v + alpha * acc
        out[i] = acc
    return out


def place(buf: np.ndarray, sig: np.ndarray, at_s: float) -> None:
    """Mix ``sig`` into ``buf`` starting at ``at_s`` seconds."""
    start = int(at_s * SR)
    if start >= len(buf):
        return
    end = min(len(buf), start + len(sig))
    buf[start:end] += sig[: end - start]


# ------------------------------------------------------------------- voices
def pad(freq: float, dur: float, amp: float) -> np.ndarray:
    """A detuned triangle stack: body without brightness."""
    n = int(dur * SR)
    t = t_axis(n)
    out = np.zeros(n)
    for detune, weight in ((0.0, 1.0), (-0.16, 0.6), (0.21, 0.6)):
        f = freq + detune
        # Triangle built from odd harmonics, which keeps it soft.
        for k, hw in ((1, 1.0), (3, 1 / 9), (5, 1 / 25), (7, 1 / 49)):
            out += weight * hw * np.sin(2 * np.pi * f * k * t)
    out /= 3.0
    out *= adsr(n, 1.1, 0.8, 0.72, 1.4)
    return one_pole_lowpass(out, 1400.0) * amp


def pluck(freq: float, dur: float, amp: float) -> np.ndarray:
    """A short bell-ish tone for the arpeggio."""
    n = int(dur * SR)
    t = t_axis(n)
    sig = (
        np.sin(2 * np.pi * freq * t)
        + 0.32 * np.sin(2 * np.pi * freq * 2.01 * t)
        + 0.12 * np.sin(2 * np.pi * freq * 3.02 * t)
    )
    sig *= np.exp(-t * 5.5)
    return sig * amp


def sub(freq: float, dur: float, amp: float) -> np.ndarray:
    n = int(dur * SR)
    t = t_axis(n)
    sig = np.sin(2 * np.pi * freq * t) + 0.18 * np.sin(2 * np.pi * freq * 2 * t)
    return sig * adsr(n, 0.5, 0.4, 0.8, 0.9) * amp


def key_click() -> np.ndarray:
    """One keystroke: a filtered noise transient with a short woody body.

    Varied slightly per call, because identical clicks at 30 a second read as
    a buzz rather than as typing.
    """
    n = int(0.030 * SR)
    t = t_axis(n)
    noise = rng.normal(0, 1, n) * np.exp(-t * 320.0)
    body = np.sin(2 * np.pi * rng.uniform(1500, 2300) * t) * np.exp(-t * 180.0)
    thock = np.sin(2 * np.pi * rng.uniform(150, 240) * t) * np.exp(-t * 90.0)
    sig = 0.55 * noise + 0.3 * body + 0.4 * thock
    return one_pole_lowpass(sig, 5200.0) * rng.uniform(0.75, 1.0)


# -------------------------------------------------------------------- score
#: Chord changes land on the scene cuts, so the harmony turns when the picture
#: does rather than wandering across it.
NOTE = {
    "A2": 110.00, "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61,
    "G3": 196.00, "A3": 220.00, "B3": 246.94, "C4": 261.63, "D4": 293.66,
    "E4": 329.63, "F4": 349.23, "G4": 392.00, "A4": 440.00, "C5": 523.25,
    "E5": 659.25,
}

PROGRESSION = [
    # (start_s, end_s, root, chord tones)
    (0.0, 3.5, "A2", ["A3", "C4", "E4"]),
    (3.5, 8.0, "A2", ["A3", "C4", "E4", "B3"]),
    (8.0, 13.5, "F3", ["F3", "A3", "C4", "E4"]),      # Fmaj7: the turn
    (13.5, 18.0, "C3", ["C4", "E4", "G4"]),
    (18.0, 22.0, "G3", ["G3", "B3", "D4"]),
    (22.0, 25.0, "A2", ["A3", "C4", "E4"]),
]


def build_score() -> np.ndarray:
    buf = np.zeros(N)

    for start, end, root, tones in PROGRESSION:
        dur = end - start
        for name in tones:
            place(buf, pad(NOTE[name], dur + 0.9, 0.055), start)
        place(buf, sub(NOTE[root], dur + 0.4, 0.085), start)

    # A sparse arpeggio, entering with the catalogue and thinning out at the
    # end card so the final line is not competing with movement.
    step = 0.3125                      # 96 BPM, eighths
    time = 3.5
    order = 0
    while time < 22.6:
        tones = next(
            (c[3] for c in PROGRESSION if c[0] <= time < c[1]), PROGRESSION[-1][3]
        )
        # Up-and-back, an octave above the pad.
        pattern = tones + tones[-2:0:-1]
        name = pattern[order % len(pattern)]
        freq = NOTE[name] * 2.0
        amp = 0.055 if time < 18.0 else 0.04
        place(buf, pluck(freq, 0.9, amp), time)
        order += 1
        time += step

    # A slow pulse under the conjunction section only: it marks the one place
    # in the video that is about risk.
    beat = 8.0
    while beat < 13.5:
        place(buf, sub(NOTE["A2"], 0.5, 0.075), beat)
        beat += 0.625

    return buf


# ------------------------------------------------------- typing from scenes
def click_times(clicks_json: Path) -> list[float]:
    """Absolute seconds at which a character appears.

    Read from the file the renderer wrote while drawing, not re-derived here.
    An earlier version scraped string literals out of the scene source and
    silently missed every value that comes from live data -- which is most of
    the numbers on screen -- leaving three seconds of typing in silence.
    """
    frames = json.loads(clicks_json.read_text(encoding="utf-8"))
    return [f / FPS for f in frames]


def build_clicks(times: list[float]) -> np.ndarray:
    buf = np.zeros(N)
    for at in times:
        place(buf, key_click(), at)
    return buf


# --------------------------------------------------------------------- main
def main() -> int:
    video = Path(sys.argv[1])
    out = Path(sys.argv[2])

    print("composing score…")
    score = build_score()

    times = click_times(video.parent / "clicks.json")
    print(f"placing {len(times)} key clicks…")
    clicks = build_clicks(times)

    mix = score * 0.9 + clicks * 0.30

    # A short fade at each end, and a limiter so the clicks cannot clip when
    # they stack on a chord change.
    fade = int(0.35 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-int(1.2 * SR):] *= np.linspace(1, 0, int(1.2 * SR))
    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        mix = np.tanh(mix / peak * 1.1) * 0.89

    stereo = np.stack([mix, mix], axis=1)
    wav = out.with_suffix(".wav")
    import wave

    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype("<i2").tobytes())
    print(f"wrote {wav.name}")

    print("muxing…")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-i", str(wav),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", "-movflags", "+faststart", str(out)],
        check=True, capture_output=True,
    )
    print(f"wrote {out}  ({out.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
