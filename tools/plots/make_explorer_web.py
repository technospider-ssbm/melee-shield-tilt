"""Build the web (Artifact) version of the shield-tilt explorer.

Reads data/<code>.csv and data/<code>_hurtboxes.csv (polar sweep, every 5 deg
and every 0.2 of stick magnitude) and writes a single self-contained page,
plots/shield_tilt_explorer_web.html. In the browser the page:
  * sizes the bubble from shield health and trigger pressure (inlineB0,
    ftCo_Guard.c:177-191; Yoshi is fixed, ftyoshiguard.c hurt.scale = 1);
  * draws the tilted hurtboxes and measures, in 3D, how much of each capsule
    lies outside the bubble (quasi-random volume sampling) and how far it
    sticks out.

Usage:  .venv/Scripts/python.exe tools/plots/make_explorer_web.py [--hurtbox-dir DIR]
        --hurtbox-dir: prefer DIR/<code>_hurtboxes.csv when present (e.g. a freshly
        regenerated file while the copy in data/ is locked by another program).
"""
import argparse
import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "plots" / "shield_tilt_explorer_web.html"

ANGLE_STEP = 5
MAGS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
FULL_FACTOR = 0.57500005  # shield_radius_full / (size * chain scale), hard press, 60 HP


def r3(v):
    return round(float(v), 3)


def pick_polar(df):
    df = df[df["sweep"] == "polar"].copy()
    df["ai"] = (df["angle"] / ANGLE_STEP).round().astype(int)
    df["mi"] = (df["mag"] * 5).round().astype(int)
    keep = (df["angle"] % ANGLE_STEP == 0) & ((df["mag"] * 5 - df["mi"]).abs() < 1e-6)
    return df[keep]


def build_char(code, chars, hurtbox_dir=None):
    meta = json.loads((DATA / f"{code}_meta.json").read_text(encoding="utf-8"))
    main = pick_polar(pd.read_csv(DATA / f"{code}.csv"))
    hb_path = DATA / f"{code}_hurtboxes.csv"
    if hurtbox_dir and (pathlib.Path(hurtbox_dir) / hb_path.name).exists():
        hb_path = pathlib.Path(hurtbox_dir) / hb_path.name
    hb = pick_polar(pd.read_csv(hb_path))
    n_ang = 360 // ANGLE_STEP + 1

    centers = [[None] * len(MAGS) for _ in range(n_ang)]
    for row in main.itertuples():
        centers[row.ai][row.mi] = [r3(row.bone_x), r3(row.bone_y), r3(row.bone_z)]

    boxes = [[[] for _ in MAGS] for _ in range(n_ang)]
    hb = hb.sort_values(["ai", "mi", "hurtbox"])
    for row in hb.itertuples():
        boxes[row.ai][row.mi].append(
            [r3(row.x1), r3(row.y1), r3(row.z1), r3(row.x2), r3(row.y2), r3(row.z2), r3(row.radius)])

    missing = [(a, m) for a in range(n_ang) for m in range(len(MAGS))
               if centers[a][m] is None or not boxes[a][m]]
    assert not missing, f"{code}: missing samples {missing[:5]}"

    dyn = set(meta.get("dynamics_parts_b0") or [])
    first = hb[(hb["ai"] == 0) & (hb["mi"] == 0)].sort_values("hurtbox")
    info_src = chars.get(code, {}).get("hurtboxes", [])
    hinfo = []
    for row in first.itertuples():
        kind = info_src[row.hurtbox]["type"] if row.hurtbox < len(info_src) else str(row.type)
        hinfo.append({"i": int(row.hurtbox), "type": kind, "joint": int(row.joint),
                      "approx": int(row.part) in dyn})

    r_full = float(main["shield_radius_full"].iloc[0])
    fixed = not meta["has_tilt"]
    return {
        "name": meta["name"],
        "has_tilt": bool(meta["has_tilt"]),
        "fixed_r": fixed,
        "r_full": r3(r_full),
        "size_chain": round(r_full / (1.0 if fixed else FULL_FACTOR), 4),
        "centers": centers,
        "boxes": boxes,
        "hinfo": hinfo,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hurtbox-dir")
    args = ap.parse_args()
    chars = json.loads((DATA / "characters.json").read_text(encoding="utf-8"))
    codes = sorted(p.stem for p in DATA.glob("*_meta.json"))
    codes = [c.removesuffix("_meta") for c in codes]
    data = {}
    for code in codes:
        if code == "Nn":  # Nana is identical to Popo
            continue
        data[code] = build_char(code, chars, args.hurtbox_dir)
        print(code, data[code]["name"])
    data = dict(sorted(data.items(), key=lambda kv: kv[1]["name"]))
    blob = json.dumps(data, separators=(",", ":"))
    template = (pathlib.Path(__file__).with_name("explorer_web_template.html")
                .read_text(encoding="utf-8"))
    OUT.write_text(template.replace("/*__DATA__*/{}", blob), encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT), f"{OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
