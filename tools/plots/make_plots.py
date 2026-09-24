#!/usr/bin/env python
"""Build all shield-tilt plots (Phase 5).

Run with the project venv:
    .venv/Scripts/python.exe tools/plots/make_plots.py

Outputs (see plots/):
  - <code>.png / <code>.svg   per-character side view
  - all_characters.png        shared-axis comparison grid
  - reach_summary.png / .svg  bar chart of reach extents
  - data/reach_summary.csv    the underlying table
  - shield_tilt_explorer.html interactive plotly picker (optional extra)
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Polygon, Patch
from matplotlib import font_manager

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import (
    REPO, DATA, PLOTS, SURFACE, PAGE, INK_PRIMARY, INK_SECONDARY, INK_MUTED,
    GRIDLINE, BASELINE, ACCENT, SKY_BLUE, ORANGE, BLUISH_GREEN, CHARCOAL,
    STATUS_GOOD, PATH_NAVY, VALIDATION_NOTE, NANA_VALIDATION_NOTE,
    HYSTERESIS_EPS, DIRECTIONS, FONT, all_codes, char_meta, display_name,
    load_main, load_hurtbox_poses, HOLD_THRESH, EDGE_GAP_DEG,
    holdable_ring_segments, reachable_grid_edge, grid_row_at_angle,
)

# faint "out of reach" ring: the continuous polar mag=1 sweep, most of which
# the dead zone actually snaps onto an axis before the player can hold it.
OUT_OF_REACH_LABEL = "out of reach: stick snaps onto the axis"

# partial-tilt rings (m=0.25/0.5/0.75): one hue (sky blue), increasing
# opacity with magnitude rather than a light->dark ramp of different blues
RING_ALPHAS = (0.35, 0.55, 0.85)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK_SECONDARY,
    "text.color": INK_PRIMARY,
    "xtick.color": INK_MUTED,
    "ytick.color": INK_MUTED,
    "figure.facecolor": PAGE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": PAGE,
})


def stadium_polygon(x1, y1, x2, y2, r, n=20):
    """2D stadium (capsule) polygon for a capsule from (x1,y1) to (x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    length = np.hypot(dx, dy)
    if length < 1e-9:
        ang0 = 0.0
    else:
        ang0 = np.arctan2(dy, dx)
    t = np.linspace(0, np.pi, n)
    # semicircle at end 2 (facing +ang0 direction), then end 1 (facing -ang0)
    arc2 = np.stack([x2 + r * np.cos(ang0 - np.pi / 2 + t),
                      y2 + r * np.sin(ang0 - np.pi / 2 + t)], axis=1)
    arc1 = np.stack([x1 + r * np.cos(ang0 + np.pi / 2 + t),
                      y1 + r * np.sin(ang0 + np.pi / 2 + t)], axis=1)
    return np.concatenate([arc2, arc1], axis=0)


def draw_hurtboxes(ax, df, color, alpha, lw=0.6, zorder=2, edgecolor=None,
                    edge_alpha=None, edge_only=False):
    """edge_alpha defaults to alpha; pass a higher value for a visible thin
    outline over a very light fill (e.g. the untilted-pose body).
    edge_only=True draws no fill at all (a silhouette outline)."""
    face_rgba = "none" if edge_only else mcolors.to_rgba(color, alpha)
    edge_rgba = mcolors.to_rgba(edgecolor or color,
                                 edge_alpha if edge_alpha is not None else alpha)
    for _, row in df.iterrows():
        poly = stadium_polygon(row.x1, row.y1, row.x2, row.y2, row.radius)
        ax.add_patch(Polygon(poly, closed=True, facecolor=face_rgba,
                              edgecolor=edge_rgba, linewidth=lw, zorder=zorder))


def char_geometry(code):
    """Compute the reusable geometry (rings, extremes, extents) for a character."""
    df = load_main(code)
    meta = char_meta(code)
    r_full = float(df.shield_radius_full.iloc[0])
    r_min = float(df.shield_radius_min.iloc[0])

    polar = df[df.sweep == "polar"].copy()
    untilted = df[(df.sweep == "polar") & (df.mag == 0)].iloc[0]
    ux, uy = untilted.bone_x, untilted.bone_y

    # angle now runs 0..360 inclusive (commit 75f3ac7): a stick at exactly
    # 0deg has two history-dependent settled poses (frame 10 = angle 0,
    # frame 370 = angle 360). Sorting ascending and NOT wrapping 360 back to
    # 0 means the full-tilt ring closes through the real angle=360 sample
    # (matplotlib's fill()/plot() already connects last->first automatically,
    # so if the two differ this draws the true cusp instead of a fake wrap).
    # Out-of-reach reference: the continuous polar mag=1 sweep. Kept only as
    # a faint backdrop now - the dead zone snaps most of these onto an axis
    # before a player can actually hold them (see reachable_edge below).
    ring_full = polar[np.isclose(polar.mag, 1.0)].sort_values("angle")
    rings_inner = {
        m: polar[np.isclose(polar.mag, m)].sort_values("angle")
        for m in (0.25, 0.5, 0.75)
    }
    # Holdable stretches of each partial-tilt ring (dense synthetic samples,
    # so a straight holdable_mask split is enough - no grid lookup needed).
    rings_inner_holdable = {
        m: holdable_ring_segments(rings_inner[m], m) for m in (0.25, 0.5, 0.75)
    }

    grid = df[df.sweep == "grid"]

    # Reachable edge: the game's own discretisation (`grid` rows), largest
    # magnitude per settled angle, split into holdable stretches (charcoal
    # path) and isolated axis snaps (dots) more than EDGE_GAP_DEG apart.
    edge, edge_segments, edge_isolated = reachable_grid_edge(grid, ux, uy)

    # 8 cardinal/diagonal extremes and the untilted/forward-hysteresis pair
    # now come from the grid's real max-mag row at each angle (holdable
    # strength is 0.95-1.0 near the rim, not exactly 1) rather than the
    # unreachable polar mag=1 ring.
    extremes = {}
    for ang, label in DIRECTIONS:
        row = grid_row_at_angle(edge, ang)
        if row is not None:
            extremes[label] = (float(row.bone_x), float(row.bone_y))

    # forward (angle 0) hysteresis: compare the frame-10 and frame-370 poses
    # in full 3D (bone_z included) even though the chart only plots x/y.
    fwd_alt = None
    r0 = grid_row_at_angle(edge, 0)
    r360 = grid_row_at_angle(edge, 360)
    if r0 is not None and r360 is not None:
        d = float(np.sqrt((r0.bone_x - r360.bone_x) ** 2 +
                           (r0.bone_y - r360.bone_y) ** 2 +
                           (r0.bone_z - r360.bone_z) ** 2))
        if d > HYSTERESIS_EPS:
            fwd_alt = (float(r360.bone_x), float(r360.bone_y), d)

    all_x = np.concatenate([grid.bone_x.values, ring_full.bone_x.values])
    all_y = np.concatenate([grid.bone_y.values, ring_full.bone_y.values])

    xlo, xhi = float(all_x.min() - r_full), float(all_x.max() + r_full)
    ylo, yhi = float(all_y.min() - r_full), float(all_y.max() + r_full)

    # extend the view to fit the (untilted) body, which can be wider/taller
    # than the shield bubble itself (e.g. Yoshi's tail, DK's arms)
    poses = load_hurtbox_poses(code, angles=())
    body = poses.get("untilted")
    if body is not None and not body.empty:
        bx = np.concatenate([body.x1.values, body.x2.values])
        by = np.concatenate([body.y1.values, body.y2.values])
        r = np.concatenate([body.radius.values, body.radius.values])
        xlo = min(xlo, float((bx - r).min())); xhi = max(xhi, float((bx + r).max()))
        ylo = min(ylo, float((by - r).min())); yhi = max(yhi, float((by + r).max()))

    has_tilt = meta.get("has_tilt", True)
    # Reach extents come from the grid (holdable) rows only, not the
    # out-of-reach polar ring - a chart must not claim a reach the dead
    # zone doesn't actually let a player hold.
    return dict(
        code=code, meta=meta, r_full=r_full, r_min=r_min, has_tilt=has_tilt,
        ux=ux, uy=uy, ring_full=ring_full, rings_inner=rings_inner,
        rings_inner_holdable=rings_inner_holdable,
        edge=edge, edge_segments=edge_segments, edge_isolated=edge_isolated,
        extremes=extremes, fwd_alt=fwd_alt, all_x=all_x, all_y=all_y,
        max_up=float(grid.bone_y.max() - uy), max_down=float(uy - grid.bone_y.min()),
        max_fwd=float(grid.bone_x.max() - ux), max_back=float(ux - grid.bone_x.min()),
        x_reach=(xlo, xhi), y_reach=(ylo, yhi),
    )


def draw_reach_layers(ax, geo, path_lw=1.8, halo=False, ring_lw=1.0,
                       out_lw=0.7, dot_ms=None, region_alpha=0.08, z0=5):
    """The shared reachable/out-of-reach geometry: a faint fill + dotted
    grey ring for the unreachable polar sweep, holdable stretches of the
    m=0.25/0.5/0.75 rings, and the true full-tilt reachable edge (grid-based,
    gapped at the dead-zone snap bands, dots at the isolated axis angles).
    Used by both the per-character left panel (thicker, haloed) and the
    all_characters.png small multiples (thinner, no halo)."""
    edge, segments, isolated = geo["edge"], geo["edge_segments"], geo["edge_isolated"]
    rf = geo["ring_full"]

    # region fill under the *real* reachable boundary (not the unreachable
    # polar ring - filling that would visually overstate the reach)
    ax.fill(edge.bone_x, edge.bone_y, color=SKY_BLUE, alpha=region_alpha, zorder=z0)

    # out-of-reach backdrop: thin dotted muted grey, never the same style as
    # the real path so it can't be mistaken for a holdable boundary
    ax.plot(rf.bone_x, rf.bone_y, color=INK_MUTED, lw=out_lw,
            ls=(0, (1, 1.6)), alpha=0.55, zorder=z0 + 1, label=OUT_OF_REACH_LABEL)

    # holdable stretches of the partial-tilt rings only (gaps elsewhere)
    for i, m in enumerate((0.25, 0.5, 0.75)):
        for seg in geo["rings_inner_holdable"][m]:
            ax.plot(seg.bone_x, seg.bone_y, color=SKY_BLUE, lw=ring_lw,
                    alpha=RING_ALPHAS[i], zorder=z0 + 2)

    # full-tilt reachable edge: thick charcoal, gapped at each snap band
    path_kwargs = dict(color=CHARCOAL, lw=path_lw, zorder=z0 + 3,
                        solid_capstyle="round")
    if halo:
        path_kwargs["path_effects"] = [
            pe.Stroke(linewidth=path_lw + 2.0, foreground=SURFACE), pe.Normal()]
    for i, seg in enumerate(segments):
        ax.plot(seg.bone_x, seg.bone_y,
                label=("full tilt, holdable (m=1)" if i == 0 else None),
                **path_kwargs)
    if not isolated.empty:
        ax.plot(isolated.bone_x, isolated.bone_y, linestyle="none", marker="o",
                ms=(dot_ms if dot_ms is not None else path_lw * 2.4),
                mfc=CHARCOAL, mec=SURFACE, mew=0.6, zorder=z0 + 4)


def plot_character(geo, ax=None, show_hurtboxes=True, show_labels=True,
                    lim=None, title=True):
    code, meta = geo["code"], geo["meta"]
    standalone = ax is None
    if standalone:
        fig, ax = plt.subplots(figsize=(7, 7), dpi=150)
    else:
        fig = ax.figure

    ux, uy, r_full, r_min = geo["ux"], geo["uy"], geo["r_full"], geo["r_min"]

    # Draw order (back to front): untilted hurtboxes -> extreme-tilt
    # hurtboxes -> bubbles -> centre path/rings/markers/labels. Hurtboxes
    # used to be opaque and on top, hiding the path entirely (e.g. Dk.png).

    # 1. untilted hurtboxes: light fill, thin mid-grey outline, at the back
    if show_hurtboxes:
        poses = load_hurtbox_poses(code, angles=() if not geo["has_tilt"] else
                                    (0, 45, 90, 135, 180, 225, 270, 315))
        body = poses.get("untilted")
        if body is not None:
            draw_hurtboxes(ax, body, INK_SECONDARY, alpha=0.2, lw=0.6, zorder=1,
                            edgecolor=INK_MUTED, edge_alpha=0.7)

        # 2. extreme-tilt hurtboxes: very faint, still behind the bubbles/path
        for label, sub in poses.items():
            if label != "untilted":
                draw_hurtboxes(ax, sub, SKY_BLUE, alpha=0.08, lw=0.3, zorder=2)

    # 3. bubbles
    if geo["has_tilt"]:
        for label, (ex, ey) in geo["extremes"].items():
            ax.add_patch(Circle((ex, ey), r_full, fill=False, edgecolor=SKY_BLUE,
                                 lw=0.7, alpha=0.5, zorder=3))
    ax.add_patch(Circle((ux, uy), r_full, fill=False, edgecolor=BLUISH_GREEN,
                         lw=1.4, zorder=4))
    ax.add_patch(Circle((ux, uy), r_min, fill=False, edgecolor=ORANGE,
                         lw=1.0, ls=(0, (3, 2)), alpha=0.9, zorder=4,
                         label="min-size bubble"))

    # 4. centre path, partial rings, markers and labels - always on top.
    # Path is charcoal (with a white halo in the two-panel chart below) so
    # colour is never the only cue distinguishing it from the sky-blue rings.
    draw_reach_layers(ax, geo, path_lw=1.4, halo=False, ring_lw=0.8,
                       out_lw=0.5, dot_ms=2.5, region_alpha=0.06, z0=5)
    ax.plot([ux], [uy], marker="o", ms=4, color=BLUISH_GREEN, zorder=9)

    if geo["has_tilt"] and show_labels:
        for label, (ex, ey) in geo["extremes"].items():
            # place label just outside the bubble, along the radial direction
            dx, dy = ex - ux, ey - uy
            norm = np.hypot(dx, dy) or 1
            lx = ex + dx / norm * (r_full * 0.35 + 1.0)
            ly = ey + dy / norm * (r_full * 0.35 + 1.0)
            ax.text(lx, ly, label, fontsize=6.5, color=INK_MUTED, ha="center",
                    va="center", zorder=9)

    # forward hysteresis: draw the second (frame-370) resting point, a thin
    # connector back to the normal (frame-10) forward point, and a note
    if show_labels and geo["fwd_alt"] is not None:
        fx, fy, fd = geo["fwd_alt"]
        fwd0 = geo["extremes"].get("Forward")
        if fwd0 is not None:
            ax.plot([fwd0[0], fx], [fwd0[1], fy], color=ORANGE, lw=0.8,
                    alpha=0.7, zorder=8)
        ax.plot([fx], [fy], marker="D", ms=5, mfc=ORANGE, mec=ORANGE, zorder=9)
        # anchor the note in a fixed corner with a leader line, rather than a
        # fixed data-space offset - for small gaps (e.g. Link) the marker
        # sits right against the min-size ring and any nearby offset collides
        ax.annotate(
            f"forward, if swept in from below (frame 370):\n"
            f"centre at ({fx:.2f}, {fy:.2f})", xy=(fx, fy), xycoords="data",
            xytext=(0.99, 0.20), textcoords="axes fraction", fontsize=6.5,
            color=ORANGE, ha="right", va="center", zorder=9,
            arrowprops=dict(arrowstyle="-", color=ORANGE, lw=0.7, alpha=0.7,
                            shrinkA=0, shrinkB=3))

    ax.set_aspect("equal", adjustable="box")
    if lim is not None:
        ax.set_xlim(*lim[0]); ax.set_ylim(*lim[1])
    else:
        ax.set_xlim(*geo["x_reach"]); ax.set_ylim(*geo["y_reach"])
    ax.grid(True, color=GRIDLINE, lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    name = display_name(code, meta)
    fixed_tag = "  fixed bubble (no tilt)" if not meta.get("has_tilt", True) else ""
    if title:
        ax.set_title(f"{name}", fontsize=13, color=INK_PRIMARY, loc="left",
                     fontweight="bold")
        if fixed_tag:
            ax.text(0.99, 1.01, fixed_tag.strip(), transform=ax.transAxes,
                    ha="right", va="bottom", fontsize=8, color=INK_MUTED)
    else:
        ax.set_title(name, fontsize=9, color=INK_PRIMARY)
        if fixed_tag:
            # inside the panel (top-right corner), not below it - text placed
            # below a small subplot bleeds into the panel underneath once
            # tight_layout packs the grid tightly (see commit 75f3ac7 review)
            ax.text(0.97, 0.94, fixed_tag.strip(), transform=ax.transAxes,
                    ha="right", va="top", fontsize=6, color=INK_MUTED)

    if standalone:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        handles = [
            Line2D([0], [0], color=BLUISH_GREEN, lw=1.4, label="untilted bubble"),
            Line2D([0], [0], color=CHARCOAL, lw=1.8, marker="o", ms=4,
                   label="full-tilt reachable edge (holdable)"),
            Line2D([0], [0], color=SKY_BLUE, lw=1.0, label="partial tilt, holdable (m=0.25/0.5/0.75)"),
            Line2D([0], [0], color=INK_MUTED, lw=0.7, ls=(0, (1, 1.6)), label=OUT_OF_REACH_LABEL),
            Line2D([0], [0], color=ORANGE, lw=1.0, ls=(0, (3, 2)), label="min-size bubble"),
            Line2D([0], [0], color=SKY_BLUE, lw=0.7, alpha=0.6, label="bubble at stick extreme"),
            Patch(facecolor=INK_SECONDARY, edgecolor=INK_MUTED, alpha=0.35, label="hurtboxes (untilted)"),
        ]
        ax.legend(handles=handles, loc="lower right", fontsize=6.5, frameon=False,
                 labelcolor=INK_SECONDARY)
        ax.set_xlabel("forward →  (game units, relative to TopN)")
        ax.set_ylabel("up →")
        fig.text(0.01, 0.025,
                 "Shield-centre position from the offline pose solver (Phase 3); "
                 "faint rings/bubbles = stick extremes, hurtboxes shown in the "
                 "tilted pose.", fontsize=6.5, color=INK_MUTED)
        note = NANA_VALIDATION_NOTE if code == "Nn" else VALIDATION_NOTE
        fig.text(0.01, 0.005, note, fontsize=6.5, color=INK_MUTED)
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        return fig
    return None


# 3x3 compass layout for the "body at each extreme" panel: (row, col), row 0
# = top, col 0 = back (matches the "up = away from forward" reading of the
# stick that the left panel's direction labels already use).
COMPASS_CELLS = {
    "Back+Up": (0, 0), "Up": (0, 1), "Fwd+Up": (0, 2),
    "Back": (1, 0), "untilted": (1, 1), "Forward": (1, 2),
    "Back+Down": (2, 0), "Down": (2, 1), "Fwd+Down": (2, 2),
}


def _place_label(ax, renderer, xy, text, avoid_bboxes, near=None,
                  fontsize=6.3, color=ORANGE):
    """Place `text` anchored at data point `xy`, trying offset candidates
    (in points, growing radius) until one clears every bbox in
    avoid_bboxes (display/pixel coords, e.g. from get_window_extent).
    `near` is another data point (e.g. the other end of a connector) whose
    bearing is deprioritised, so two related end-labels don't grow toward
    each other. Falls back to the last-tried candidate if nothing is
    collision-free."""
    away = None
    if near is not None:
        x0, y0 = ax.transData.transform(xy)
        x1, y1 = ax.transData.transform(near)
        away = np.degrees(np.arctan2(y0 - y1, x0 - x1))

    candidates = [(r, ang) for r in (12, 20, 30, 42)
                  for ang in (0, 45, 90, 135, 180, 225, 270, 315)]
    if away is not None:
        def pref(c):
            r, ang = c
            d = abs(((ang - away + 180) % 360) - 180)  # 0 = toward `near`
            return (d < 100, r)
        candidates.sort(key=pref)

    def _try(r, ang):
        rad = np.radians(ang)
        dx, dy = r * np.cos(rad), r * np.sin(rad)
        ha = "left" if dx > 2 else ("right" if dx < -2 else "center")
        va = "bottom" if dy > 2 else ("top" if dy < -2 else "center")
        # a short leader line disambiguates which point the label belongs
        # to once it's nudged away to dodge a collision (e.g. Link, where
        # the two forward points are only 0.24 units apart)
        t = ax.annotate(text, xy=xy, xycoords="data", xytext=(dx, dy),
                         textcoords="offset points", fontsize=fontsize,
                         color=color, ha=ha, va=va, zorder=9,
                         arrowprops=dict(arrowstyle="-", color=color, lw=0.6,
                                         alpha=0.6, shrinkA=0, shrinkB=3))
        return t

    for r, ang in candidates:
        t = _try(r, ang)
        bbox = t.get_window_extent(renderer=renderer).expanded(1.05, 1.2)
        if not any(bbox.overlaps(b) for b in avoid_bboxes):
            return t
        t.remove()
    return _try(*candidates[-1])  # best effort


def draw_left_panel(ax, geo):
    """'Where the shield can go': the centre path, no per-pose hurtbox
    fills at all (those are what made Dk.png unreadable) - just a faint
    outline of the untilted body for scale."""
    code = geo["code"]
    ux, uy, r_full, r_min = geo["ux"], geo["uy"], geo["r_full"], geo["r_min"]

    # faint untilted body silhouette: outline only, no fill
    poses = load_hurtbox_poses(code, angles=())
    body = poses.get("untilted")
    if body is not None and not body.empty:
        draw_hurtboxes(ax, body, BASELINE, alpha=0, lw=0.5, zorder=1,
                        edgecolor=BASELINE, edge_alpha=0.7, edge_only=True)

    # out-of-reach polar ring (faint, dotted) + holdable partial rings (sky
    # blue, gapped at the dead-zone snap bands) + the true full-tilt
    # reachable edge (thick charcoal, white halo, gapped, dots on the
    # isolated axis snaps) - see draw_reach_layers for the full stack.
    draw_reach_layers(ax, geo, path_lw=2.5, halo=True, ring_lw=0.8,
                       out_lw=0.7, dot_ms=6, region_alpha=0.08, z0=3)

    # bubbles: untilted (black), min-size (dashed), 8 extremes (thin outline).
    # Skip the plain "Forward" text label when there's a forward-hysteresis
    # pair (DK/YL/Link) - the two short labels added below stand in for it,
    # at the same spot, so drawing both would just collide.
    direction_texts = []
    if geo["has_tilt"]:
        for label, (ex, ey) in geo["extremes"].items():
            ax.add_patch(Circle((ex, ey), r_full, fill=False, edgecolor=SKY_BLUE,
                                 lw=0.6, alpha=0.6, zorder=4))
            if label == "Forward" and geo["fwd_alt"] is not None:
                continue
            dx, dy = ex - ux, ey - uy
            norm = np.hypot(dx, dy) or 1
            lx = ex + dx / norm * (r_full * 0.35 + 1.0)
            ly = ey + dy / norm * (r_full * 0.35 + 1.0)
            t = ax.text(lx, ly, label, fontsize=6.5, color=INK_MUTED, ha="center",
                        va="center", zorder=7)
            direction_texts.append(t)
    ax.add_patch(Circle((ux, uy), r_full, fill=False, edgecolor=BLUISH_GREEN,
                         lw=1.4, zorder=5))
    ax.add_patch(Circle((ux, uy), r_min, fill=False, edgecolor=ORANGE,
                         lw=1.0, ls=(0, (3, 2)), alpha=0.9, zorder=5,
                         label="min-size bubble"))
    ax.plot([ux], [uy], marker="o", ms=4, color=BLUISH_GREEN, zorder=8)

    # axis limits/aspect must be final before we measure any text bounding
    # boxes below (they depend on the data->display transform)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(*geo["x_reach"]); ax.set_ylim(*geo["y_reach"])

    handles = [
        Line2D([0], [0], color=BLUISH_GREEN, lw=1.4, label="untilted bubble"),
        Line2D([0], [0], color=CHARCOAL, lw=2.5, marker="o", ms=5,
               label="full-tilt reachable edge (holdable, dots = axis snaps)"),
        Line2D([0], [0], color=SKY_BLUE, lw=1.0, label="partial tilt, holdable (m=0.25/0.5/0.75)"),
        Line2D([0], [0], color=INK_MUTED, lw=0.8, ls=(0, (1, 1.6)), label=OUT_OF_REACH_LABEL),
        Line2D([0], [0], color=ORANGE, lw=1.0, ls=(0, (3, 2)), label="min-size bubble"),
        Line2D([0], [0], color=SKY_BLUE, lw=0.6, alpha=0.6, label="bubble at stick extreme"),
        Line2D([0], [0], color=BASELINE, lw=0.5, label="untilted body outline"),
    ]
    if geo["fwd_alt"] is not None:
        handles.append(Line2D([0], [0], color=ORANGE, lw=1.2, ls="--",
                               label="forward: 2 resting points (depends on approach)"))
    legend = ax.legend(handles=handles, loc="lower right", fontsize=6.3,
                        frameon=False, labelcolor=INK_SECONDARY)

    # forward hysteresis (DK, Young Link, Link): dashed segment straight
    # between the two real forward samples (angle 0 / frame 10 and angle
    # 360 / frame 370), each end labelled and nudged to clear every other
    # label/legend already on the panel.
    if geo["fwd_alt"] is not None:
        fx, fy, fd = geo["fwd_alt"]
        fwd0 = geo["extremes"].get("Forward")
        ax.figure.canvas.draw()  # need real text/legend extents to avoid
        renderer = ax.figure.canvas.get_renderer()
        avoid = [t.get_window_extent(renderer=renderer).expanded(1.1, 1.3)
                 for t in direction_texts]
        avoid.append(legend.get_window_extent(renderer=renderer).expanded(1.05, 1.05))

        if fwd0 is not None:
            ax.plot([fwd0[0], fx], [fwd0[1], fy], color=ORANGE, lw=1.2,
                    ls="--", alpha=0.85, zorder=7)
            t0 = _place_label(ax, renderer, fwd0, "fwd: from above / fresh shield",
                               avoid, near=(fx, fy))
            if t0 is not None:
                avoid.append(t0.get_window_extent(renderer=renderer).expanded(1.05, 1.2))
        ax.plot([fx], [fy], marker="D", ms=5, mfc=ORANGE, mec=ORANGE, zorder=8)
        _place_label(ax, renderer, (fx, fy), "fwd: swept in from below",
                     avoid, near=fwd0 or (fx, fy))

    ax.grid(True, color=GRIDLINE, lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_title("Where the shield can go", fontsize=11, color=INK_PRIMARY,
                 loc="left")
    ax.set_xlabel("forward →  (game units, relative to TopN)")
    ax.set_ylabel("up →")


def draw_body_grid(fig, gs_cell, geo):
    """'Body at each extreme': a 3x3 small-multiples grid (compass layout),
    each cell showing that pose's tilted hurtboxes + bubble outline on
    shared limits."""
    code = geo["code"]
    r_full = geo["r_full"]
    inner_gs = gs_cell.subgridspec(3, 3, wspace=0.04, hspace=0.08)
    lim = (geo["x_reach"], geo["y_reach"])

    poses = load_hurtbox_poses(code, angles=() if not geo["has_tilt"] else
                                (0, 45, 90, 135, 180, 225, 270, 315))
    axes = {}
    for label, (row, col) in COMPASS_CELLS.items():
        ax = fig.add_subplot(inner_gs[row, col])
        axes[label] = ax
        if label == "untilted":
            centre = (geo["ux"], geo["uy"])
        elif geo["has_tilt"]:
            centre = geo["extremes"].get(label)
        else:
            centre = (geo["ux"], geo["uy"])  # fixed bubble: same everywhere

        sub = poses.get(label)
        if sub is not None and not sub.empty:
            draw_hurtboxes(ax, sub, INK_SECONDARY, alpha=0.3, lw=0.5, zorder=1,
                            edgecolor=INK_MUTED, edge_alpha=0.7)
        if centre is not None:
            ax.add_patch(Circle(centre, r_full, fill=False, edgecolor=SKY_BLUE,
                                 lw=1.0, zorder=2))
        ax.set_xlim(*lim[0]); ax.set_ylim(*lim[1])
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(GRIDLINE)
        title = "neutral" if label == "untilted" else label
        ax.text(0.03, 0.95, title, transform=ax.transAxes, fontsize=6.2,
                color=INK_MUTED, ha="left", va="top")
    return axes


def render_char_detail(geo):
    """Two panels, same axis limits: left = shield-centre reach, right =
    a 3x3 compass grid of the posed body/hurtboxes at each stick extreme.
    Keeps hurtboxes in the tilted pose without 8-way alpha stacking hiding
    the centre path (the original single-panel design's failure mode)."""
    code, meta = geo["code"], geo["meta"]
    fig = plt.figure(figsize=(13.5, 7.2), dpi=150)
    gs = fig.add_gridspec(1, 2, width_ratios=(1.3, 1), wspace=0.08)

    axL = fig.add_subplot(gs[0, 0])
    draw_left_panel(axL, geo)

    draw_body_grid(fig, gs[0, 1], geo)
    fig.text(gs[0, 1].get_position(fig).x0, 0.965, "Body at each extreme",
              fontsize=11, color=INK_PRIMARY)

    name = display_name(code, meta)
    fixed_tag = "  — fixed bubble (no tilt)" if not meta.get("has_tilt", True) else ""
    fig.suptitle(f"{name}{fixed_tag}", fontsize=15, color=INK_PRIMARY, x=0.01,
                 y=0.995, ha="left", va="top", fontweight="bold")

    fig.text(0.01, 0.028,
             "Shield-centre position from the offline pose solver (Phase 3); "
             "hurtboxes shown in the tilted pose (right).", fontsize=6.5,
             color=INK_MUTED)
    note = NANA_VALIDATION_NOTE if code == "Nn" else VALIDATION_NOTE
    fig.text(0.01, 0.008, note, fontsize=6.5, color=INK_MUTED)
    fig.tight_layout(rect=(0, 0.045, 1, 0.94))
    return fig


def make_per_character_plots(codes):
    for code in codes:
        geo = char_geometry(code)
        fig = render_char_detail(geo)
        fig.savefig(PLOTS / f"{code}.png", dpi=150)
        fig.savefig(PLOTS / f"{code}.svg")
        plt.close(fig)
        print(f"  {code}: {display_name(code, geo['meta'])} done")


def make_comparison_grid(codes):
    # Nana is a geometry/animation clone of Popo (data/Nn_meta.json notes
    # field is empty but the two csvs are identical in shape); drop her from
    # the shared-axis grid and cross-reference instead of duplicating a panel.
    codes = [c for c in codes if c != "Nn"]
    geos = {c: char_geometry(c) for c in codes}

    # shared axes across every character so size differences are honest
    xmin = min(g["x_reach"][0] for g in geos.values())
    xmax = max(g["x_reach"][1] for g in geos.values())
    ymin = min(g["y_reach"][0] for g in geos.values())
    ymax = max(g["y_reach"][1] for g in geos.values())
    lim = ((xmin, xmax), (ymin, ymax))

    n = len(codes)
    ncols = 6
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 2.6, nrows * 2.6), dpi=150)
    axes = np.atleast_2d(axes)
    order = sorted(codes, key=lambda c: display_name(c, geos[c]["meta"]))
    for i, code in enumerate(order):
        r, c = divmod(i, ncols)
        ax = axes[r][c]
        plot_character(geos[code], ax=ax, show_hurtboxes=False, show_labels=False,
                        lim=lim, title=False)
        ax.set_xticks([]); ax.set_yticks([])
    for i in range(n, nrows * ncols):
        r, c = divmod(i, ncols)
        axes[r][c].axis("off")

    fig.suptitle("Shield-centre reach by character (shared scale)", fontsize=15,
                 color=INK_PRIMARY, x=0.02, y=0.995, ha="left", va="top",
                 fontweight="bold")
    fig.text(0.02, 0.975,
             "Dark circle = untilted bubble; dark dotted line/dots = the reachable full-tilt "
             "edge (gaps mark dead-zone axis snaps); faint dotted ring = out of reach; "
             "faint rings = the 8 stick extremes. Nana matches Popo exactly and\n"
             "is omitted. Yoshi's shield does not tilt (fixed bubble). " + VALIDATION_NOTE,
             fontsize=8.5, color=INK_SECONDARY, va="top", linespacing=1.6)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(PLOTS / "all_characters.png", dpi=150)
    plt.close(fig)
    print("  all_characters.png done")


def make_reach_summary(codes):
    import csv
    codes = [c for c in codes if c != "Nn"]
    rows = []
    for code in codes:
        geo = char_geometry(code)
        # shoelace area of the *reachable* edge (grid max-mag-per-angle,
        # in angle order, including the isolated axis points) - the snap
        # gaps are bridged with a straight line same as the drawn polygon,
        # not the unreachable polar ring, so this can't overstate reach.
        edge = geo["edge"]
        x = edge.bone_x.values - geo["ux"]
        y = edge.bone_y.values - geo["uy"]
        area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        rows.append(dict(
            code=code, name=display_name(code, geo["meta"]),
            max_up=geo["max_up"], max_down=geo["max_down"],
            max_forward=geo["max_fwd"], max_back=geo["max_back"],
            centre_reach_area=area, shield_radius_full=geo["r_full"],
            has_tilt=geo["meta"].get("has_tilt", True),
            forward_hysteresis_gap=(geo["fwd_alt"][2] if geo["fwd_alt"] else 0.0),
        ))

    rows.sort(key=lambda r: r["centre_reach_area"], reverse=True)
    out_csv = DATA / "reach_summary.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {out_csv} done")

    # bar chart: max up/down/forward/back per character, sorted by reach area
    fig, ax = plt.subplots(figsize=(9, max(6, len(rows) * 0.32)), dpi=150)
    names = [r["name"] for r in rows]
    ypos = np.arange(len(rows))
    bar_h = 0.2
    # one hue per metric from the Okabe-Ito subset - no red or green
    metrics = [
        ("max_up", CHARCOAL, "up"),
        ("max_down", SKY_BLUE, "down"),
        ("max_forward", ORANGE, "forward"),
        ("max_back", BLUISH_GREEN, "back"),
    ]
    for i, (key, color, label) in enumerate(metrics):
        vals = [r[key] for r in rows]
        ax.barh(ypos + (i - 1.5) * bar_h, vals, height=bar_h, color=color,
                label=label, edgecolor=SURFACE, linewidth=0.5)
    ax.set_yticks(ypos)
    labels = []
    for r in rows:
        tag = "  (fixed)" if not r["has_tilt"] else ""
        labels.append(r["name"] + tag)
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("shield-centre shift from untilted (game units)")
    ax.set_title("Maximum shield-centre shift by direction, sorted by reachable area",
                 fontsize=13, loc="left", fontweight="bold", color=INK_PRIMARY)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5, ncols=4)
    ax.grid(True, axis="x", color=GRIDLINE, lw=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    fig.text(0.01, 0.02, "'(fixed)' = Yoshi's shield does not tilt.",
             fontsize=7.5, color=INK_MUTED)
    fig.text(0.01, 0.005, VALIDATION_NOTE + " (Nana excluded; identical to Popo.)",
             fontsize=7.5, color=INK_MUTED)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(PLOTS / "reach_summary.png", dpi=150)
    fig.savefig(PLOTS / "reach_summary.svg")
    plt.close(fig)
    print("  reach_summary.png done")


if __name__ == "__main__":
    codes = all_codes()
    print(f"Building per-character plots for {len(codes)} characters...")
    make_per_character_plots(codes)
    print("Building comparison grid...")
    make_comparison_grid(codes)
    print("Building reach summary...")
    make_reach_summary(codes)
    print("Done.")
