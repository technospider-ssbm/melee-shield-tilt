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
# Yoshi (ftyoshiguard.c, ftYoshi/ftyoshi.c:29-51) uses character-specific
# motion states GuardOn_0=341, GuardHold=342, GuardOff=343 with his own
# fp->mv.ys.guard layout instead of the shared fp->mv.co.guard union, so
# guard_x4/x8 (which alias mv.co.guard) are meaningless for him and
# libmelee's shared Action enum mislabels 342 as NEUTRAL_B_CHARGING even
# though he really is shielding (technospider, 2026-09-23). Accept on raw
# motion_id == 342 instead of Action.SHIELD, with a fixed extra settle.
YOSHI_GUARD_HOLD_MOTION_ID = 342
YOSHI_EXTRA_SETTLE_FRAMES = 30
MIN_HEALTH_BEFORE_HOLD = 55.0
MAX_REGEN_WAIT_FRAMES = 1200
REGEN_POLL_FRAMES = 30
SHIELD_BREAK_ACTIONS = {"SHIELD_BREAK_FLY", "SHIELD_BREAK_FALL", "SHIELD_BREAK_DOWN_U",
                         "SHIELD_BREAK_DOWN_D", "SHIELD_BREAK_STAND_U", "SHIELD_BREAK_STAND_D",
                         "SHIELD_BREAK_TEETER"}


def compute_rings(n_angles: int, magnitudes):
    """Returns a list of rings, each a list of target dicts sharing a fixed
    magnitude, in angle order, so consecutive samples within a ring can be
    reached by a direct slow ramp (walking around the circle) instead of
    releasing and re-pressing shield every time."""
    rings = [[{"angle": None, "mag": 0.0, "sx": 0, "sy": 0}]]
    for m in magnitudes:
        ring = []
        for i in range(n_angles):
            theta = 360.0 * i / n_angles
            rad = math.radians(theta)
            sx = max(-80, min(80, round(m * 80.0 * math.cos(rad))))
            sy = max(-80, min(80, round(m * 80.0 * math.sin(rad))))
            ring.append({"angle": theta, "mag": m, "sx": sx, "sy": sy})
        rings.append(ring)
    return rings


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

    rings = compute_rings(args.angles, args.magnitudes)
    rows = []

    # let the fighter finish its entry animation
    for _ in range(120):
        console.step()

    def sample_and_record(t, ok):
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
            "axis_scale_x": st["axis_scale"][0],
            "axis_scale_y": st["axis_scale"][1],
            "axis_scale_z": st["axis_scale"][2],
            "reachable": ok,
        })
        ax = st["axis_scale"]
        aniso = (max(ax) - min(ax)) / (sum(ax) / 3.0)
        print(f"angle={t['angle']} mag={t['mag']} sx={t['sx']} sy={t['sy']} "
              f"-> x4={st['guard_x4']:.4f} x8={st['guard_x8']:.4f} rel={rel} "
              f"health={st['shield_health']:.1f} reachable={ok} "
              f"axis_scale={tuple(round(a,4) for a in ax)} aniso={aniso:.4f}")

    # technospider (2026-09-23): with health pinned, hold shield continuously
    # and walk the stick from sample to sample within a ring (fixed
    # magnitude) instead of releasing/re-pressing every time -- the tilt
    # eases toward the stick target regardless of where it came from, so a
    # settled sample doesn't depend on history. Only release and restart
    # from neutral between rings (where the direct path could cross a smash
    # threshold) or after a failed sample.
    cur_x, cur_y = 0, 0
    for ring_idx, ring in enumerate(rings):
        first_in_ring = True
        for t in ring:
            step = 0.03
            max_attempts = 4
            ok = False
            for attempt in range(max_attempts):
                if first_in_ring:
                    gs = drive.ramp_shield_toward(console, c1, 0, t["sx"], t["sy"],
                                                   step=step, settle_frames=args.settle)
                else:
                    gs = drive.ramp_stick_to(console, c1, 0, cur_x, cur_y, t["sx"], t["sy"],
                                              step=step, settle_frames=args.settle)
                action_name = gs.players[1].action.name if (gs and 1 in gs.players) else "?"
                # Also require facing right: a CPU/opponent hit can turn the
                # fighter around mid-sweep. lstick is raw/absolute (not
                # facing-relative), but the pose-solver CSV assumes
                # facing=+1 throughout, so a facing-left sample would need a
                # different (mirrored) stick target to mean the same
                # in-fighter-space angle -- just retry until facing is right.
                facing_ok = ram.get_facing_dir(0) > 0
                if args.code == "Ys":
                    raw_motion_id = ram._read_u32(ram.get_fighter_ptr(0) + ram.FP_MOTION_ID)
                    action_name = f"motion_id={raw_motion_id}"
                    in_guard = raw_motion_id == YOSHI_GUARD_HOLD_MOTION_ID
                    if in_guard and facing_ok:
                        for _ in range(YOSHI_EXTRA_SETTLE_FRAMES):
                            console.step()
                            ram.pin_shield_health(0)
                        ok = True
                        break
                else:
                    if action_name == "SHIELD" and facing_ok:
                        ok = True
                        break
                print(f"  retry (attempt {attempt}) angle={t['angle']} mag={t['mag']} "
                      f"action={action_name} facing_ok={facing_ok} step={step} -> slowing down, from neutral")
                drive.release(c1)
                for _ in range(10):
                    console.step()
                step *= 0.5
                first_in_ring = True  # re-approach from neutral after a failure

            sample_and_record(t, ok)
            cur_x, cur_y = t["sx"], t["sy"]
            first_in_ring = False

        # Between rings: release and reset to neutral before the next ring
        # starts (a direct jump between ring magnitudes could cross a smash
        # threshold too fast).
        drive.release(c1)
        for _ in range(10):
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
