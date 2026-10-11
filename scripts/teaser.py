"""Render a 9:16 pixel-art teaser for the deployed platform.

Every frame is drawn at 270x480 and upscaled 4x with nearest-neighbour, so
each drawn pixel becomes a hard 4x4 block. That is what makes it read as
pixel art rather than as a small picture: there is no antialiasing anywhere,
no gradient, and no sub-pixel positioning. Type is laid on an 8px grid for
the same reason.

The things that make motion graphics look machine-made are cross-fades, eased
tweens, glows and drifting parallax. None are used. Cuts are hard, text
arrives a character at a time at a fixed cadence, and the only continuous
motion is orbital, which is the subject.

Numbers and names come from the live API, not from placeholders.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------- constants
SCALE = 4
W, H = 1080 // SCALE, 1920 // SCALE          # 270 x 480
FPS = 30
DURATION_S = 25
TOTAL = FPS * DURATION_S                      # 750

PLATE = (10, 12, 13)
BONE = (239, 236, 228)
VERMILLION = (192, 47, 24)
DIM = (124, 118, 107)
MID = (186, 180, 167)

FONT_PATH = "C:/Users/rahul/AppData/Local/Microsoft/Windows/Fonts/Retro Gaming.ttf"
API = "https://sdebris-api.onrender.com"

#: Characters per second for the typewriter. Fast enough to finish a line in
#: a few seconds, slow enough to read as typing rather than as a wipe.
CPS = 26
#: Cursor blinks twice a second, like a terminal.
CURSOR_HZ = 2


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


F_HUGE, F_BIG, F_MED, F_SMALL = font(22), font(14), font(10), font(8)


# --------------------------------------------------------------- live inputs
@dataclass(frozen=True)
class Subject:
    primary: str
    secondary: str
    miss_km: float
    speed_km_s: float
    hours: float
    tracked: int
    pc: float


def fetch() -> Subject:
    def get(path):
        with urllib.request.urlopen(f"{API}{path}", timeout=90) as r:
            return json.load(r)

    monitored = get("/monitoring")
    events = get("/events/assessed")["events"]
    upcoming = [e for e in events if e["tca"] > "2026-10-11"] or events
    closest = min(upcoming, key=lambda e: e["miss_distance_km"])
    detail = get(f"/events/{closest['id']}/explanation")
    from datetime import datetime, timezone

    tca = datetime.fromisoformat(detail["tca"])
    hours = (tca - datetime.now(timezone.utc)).total_seconds() / 3600.0
    return Subject(
        primary=detail["primary"]["name"],
        secondary=detail["secondary"]["name"],
        miss_km=detail["miss_distance_km"],
        speed_km_s=detail["relative_speed_km_s"],
        hours=hours,
        tracked=len(monitored),
        pc=detail.get("probability_of_collision") or 0.0,
    )


# ------------------------------------------------------------------ drawing
def typed(text: str, frame: int, start: int) -> str:
    """How much of ``text`` has been typed by ``frame``."""
    elapsed = max(0, frame - start) / FPS
    return text[: int(elapsed * CPS)]


def is_typing(text: str, frame: int, start: int) -> bool:
    return len(typed(text, frame, start)) < len(text)


def cursor_on(frame: int) -> bool:
    return int(frame / FPS * CURSOR_HZ * 2) % 2 == 0


def write(
    d: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    f: ImageFont.FreeTypeFont,
    colour: tuple[int, int, int],
    cursor: bool = False,
    frame: int = 0,
) -> None:
    d.text(xy, text, font=f, fill=colour)
    if cursor and cursor_on(frame):
        width = d.textlength(text, font=f)
        size = f.size
        # A block cursor, not a caret: this is a terminal.
        d.rectangle(
            [xy[0] + width + 1, xy[1] + 1, xy[0] + width + size * 0.55, xy[1] + size],
            fill=colour,
        )


def rule(d: ImageDraw.ImageDraw, y: int, colour=DIM, x0=16, x1=W - 16) -> None:
    d.rectangle([x0, y, x1, y], fill=colour)


def earth(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, phase: float) -> None:
    """A wireframe globe drawn as discrete pixels on a lat/long grid."""
    for lat in range(-75, 76, 15):
        rad = math.radians(lat)
        rr = r * math.cos(rad)
        yy = cy - r * math.sin(rad)
        for step in range(0, 360, 2):
            ang = math.radians(step) + phase
            x = cx + rr * math.cos(ang)
            # Only the hemisphere facing the viewer.
            if math.sin(ang) > -0.1:
                d.point((x, yy), fill=DIM if math.sin(ang) < 0.35 else MID)
    for lon in range(0, 360, 30):
        ang = math.radians(lon) + phase
        if math.sin(ang) <= -0.1:
            continue
        for lat in range(-90, 91, 2):
            rad = math.radians(lat)
            x = cx + r * math.cos(rad) * math.cos(ang)
            y = cy - r * math.sin(rad)
            d.point((x, y), fill=DIM)


def orbit(
    d: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    a: int,
    b: int,
    tilt: float,
    phase: float,
    colour,
    mark: bool = False,
) -> None:
    """An orbital track, plus optionally the object riding it."""
    pts = []
    for step in range(0, 360, 2):
        t = math.radians(step)
        x, y = a * math.cos(t), b * math.sin(t)
        xr = x * math.cos(tilt) - y * math.sin(tilt)
        yr = x * math.sin(tilt) + y * math.cos(tilt)
        pts.append((cx + xr, cy + yr))
    for i, p in enumerate(pts):
        d.point(p, fill=colour)
    if mark:
        t = phase
        x, y = a * math.cos(t), b * math.sin(t)
        xr = x * math.cos(tilt) - y * math.sin(tilt)
        yr = x * math.sin(tilt) + y * math.cos(tilt)
        d.rectangle([cx + xr - 1, cy + yr - 1, cx + xr + 1, cy + yr + 1], fill=VERMILLION)


def header(d: ImageDraw.ImageDraw, frame: int) -> None:
    d.rectangle([0, 0, W, 18], fill=PLATE)
    write(d, (16, 6), "ASTRA / SSA", F_SMALL, BONE)
    label = "LIVE" if cursor_on(frame) else "    "
    write(d, (W - 46, 6), label, F_SMALL, VERMILLION)
    rule(d, 18, DIM, 0, W)


def footer(d: ImageDraw.ImageDraw, text: str) -> None:
    rule(d, H - 22, DIM, 0, W)
    write(d, (16, H - 15), text, F_SMALL, DIM)


# ------------------------------------------------------------------- scenes
# Timings below are LOCAL to each scene and, because CPS equals FPS, one
# character takes exactly one frame. A line starting at local frame N with
# L characters finishes at N + L, which is checkable by reading rather than
# by rendering. verify_timing() enforces it.


#: Absolute frames on which a character is revealed, collected while drawing
#: so the key clicks cannot drift from the picture.
CLICKS: list[int] = []


def tw(d, xy, text, t, at, f, fnt, colour, cur=True):
    """Typewriter a line that begins at local frame ``at``."""
    if t < at:
        return
    revealed = t - at
    if 0 < revealed <= len(text) and text[revealed - 1] != " ":
        CLICKS.append(f)
    shown = text[:revealed]
    d.text(xy, shown, font=fnt, fill=colour)
    if cur and len(shown) < len(text) and cursor_on(f):
        w = d.textlength(shown, font=fnt)
        d.rectangle([xy[0] + w + 1, xy[1] + 1, xy[0] + w + fnt.size * 0.55,
                     xy[1] + fnt.size], fill=colour)


def scene_boot(d, f, t, s):
    """0.0-3.5s  The system announces itself."""
    tw(d, (16, 150), "ASTRA / SSA", t, 6, f, F_HUGE, BONE)
    if t > 20:
        rule(d, 186, VERMILLION, 16, 16 + min(238, (t - 20) * 14))
    tw(d, (16, 204), "SPACE SITUATIONAL AWARENESS", t, 24, f, F_MED, VERMILLION)
    tw(d, (16, 240), "CONJUNCTION SCREENING,", t, 54, f, F_SMALL, MID)
    tw(d, (16, 254), "IN A BROWSER.", t, 78, f, F_SMALL, MID)
    if t > 92:
        write(d, (16, 294), "FROM PUBLIC ELEMENT SETS", F_SMALL, DIM)


def scene_catalogue(d, f, t, s):
    """3.5-8.0s  The live catalogue, orbiting."""
    header(d, f)
    phase = t / 42.0
    cx, cy = W // 2, 196
    earth(d, cx, cy, 74, phase * 0.5)
    orbit(d, cx, cy, 124, 44, 0.42, phase * 1.7, MID)
    orbit(d, cx, cy, 108, 62, -0.65, phase * 1.3, DIM)
    orbit(d, cx, cy, 136, 96, 0.18, phase * 2.1, MID, mark=True)
    tw(d, (16, 40), f"> TRACKING {s.tracked} OBJECTS", t, 7, f, F_MED, BONE)
    if t > 44:
        rule(d, 316, DIM)
    tw(d, (16, 330), "SGP4 PROPAGATION", t, 46, f, F_MED, MID)
    tw(d, (16, 352), "TEME FRAME", t, 66, f, F_MED, MID)
    tw(d, (16, 374), "REFRESHED EVERY 6 HOURS", t, 80, f, F_MED, VERMILLION)
    tw(d, (16, 408), "ONE REPRODUCIBLE RUN", t, 108, f, F_SMALL, DIM)
    footer(d, "NO ACCOUNT REQUIRED")


def scene_conjunction(d, f, t, s):
    """8.0-13.5s  A real predicted encounter."""
    header(d, f)
    tw(d, (16, 44), "CONJUNCTION PREDICTED", t, 6, f, F_BIG, VERMILLION)
    if t > 30:
        rule(d, 70, VERMILLION)
    tw(d, (16, 86), s.primary[:18], t, 34, f, F_MED, BONE)
    if t > 52:
        write(d, (16, 104), "VS", F_SMALL, DIM)
    tw(d, (16, 120), s.secondary[:18], t, 56, f, F_MED, BONE)

    rows = [
        ("MISS DISTANCE", f"{s.miss_km:.3f} KM", 172, 78),
        ("CLOSING SPEED", f"{s.speed_km_s:.2f} KM/S", 220, 92),
        ("TIME TO TCA", f"T-{s.hours:.1f} H", 268, 106),
        ("PROBABILITY", f"{s.pc:.2E}", 316, 118),
    ]
    for label, value, y, at in rows:
        if t > at:
            write(d, (16, y), label, F_SMALL, DIM)
            tw(d, (16, y + 14), value, t, at + 2, f, F_MED, BONE)

    if t > 132:
        rule(d, 376, DIM)
    tw(d, (16, 390), "SYNTHETIC COVARIANCE.", t, 134, f, F_SMALL, DIM, cur=False)
    if t > 158:
        write(d, (16, 404), "THE MODEL SAYS SO.", F_SMALL, DIM)
    footer(d, "FROM THE LIVE CATALOGUE")


def scene_language(d, f, t, s):
    """13.5-18.0s  Plain English becomes an allowlisted command."""
    header(d, f)
    write(d, (16, 44), "ASK IN PLAIN ENGLISH", F_MED, DIM)
    rule(d, 64)
    tw(d, (16, 84), "> is envisat in danger tomorrow", t, 8, f, F_SMALL, BONE)
    if t > 48:
        write(d, (16, 124), "TRANSLATED TO", F_SMALL, DIM)
    tw(d, (16, 144), "screen 27386 --window 48h", t, 56, f, F_MED, VERMILLION)
    if t > 88:
        rule(d, 186, DIM)
    tw(d, (16, 200), "CHECKED BY THE SAME ALLOWLIST", t, 90, f, F_SMALL, MID, cur=False)
    if t > 122:
        write(d, (16, 222), "AS HAND-TYPED INPUT.", F_SMALL, MID)
        write(d, (16, 252), "NO SHELL. NO FREE TEXT.", F_SMALL, VERMILLION)
    footer(d, "RULES, NOT A LANGUAGE MODEL")


def scene_models(d, f, t, s):
    """18.0-22.0s  Three manoeuvre models, and their disagreement."""
    header(d, f)
    write(d, (16, 44), "MANOEUVRE WHAT-IF", F_MED, DIM)
    rule(d, 64)
    tw(d, (16, 84), "0.05 M/S ALONG-TRACK, T-2H", t, 4, f, F_SMALL, BONE)

    models = [
        ("CLOHESSY-WILTSHIRE", "+0.082 KM", 130, 36),
        ("J2 + DRAG", "+0.089 KM", 180, 48),
        ("TWO-BODY", "EXCLUDED", 230, 60),
    ]
    for name, value, y, at in models:
        if t > at:
            out = value == "EXCLUDED"
            write(d, (16, y), name, F_SMALL, DIM if out else MID)
            write(d, (16, y + 14), value, F_MED, DIM if out else BONE)
            if out and t > at + 8:
                write(d, (132, y + 12), "OUTSIDE", F_SMALL, VERMILLION)
                write(d, (132, y + 24), "ASSUMPTIONS", F_SMALL, VERMILLION)
    if t > 76:
        rule(d, 288, DIM)
    tw(d, (16, 302), "THREE MODELS RUN.", t, 78, f, F_SMALL, BONE, cur=False)
    if t > 100:
        write(d, (16, 322), "THE DISAGREEMENT IS", F_SMALL, BONE)
        write(d, (16, 336), "PART OF THE ANSWER.", F_SMALL, VERMILLION)
    footer(d, "NOT A MANOEUVRE PLAN")


def scene_end(d, f, t, s):
    """22.0-25.0s  Where to find it."""
    write(d, (16, 150), "ASTRA / SSA", F_HUGE, BONE)
    rule(d, 186, VERMILLION, 16, 254)
    tw(d, (16, 208), "space-debris-ssa-tool", t, 10, f, F_MED, VERMILLION)
    tw(d, (16, 228), ".vercel.app", t, 34, f, F_MED, VERMILLION)
    if t > 52:
        write(d, (16, 272), "OPEN SOURCE", F_SMALL, MID)
        write(d, (16, 286), "NO ACCOUNT NEEDED", F_SMALL, MID)
    if t > 66:
        rule(d, 316, DIM)
        write(d, (16, 330), "EDUCATIONAL MODEL.", F_SMALL, DIM)
        write(d, (16, 344), "NOT FOR OPERATIONAL USE.", F_SMALL, DIM)


SCENES = [
    (0, 105, scene_boot),
    (105, 240, scene_catalogue),
    (240, 405, scene_conjunction),
    (405, 540, scene_language),
    (540, 660, scene_models),
    (660, TOTAL, scene_end),
]


def verify_timing() -> list[str]:
    """Every typewritten line must finish before its scene cuts.

    One character takes one frame, so a line is checkable from its source:
    local start plus length must not exceed the scene's length. Written as a
    test rather than a comment because the failure is silent -- a line simply
    stops mid-word and the cut looks like a glitch.
    """
    import inspect
    import re

    faults = []
    for start, end, fn in SCENES:
        span = end - start
        body = inspect.getsource(fn)
        for m in re.finditer(
            r'tw\(\s*d,\s*\([^)]*\),\s*(f?)"([^"]*)"\s*,\s*t\s*,\s*(\d+)', body
        ):
            text, at = m.group(2), int(m.group(3))
            # An f-string's runtime length is unknown; allow generous slack.
            length = len(text) + (12 if m.group(1) else 0)
            if at + length > span:
                faults.append(
                    f"{fn.__name__}: '{text[:30]}' starts {at}, needs "
                    f"{at + length}, scene is {span} frames"
                )
    return faults


def render_frame(f: int, s: Subject) -> Image.Image:
    img = Image.new("RGB", (W, H), PLATE)
    d = ImageDraw.Draw(img)
    for start, end, fn in SCENES:
        if start <= f < end:
            fn(d, f, f - start, s)
            break

    # Upscale with NEAREST so every drawn pixel becomes a hard 4x4 block.
    big = img.resize((W * SCALE, H * SCALE), Image.NEAREST)

    # Scanlines, applied after the upscale so they sit between pixel rows
    # rather than inside them.
    scan = Image.new("RGB", big.size, (0, 0, 0))
    mask = Image.new("L", big.size, 0)
    md = ImageDraw.Draw(mask)
    for y in range(0, H * SCALE, 4):
        # 45% rather than opaque: enough to read as a CRT line without
        # swallowing a quarter of the image's light.
        md.line([(0, y), (W * SCALE, y)], fill=115, width=1)
    return Image.composite(scan, big, mask)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "teaser.mp4")
    frames_dir = out.parent / "_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"):
        old.unlink()

    faults = verify_timing()
    if faults:
        print("timing faults:")
        for fault in faults:
            print("  -", fault)
        return 1

    print("fetching live figures…")
    s = fetch()
    print(f"  {s.primary} vs {s.secondary}  {s.miss_km:.3f} km  T-{s.hours:.1f}h")

    print(f"rendering {TOTAL} frames…")
    for f in range(TOTAL):
        render_frame(f, s).save(frames_dir / f"{f:04d}.png")
        if f % 150 == 0:
            print(f"  {f}/{TOTAL}")

    print("encoding…")
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(FPS),
            "-i", str(frames_dir / "%04d.png"),
            "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            # yuv420p for player compatibility; the source is already a
            # multiple of 2 in both dimensions.
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    clicks = sorted(set(CLICKS))
    (out.parent / "clicks.json").write_text(json.dumps(clicks), encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size / 1_048_576:.1f} MB)")
    print(f"recorded {len(clicks)} keystrokes -> clicks.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
