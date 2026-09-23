"""Sweep 16 angles x 3 magnitudes (+ untilted) for one character, holding
digital-trigger full shield in an isolated Slippi Dolphin instance, and
write data/validation/<code>.csv with the settled shield-bone world
position (relative to the fighter, mirrored to face right) plus the raw
x4/x8 tilt-state RAM fields.

Usage: .venv/Scripts/python tools/validate/capture.py <code> [--angles N] [--settle N]

<code> is the two-letter character code from data/characters.json (Fx, Kp, Gw, ...).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = os.environ.get("VALIDATE_SCRATCH")

CODE_TO_MELEE_CHAR = {
    "Fx": "FOX",
    "Kp": "BOWSER",
    "Gw": "GAMEANDWATCH",
    "Kb": "KIRBY",
    "Ys": "YOSHI",
    "Ms": "MARTH",  # characters.json: Ms=Marth, Mt=Mewtwo (fixed in Phase 2)
    "Mt": "MEWTWO",
    "Pp": "POPO",
}

SETTLE_FRAMES = 75  # ~60 for eased x4/x8 to converge + margin
MIN_HEALTH_BEFORE_HOLD = 55.0
MAX_REGEN_WAIT_FRAMES = 1200
REGEN_POLL_FRAMES = 30
SHIELD_BREAK_ACTIONS = {"SHIELD_BREAK_FLY", "SHIELD_BREAK_FALL", "SHIELD_BREAK_DOWN_U",
                         "SHIELD_BREAK_DOWN_D", "SHIELD_BREAK_STAND_U", "SHIELD_BREAK_STAND_D",
                         "SHIELD_BREAK_TEETER"}


def compute_targets(n_angles: int, magnitudes):
    targets = [(0.0, 0.0, 0)]  # angle, mag placeholders for untilted (m=0)
    out = []
    out.append({"angle": None, "mag": 0.0, "sx": 0, "sy": 0})
    for i in range(n_angles):
        theta = 360.0 * i / n_angles
        rad = math.radians(theta)
        for m in magnitudes:
            sx = round(m * 80.0 * math.cos(rad))
            sy = round(m * 80.0 * math.sin(rad))
            sx = max(-80, min(80, sx))
            sy = max(-80, min(80, sy))
            out.append({"angle": theta, "mag": m, "sx": sx, "sy": sy})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--angles", type=int, default=16)
    ap.add_argument("--magnitudes", type=float, nargs="+", default=[0.33, 0.66, 1.0])
    ap.add_argument("--settle", type=int, default=SETTLE_FRAMES)
    ap.add_argument("--scratch", default=SCRATCH)
    args = ap.parse_args()

    import drive
    import ram
    from melee import enums

    chars = json.load(open(os.path.join(ROOT, "data", "characters.json")))
    if args.code not in chars:
        raise SystemExit(f"Unknown code {args.code}")
    shield_bone_index = chars[args.code]["shield_bone_index"]
    char_name = CODE_TO_MELEE_CHAR.get(args.code)
    if char_name is None:
        raise SystemExit(f"No melee.enums.Character mapping for {args.code}; add one to CODE_TO_MELEE_CHAR")
    character = getattr(enums.Character, char_name)

    scratch = args.scratch
    if not scratch:
        raise SystemExit("Set VALIDATE_SCRATCH or pass --scratch")

    console, c1, c2 = drive.start(scratch, character)
    ram.connect()

    targets = compute_targets(args.angles, args.magnitudes)
    rows = []

    # let the fighter finish its entry animation
    for _ in range(120):
        console.step()

    for t in targets:
        # shield_health is pinned to 60 every frame inside ramp_shield_toward
        # (technospider, 2026-09-23: write-only exception for this one field,
        # since health only affects bubble scale, not pose/position). Just
        # wait out a shield break if one somehow slips through.
        waited = 0
        while waited < MAX_REGEN_WAIT_FRAMES:
            gs = console.step()
            action_name = gs.players[1].action.name if (gs and 1 in gs.players) else None
            if action_name not in SHIELD_BREAK_ACTIONS:
                break
            waited += 1
        step = 0.03
        max_attempts = 4
        ok = False
        for attempt in range(max_attempts):
            gs = drive.ramp_shield_toward(console, c1, 0, t["sx"], t["sy"],
                                           step=step, settle_frames=args.settle)
            action_name = gs.players[1].action.name if (gs and 1 in gs.players) else "?"
            if action_name == "SHIELD":
                ok = True
                break
            print(f"  retry (attempt {attempt}) angle={t['angle']} mag={t['mag']} "
                  f"action={action_name} step={step} -> slowing down")
            drive.release(c1)
            for _ in range(10):
                console.step()
            step *= 0.5

        st = ram.read_fighter_state(0, shield_bone_index)
        facing_right = st["facing_dir"] > 0
        rel = tuple(st["bone_world"][k] - st["pos"][k] for k in range(3))
        if not facing_right:
            rel = (-rel[0], rel[1], -rel[2])
        rows.append({
            "angle": t["angle"] if t["angle"] is not None else "",
            "mag": t["mag"],
            "target_stick_x": t["sx"],
            "target_stick_y": t["sy"],
            "lstick_x": st["lstick"][0],
            "lstick_y": st["lstick"][1],
            "guard_x4": st["guard_x4"],
            "guard_x8": st["guard_x8"],
            "bone_x": rel[0],
            "bone_y": rel[1],
            "bone_z": rel[2],
            "shield_health": st["shield_health"],
            "lightshield_amount": st["lightshield_amount"],
            "facing_dir": st["facing_dir"],
            "reachable": ok,
        })
        print(f"angle={t['angle']} mag={t['mag']} sx={t['sx']} sy={t['sy']} "
              f"-> x4={st['guard_x4']:.4f} x8={st['guard_x8']:.4f} rel={rel} "
              f"health={st['shield_health']:.1f} reachable={ok}")

        # release; the top of the next loop iteration will wait for regen.
        drive.release(c1)
        for _ in range(5):
            console.step()

    drive.release(c1)
    console.stop()

    out_dir = os.path.join(ROOT, "data", "validation")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{args.code}.csv")
    fieldnames = list(rows[0].keys())
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out_path} ({len(rows)} rows)")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
