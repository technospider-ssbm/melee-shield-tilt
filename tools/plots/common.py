"""Shared constants and loaders for the shield-tilt plots.

Static-chart marks use an Okabe-Ito colour-blind-safe subset (technospider,
2026-09-23): sky blue, orange, bluish green and charcoal - never red or
green. Chart chrome (surfaces/ink/gridlines) stays on the dataviz-skill
neutral tokens. make_explorer.py is intentionally on its own palette and
is not touched by this module's constants.
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

# Okabe-Ito colour-blind-safe subset - the only hues used on any static mark.
SKY_BLUE = "#56B4E9"      # partial-tilt rings, extreme-tilt/body-grid bubbles
ORANGE = "#E69F00"        # min-size bubble, forward-hysteresis diamond/dash
BLUISH_GREEN = "#009E73"  # untilted bubble + its centre marker
CHARCOAL = "#333333"      # full-tilt centre path (thick, white halo)

# Back-compat aliases (still referenced as ACCENT/PATH_NAVY around the code).
ACCENT = SKY_BLUE
PATH_NAVY = CHARCOAL
STATUS_GOOD = "#0ca30c"  # reserved status color (unused on charts; kept for parity)

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

# --- reachable-stick geometry (technospider, 2026-09-24) ------------------
# The control stick is clamped to radius 80 then each axis is dead-zoned:
# |raw component| <= 22 snaps to 0. The smallest surviving raw component is
# 23, i.e. 23/80 of full tilt - the threshold below is exactly that ratio.
# Only angles exactly on an axis (0/90/180/270, or the forward 360 twin) or
# strictly between ~16.84 deg and ~73.16 deg within a quadrant are holdable;
# see docs/MECHANICS.md and data/<code>.csv `grid` rows (the game's own
# discretisation) for the full derivation.
HOLD_THRESH = 23.0 / 80.0  # 0.2875
EDGE_GAP_DEG = 3.0  # grid angle-gap that marks a dead-zone snap band


def char_meta(code):
    return json.loads((DATA / f"{code}_meta.json").read_text())


def all_codes():
    d = json.loads((DATA / "characters.json").read_text())
    return sorted(d.keys())


def holdable_mask(m, angles_deg, thresh=HOLD_THRESH, zero_eps=1e-6):
    """True where a stick at strength m and angle theta is actually
    holdable: |m*cos(theta)| and |m*sin(theta)| are each either ~0 (dead
    zone snaps that axis to exactly 0) or >= thresh (clears the dead zone)."""
    theta = np.radians(np.asarray(angles_deg, dtype=float))
    cx = np.abs(m * np.cos(theta))
    cy = np.abs(m * np.sin(theta))
    ok = lambda v: (v < zero_eps) | (v >= thresh - 1e-9)
    return ok(cx) & ok(cy)


def _contiguous_index_runs(idx):
    """Group a sorted 1-D array of integer positions into (start, end)
    inclusive runs of consecutive integers."""
    idx = np.asarray(idx)
    if len(idx) == 0:
        return []
    runs = []
    start = prev = idx[0]
    for i in idx[1:]:
        if i != prev + 1:
            runs.append((start, prev))
            start = i
        prev = i
    runs.append((start, prev))
    return runs


def holdable_ring_segments(ring_df, m, min_len=2):
    """Split a dense, uniformly-spaced polar ring (one character, one
    magnitude m) into the line stretches that are actually holdable.
    Returns a list of DataFrames (angle-sorted, ring_df's own index order
    preserved) - single-sample axis points are dropped by default since the
    ring is already dense enough that a lone True sample isn't worth a mark."""
    ring_df = ring_df.sort_values("angle").reset_index(drop=True)
    mask = holdable_mask(m, ring_df.angle.values)
    runs = _contiguous_index_runs(np.where(mask)[0])
    return [ring_df.iloc[s:e + 1] for s, e in runs if (e - s + 1) >= min_len]


def reachable_grid_edge(grid_df, gap_deg=EDGE_GAP_DEG):
    """From a character's `grid` rows (the game's actual stick
    discretisation), keep the largest-magnitude row per unique settled
    angle, sorted by angle - this is the true reachable boundary. Split it
    into continuous stretches (consecutive angles <= gap_deg apart, drawn as
    a path) and isolated single-angle points (the axis snaps, including the
    forward 0/360 hysteresis twin), drawn as dots with a gap either side.

    Returns (edge, segments, isolated):
      edge       - the full max-mag-per-angle frame, angle-sorted (used for
                   the reach-area polygon, which bridges the snap gaps with
                   a straight edge rather than pretending they're reachable)
      segments   - list of DataFrames, each a holdable stretch (len >= 2)
      isolated   - DataFrame of the single-angle axis points
    """
    idx = grid_df.groupby("angle")["mag"].idxmax()
    edge = grid_df.loc[idx].sort_values("angle").reset_index(drop=True)
    diffs = np.diff(edge.angle.values)
    breaks = np.where(diffs > gap_deg)[0]
    bounds = list(breaks) + [len(edge) - 1]
    segments, isolated_rows = [], []
    start = 0
    for b in bounds:
        if b > start:
            segments.append(edge.iloc[start:b + 1])
        else:
            isolated_rows.append(edge.iloc[start])
        start = b + 1
    isolated = (pd.DataFrame(isolated_rows).reset_index(drop=True)
                if isolated_rows else edge.iloc[0:0])
    return edge, segments, isolated


def grid_row_at_angle(df, angle, atol=1e-2):
    """The largest-magnitude grid (or edge) row at (numerically) this exact
    settled angle, e.g. one of the 8 cardinal/diagonal stick extremes."""
    sub = df[np.isclose(df.angle, angle, atol=atol)]
    if sub.empty:
        return None
    return sub.iloc[int(sub.mag.values.argmax())]


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
