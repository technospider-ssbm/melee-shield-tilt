"""Shared constants and loaders for the shield-tilt plots.

Palette and mark conventions follow the project's dataviz skill
(references/palette.md): categorical slot 1 (blue) as the single accent hue
for "reachable region" geometry, chart-chrome ink/gridline roles for
everything else.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
PLOTS = REPO / "plots"
PLOTS.mkdir(exist_ok=True)

# --- palette (references/palette.md) ---------------------------------
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
BORDER = "rgba(11,11,11,0.10)"

ACCENT = "#2a78d6"       # categorical slot 1 (blue) - reachable-region geometry
ACCENT_SEQ = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95"]  # light->dark
ORANGE = "#eb6834"       # categorical slot 2 - used only for the min-shield ring
STATUS_GOOD = "#0ca30c"  # reserved status color (unused on charts; kept for parity)
# High-contrast path colour for the "where the shield can go" panel - darker
# than ACCENT so it survives a white halo (path_effects) over any fill.
PATH_NAVY = "#0d2b52"

# All 26 selectable characters (everyone but Nana, whose pose is identical to
# Popo's) now match the emulator exactly - see data/validation/PROGRESS.md
# and commit 75f3ac7. One line, once per chart, rather than a per-panel tag.
VALIDATION_NOTE = ("All characters validated against Dolphin (vanilla NTSC "
                    "1.02), max error < 1e-5 units.")
# Nana isn't independently selectable/validated (no 1v1 slot for her alone);
# her pose is identical to Popo's, which is one of the validated 26.
NANA_VALIDATION_NOTE = ("Nana's pose is identical to Popo's (not independently "
                         "selectable in-game); Popo is validated against "
                         "Dolphin (vanilla NTSC 1.02), max error < 1e-5 units.")

# 8 cardinal/diagonal stick directions, angle=0 is forward (+x), 90 is up.
DIRECTIONS = [
    (0, "Forward"), (45, "Fwd+Up"), (90, "Up"), (135, "Back+Up"),
    (180, "Back"), (225, "Back+Down"), (270, "Down"), (315, "Fwd+Down"),
]

# A grid/polar stick at exactly 0deg (straight forward) settles to one of two
# history-dependent poses (frame 10 = angle 0, or frame 370 = angle 360;
# docs/MECHANICS.md 1.2). Below this 3D game-unit gap between the two we
# treat them as the same point and don't clutter the chart.
HYSTERESIS_EPS = 0.05

FONT = "system-ui, -apple-system, Segoe UI, sans-serif"


def char_meta(code):
    return json.loads((DATA / f"{code}_meta.json").read_text())


def all_codes():
    d = json.loads((DATA / "characters.json").read_text())
    return sorted(d.keys())


def display_name(code, meta=None):
    meta = meta or char_meta(code)
    return meta["name"]


def load_main(code):
    df = pd.read_csv(DATA / f"{code}.csv")
    return df


def load_hurtbox_poses(code, angles=(0, 45, 90, 135, 180, 225, 270, 315)):
    """Return {pose_label: DataFrame(hurtbox rows)} for untilted + each
    full-magnitude cardinal/diagonal extreme, taken from the polar sweep
    (exact angle/mag=1 samples, no nearest-match needed). Missing rows (e.g.
    a character's hurtbox export predates the angle=360 rows added in
    commit 75f3ac7) are silently skipped rather than guessed at."""
    path = DATA / f"{code}_hurtboxes.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    poses = {}
    untilted = df[(df.sweep == "polar") & (df.mag == 0)]
    if untilted.empty:
        untilted = df[(df.sweep == "grid") & (df.stick_x == 0) & (df.stick_y == 0)]
    # one representative angle row-set for mag=0 (all angles identical there)
    if not untilted.empty:
        a0 = untilted.angle.iloc[0]
        poses["untilted"] = untilted[untilted.angle == a0]
    full = df[(df.sweep == "polar") & (df.mag == 1.0)]
    for ang in angles:
        label = dict(DIRECTIONS).get(ang, f"angle={ang}")
        sub = full[full.angle == ang]
        if not sub.empty:
            poses[label] = sub
    return poses
