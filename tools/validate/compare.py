"""Compare a captured data/validation/<code>.csv against the pose-solver's
data/<code>.csv ground truth.

For each captured (post-deadzone) sample, finds the nearest (stick_x, stick_y)
row in the pose-solver CSV (grid ∪ polar) by Euclidean distance in stick space,
and reports the position error between bone_{x,y,z} in both files.

Usage: .venv/Scripts/python tools/validate/compare.py <code>
"""
from __future__ import annotations

import argparse
import csv
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_solver_csv(code):
    path = os.path.join(ROOT, "data", f"{code}.csv")
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            sx = r["stick_x"]
            sy = r["stick_y"]
            if sx == "" or sy == "":
                # polar rows have no stick_x/stick_y; derive from angle/mag
                theta = math.radians(float(r["angle"]))
                m = float(r["mag"])
                sx = m * 80.0 * math.cos(theta)
                sy = m * 80.0 * math.sin(theta)
            else:
                sx = float(sx)
                sy = float(sy)
            rows.append({
                "sx": sx, "sy": sy, "angle": float(r["angle"]),
                "bone": (float(r["bone_x"]), float(r["bone_y"]), float(r["bone_z"])),
                "shield_radius_full": float(r["shield_radius_full"]),
                "shield_radius_min": float(r["shield_radius_min"]),
            })
    return rows


def load_validation_csv(code):
    path = os.path.join(ROOT, "data", "validation", f"{code}.csv")
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("reachable") == "False":
                continue
            rows.append({
                "angle": r["angle"],
                "mag": float(r["mag"]),
                "sx": float(r["lstick_x"]) * 80.0,
                "sy": float(r["lstick_y"]) * 80.0,
                "bone": (float(r["bone_x"]), float(r["bone_y"]), float(r["bone_z"])),
                "guard_x4": float(r["guard_x4"]),
                "guard_x8": float(r["guard_x8"]),
                "shield_health": float(r["shield_health"]),
                "lightshield_amount": float(r["lightshield_amount"]),
            })
    return rows


def nearest(solver_rows, sx, sy, g=None):
    """Nearest row in stick space. Ties (same stick) are broken by the settled
    angle: a stick at exactly 0 deg has two solver rows, angle 0 (x8 = 10) and
    angle 360 (x8 = 370), and the capture's guard_x8 says which one the game is on
    (MECHANICS 1.2)."""
    best = None
    best_key = None
    for r in solver_rows:
        d = (r["sx"] - sx) ** 2 + (r["sy"] - sy) ** 2
        key = (round(d, 9), abs(r["angle"] - g) if g is not None else 0.0)
        if best_key is None or key < best_key:
            best_key = key
            best = r
    return best, math.sqrt(best_key[0]) if best_key is not None else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    args = ap.parse_args()

    solver_rows = load_solver_csv(args.code)
    val_rows = load_validation_csv(args.code)

    errors = []
    print(f"{'angle':>8} {'mag':>5} {'stick_match_dist':>17} {'pos_err':>10} "
          f"{'val_bone':>28} {'solver_bone':>28}")
    for v in val_rows:
        match, stick_dist = nearest(solver_rows, v["sx"], v["sy"], v["guard_x8"] - 10.0)
        dx = v["bone"][0] - match["bone"][0]
        dy = v["bone"][1] - match["bone"][1]
        dz = v["bone"][2] - match["bone"][2]
        err = math.sqrt(dx * dx + dy * dy + dz * dz)
        errors.append(err)
        print(f"{str(v['angle']):>8} {v['mag']:>5.2f} {stick_dist:>17.2f} {err:>10.2e} "
              f"{str(tuple(round(c,3) for c in v['bone'])):>28} "
              f"{str(tuple(round(c,3) for c in match['bone'])):>28}")

    if errors:
        print(f"\n{args.code}: n={len(errors)} max_err={max(errors):.2e} "
              f"mean_err={sum(errors)/len(errors):.4f}")
    else:
        print("No comparable rows.")


if __name__ == "__main__":
    main()
