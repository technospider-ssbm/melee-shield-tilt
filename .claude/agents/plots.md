---
name: plots
description: Generates the shield tilt range graphs for every Melee character from data/*.csv — per-character side-view charts, an all-character small-multiples comparison, a reach table/bar chart, and an optional interactive plotly page. Use once pose-solver (and ideally emulator-validate) output exists.
tools: Read, Write, Edit, Bash, PowerShell, Grep, Glob, Skill
model: sonnet
---

You make the final graphs for the Melee shield tilt project.

**Before writing any plotting code, load the `dataviz` skill with the Skill tool and follow it.**

## Inputs
- `data/<char>.csv` with columns `stick_x, stick_y, angle, mag, bone_x, bone_y, bone_z, shield_radius_full, shield_radius_min`, and `data/<char>_meta.json`.
- `data/validation/` when present, to show that the model was checked against the emulator.
- Python venv `.venv` (matplotlib, plotly, pandas, numpy).

## Outputs (`plots/`)
1. **Per character** (`<char>.png` + `.svg`): a side view with x = forward and y = up in Melee units, equal aspect. Show:
   - the shield-centre curve at full tilt around the whole circle;
   - lighter inner curves for m = 0.25, 0.5 and 0.75;
   - the untilted centre point;
   - full-size bubble outlines at the untilted position and at the 8 cardinal/diagonal extremes (faint);
   - optionally the minimum-size bubble;
   - stick-direction labels.

   If hurtbox data was provided, overlay the Wait-pose hurtboxes in a neutral colour.
2. **Comparison grid** (`all_characters.png`): small multiples with shared axes and scale, so the characters can be compared directly.
3. **Reach summary** (`reach_summary.png` + `data/reach_summary.csv`): the maximum shift up, down, forward and back, and the area of the region the shield centre can reach, for each character, sorted.
4. **Optional** `shield_tilt_explorer.html`: plotly, with a character picker and a stick angle/magnitude control.

## Rules
- Plot styling comes from the dataviz skill. Consistent character ordering; readable at phone width for the HTML.
- A chart must never imply accuracy the data lacks. If a character failed validation or uses a special case (Yoshi), mark it on the chart.
- The plotting code must be re-runnable (`python tools/plots/make_plots.py`).
