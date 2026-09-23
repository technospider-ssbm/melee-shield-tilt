#!/usr/bin/env python
"""Build plots/shield_tilt_explorer.html - an interactive plotly picker.

Downsamples to the polar sweep at angle step 5 degrees x mag in
{0, .2, .4, .6, .8, 1.0} so the embedded JSON stays small (all 27
characters ~a few MB). Uses the plotly.js CDN build rather than bundling
the ~3-4 MB plotly.js locally, per technospider's "keep it under ~15 MB"
note. Run with the project venv:

    .venv/Scripts/python.exe tools/plots/make_explorer.py

Angle now runs 0..360 inclusive (commit 75f3ac7): a stick held exactly
forward (0deg) has two history-dependent settled poses (frame 10 = angle 0,
frame 370 = angle 360), so 360 is a real, distinct sample, not a
duplicate of 0.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, PLOTS, all_codes, char_meta, display_name, VALIDATION_NOTE

ANGLES = list(range(0, 361, 5))  # 0, 5, ..., 360
MAGS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def build_char_payload(code):
    meta = char_meta(code)
    main = pd.read_csv(DATA / f"{code}.csv")
    r_full = float(main.shield_radius_full.iloc[0])
    r_min = float(main.shield_radius_min.iloc[0])
    has_tilt = bool(meta.get("has_tilt", True))

    polar = main[main.sweep == "polar"]
    # centers[a][m] = [x, y]; angle 0 row for mag 0 stands for every angle
    a0 = polar[np.isclose(polar.mag, 0)]
    ux, uy = float(a0.bone_x.iloc[0]), float(a0.bone_y.iloc[0])

    # forward (angle 0) hysteresis, in full 3D like the static charts
    fwd_gap = 0.0
    r0 = polar[(polar.angle == 0) & np.isclose(polar.mag, 1.0)]
    r360 = polar[(polar.angle == 360) & np.isclose(polar.mag, 1.0)]
    if not r0.empty and not r360.empty:
        fwd_gap = float(np.sqrt(
            (r0.bone_x.iloc[0] - r360.bone_x.iloc[0]) ** 2 +
            (r0.bone_y.iloc[0] - r360.bone_y.iloc[0]) ** 2 +
            (r0.bone_z.iloc[0] - r360.bone_z.iloc[0]) ** 2))

    centers = []
    for ang in ANGLES:
        row_by_mag = []
        for m in MAGS:
            if m == 0:
                row_by_mag.append([ux, uy])
                continue
            r = polar[(polar.angle == ang) & (np.isclose(polar.mag, m))]
            if r.empty:
                row_by_mag.append([ux, uy])
            else:
                row_by_mag.append([float(r.bone_x.iloc[0]), float(r.bone_y.iloc[0])])
        centers.append(row_by_mag)

    hb_path = DATA / f"{code}_hurtboxes.csv"
    boxes = []
    xs, ys = [ux], [uy]
    if hb_path.exists():
        hb = pd.read_csv(hb_path)
        sub = hb[(hb.sweep == "polar") & (hb.angle.isin(ANGLES)) &
                 (hb.mag.isin(MAGS))]
        # index: [angle_idx][mag_idx] -> list of [x1,y1,x2,y2,r]
        grouped = {}
        for row in sub.itertuples(index=False):
            grouped.setdefault((row.angle, row.mag), []).append(
                [round(row.x1, 3), round(row.y1, 3), round(row.x2, 3),
                 round(row.y2, 3), round(row.radius, 3)])
            xs.extend([row.x1, row.x2]); ys.extend([row.y1, row.y2])
        for ang in ANGLES:
            row_by_mag = []
            for m in MAGS:
                row_by_mag.append(grouped.get((ang, m), []))
            boxes.append(row_by_mag)

    xs = np.array(xs); ys = np.array(ys)
    pad = r_full * 0.3 + 1
    xr = [float(xs.min() - r_full - pad * 0), float(xs.max() + r_full)]
    yr = [float(ys.min() - r_full), float(ys.max() + r_full)]
    # square up the range so aspect stays 1:1 regardless of plot box size
    cx, cy = (xr[0] + xr[1]) / 2, (yr[0] + yr[1]) / 2
    half = max(xr[1] - xr[0], yr[1] - yr[0]) / 2 + 1
    xr = [cx - half, cx + half]
    yr = [cy - half, cy + half]

    return {
        "name": display_name(code, meta),
        "r_full": round(r_full, 4),
        "r_min": round(r_min, 4),
        "has_tilt": has_tilt,
        "fwd_gap": round(fwd_gap, 3),
        "angles": ANGLES,
        "mags": MAGS,
        "centers": [[[round(v, 3) for v in c] for c in row] for row in centers],
        "boxes": boxes,
        "xr": [round(v, 2) for v in xr],
        "yr": [round(v, 2) for v in yr],
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Melee shield-tilt explorer</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {
    --surface-1: #fcfcfb; --page: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
    --ink-muted: #898781; --grid: #e1e0d9; --baseline: #c3c2b7;
    --accent: #2a78d6; --accent-light: #9ec5f4; --orange: #eb6834;
    --good: #0ca30c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--page); color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  header { padding: 16px 20px 8px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  p.sub { color: var(--ink-2); font-size: 13px; margin: 0; max-width: 720px; }
  p.validation { color: var(--ink-2); font-size: 12px; margin: 4px 0 0; max-width: 720px; }
  .layout {
    display: flex; flex-wrap: wrap; gap: 16px; padding: 12px 20px 24px;
    align-items: flex-start;
  }
  .controls {
    background: var(--surface-1); border: 1px solid var(--baseline);
    border-radius: 8px; padding: 14px 16px; min-width: 240px; max-width: 280px;
  }
  .controls label { display: block; font-size: 12px; color: var(--ink-2);
    margin: 12px 0 4px; }
  .controls select, .controls input[type=range] { width: 100%; }
  .controls .row-val { display:flex; justify-content:space-between;
    font-size: 11px; color: var(--ink-muted); }
  #plot { flex: 1 1 520px; min-width: 300px; max-width: 720px; }
  .tag { display: inline-block; margin-top: 10px; font-size: 11px;
    padding: 2px 8px; border-radius: 10px; }
  .tag.fixed { color: var(--ink-muted); background: rgba(137,135,129,0.15); }
  .tag.hysteresis { color: var(--orange); background: rgba(235,104,52,0.1); }
  footer { padding: 0 20px 24px; font-size: 11px; color: var(--ink-muted);
    max-width: 720px; }
</style>
</head>
<body>
<header>
  <h1>Melee shield-tilt explorer</h1>
  <p class="sub">Shield-centre position and posed hurtboxes vs. stick angle
  and magnitude, from the offline pose solver (Phase 3). Side view: x =
  forward, y = up, in game units relative to the character's root
  position.</p>
  <p class="validation">__VALIDATION_NOTE__</p>
</header>
<div class="layout">
  <div class="controls">
    <label for="char">Character</label>
    <select id="char"></select>
    <div id="tagbox"></div>

    <label for="angle">Stick angle: <span id="angleval"></span>&deg;
      (0 = forward/fresh, 90 = up, 360 = forward/absorbing &mdash; see the
      hysteresis note below when it appears)</label>
    <input type="range" id="angle" min="0" max="360" step="5" value="0">

    <label for="mag">Stick magnitude: <span id="magval"></span></label>
    <input type="range" id="mag" min="0" max="5" step="1" value="0">
  </div>
  <div id="plot"></div>
</div>
<footer>
  Downsampled to angle step 5&deg; and magnitude steps of 0.2 to keep this
  page small; the static per-character PNGs in <code>plots/</code> use the
  full-resolution sweep. Yoshi's shield does not tilt (fixed bubble). A
  stick held exactly forward (angle 0/360) can settle to either of two
  history-dependent poses; where they differ noticeably, dragging the angle
  slider between 0 and 360 shows the gap.
</footer>
<script>
const DATA = __DATA_JSON__;
const codes = Object.keys(DATA);
const sel = document.getElementById('char');
for (const c of codes) {
  const o = document.createElement('option');
  o.value = c; o.textContent = DATA[c].name;
  sel.appendChild(o);
}
sel.value = codes.includes('Fx') ? 'Fx' : codes[0];

const angleInput = document.getElementById('angle');
const magInput = document.getElementById('mag');
const angleVal = document.getElementById('angleval');
const magVal = document.getElementById('magval');
const tagbox = document.getElementById('tagbox');

function stadiumPath(x1, y1, x2, y2, r) {
  let dx = x2 - x1, dy = y2 - y1;
  let len = Math.hypot(dx, dy);
  let nx, ny;
  if (len < 1e-9) { nx = 1; ny = 0; } else { nx = -dy / len; ny = dx / len; }
  const p1a = [x1 + nx * r, y1 + ny * r];
  const p1b = [x1 - nx * r, y1 - ny * r];
  const p2a = [x2 + nx * r, y2 + ny * r];
  const p2b = [x2 - nx * r, y2 - ny * r];
  return `M ${p1a[0]},${p1a[1]} L ${p2a[0]},${p2a[1]} ` +
    `A ${r},${r} 0 1,1 ${p2b[0]},${p2b[1]} ` +
    `L ${p1b[0]},${p1b[1]} ` +
    `A ${r},${r} 0 1,1 ${p1a[0]},${p1a[1]} Z`;
}

function circlePath(cx, cy, r) {
  return `M ${cx - r},${cy} A ${r},${r} 0 1,1 ${cx + r},${cy} ` +
    `A ${r},${r} 0 1,1 ${cx - r},${cy} Z`;
}

let firstDraw = true;

function draw() {
  const code = sel.value;
  const d = DATA[code];
  const ai = Math.round(angleInput.value / 5);
  const mi = parseInt(magInput.value, 10);
  angleVal.textContent = d.angles[ai];
  magVal.textContent = d.mags[mi].toFixed(1);

  angleInput.disabled = !d.has_tilt;

  tagbox.innerHTML = '';
  if (!d.has_tilt) {
    const t = document.createElement('span');
    t.className = 'tag fixed'; t.textContent = 'fixed bubble (no tilt)';
    tagbox.appendChild(t);
  }
  if (d.fwd_gap > 0.05) {
    const t = document.createElement('span');
    t.className = 'tag hysteresis';
    t.textContent = `forward: 2 resting states, ${d.fwd_gap.toFixed(2)} units apart`;
    tagbox.appendChild(t);
  }

  const [cx, cy] = d.centers[ai][mi];
  const [ux, uy] = d.centers[0][0];
  const shapes = [];
  // untilted body hurtboxes: light fill + a visible mid-grey outline, at the
  // back, so bubbles/markers drawn after this never get hidden underneath
  for (const b of d.boxes[0][0]) {
    shapes.push({ type: 'path', path: stadiumPath(...b), fillcolor: 'rgba(137,135,129,0.22)',
      line: { color: 'rgba(137,135,129,0.7)', width: 0.6 }, layer: 'below' });
  }
  // posed hurtboxes at the current stick position, very faint accent tint
  for (const b of (d.boxes[ai] ? d.boxes[ai][mi] : [])) {
    shapes.push({ type: 'path', path: stadiumPath(...b), fillcolor: 'rgba(42,120,214,0.1)',
      line: { color: 'rgba(42,120,214,0.35)', width: 0.4 }, layer: 'below' });
  }
  // untilted bubble outline
  shapes.push({ type: 'path', path: circlePath(ux, uy, d.r_full), fillcolor: 'rgba(0,0,0,0)',
    line: { color: '#0b0b0b', width: 1.2, dash: 'dot' } });
  // current bubble
  shapes.push({ type: 'path', path: circlePath(cx, cy, d.r_full), fillcolor: 'rgba(42,120,214,0.06)',
    line: { color: '#2a78d6', width: 2 } });
  shapes.push({ type: 'path', path: circlePath(cx, cy, d.r_min), fillcolor: 'rgba(0,0,0,0)',
    line: { color: '#eb6834', width: 1, dash: 'dash' } });

  const traces = [
    { x: [ux], y: [uy], mode: 'markers', marker: { color: '#0b0b0b', size: 6 },
      name: 'untilted centre', hovertemplate: 'untilted centre<extra></extra>' },
    { x: [cx], y: [cy], mode: 'markers', marker: { color: '#2a78d6', size: 7 },
      name: 'shield centre',
      hovertemplate: `shield centre<br>x=%{x:.2f} y=%{y:.2f}<extra></extra>` },
  ];

  const layout = {
    shapes: shapes,
    xaxis: { range: d.xr, title: 'forward → (game units)', zeroline: false,
      gridcolor: '#e1e0d9', scaleanchor: 'y', scaleratio: 1 },
    yaxis: { range: d.yr, title: 'up →', zeroline: false, gridcolor: '#e1e0d9' },
    plot_bgcolor: '#fcfcfb', paper_bgcolor: '#fcfcfb',
    margin: { l: 50, r: 20, t: 30, b: 45 },
    title: { text: d.name, x: 0, font: { size: 16 } },
    showlegend: true,
    legend: { orientation: 'h', y: -0.15 },
    font: { family: 'system-ui, -apple-system, Segoe UI, sans-serif', color: '#0b0b0b' },
    height: 560,
  };

  if (firstDraw) {
    Plotly.newPlot('plot', traces, layout, { displayModeBar: false, responsive: true });
    firstDraw = false;
  } else {
    Plotly.react('plot', traces, layout, { displayModeBar: false, responsive: true });
  }
}

sel.addEventListener('change', () => { magInput.value = 0; angleInput.value = 0; draw(); });
angleInput.addEventListener('input', draw);
magInput.addEventListener('input', draw);
draw();
</script>
</body>
</html>
"""


def main():
    codes = all_codes()
    payload = {}
    for i, code in enumerate(codes):
        payload[code] = build_char_payload(code)
        print(f"  [{i+1}/{len(codes)}] {code} done")
    note = VALIDATION_NOTE + " Nana is covered by Popo (identical pose, not independently selectable)."
    out = HTML_TEMPLATE.replace("__VALIDATION_NOTE__", note)
    out = out.replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
    out_path = PLOTS / "shield_tilt_explorer.html"
    out_path.write_text(out, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1e6
    print(f"Wrote {out_path} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
