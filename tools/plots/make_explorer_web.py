"""Build the web (Artifact) version of the shield-tilt explorer.

The page computes every pose live in the browser. It embeds:
  * data/shieldpose_web.json, written by `ShieldPose --export-web` (skeleton subset on the shield and
    hurtbox chains, ShieldPose SRT, the raw Guard FObj tracks, hurtboxes and the PlCo shield constants);
  * tools/plots/shieldpose.js, the float32 JavaScript port of the C# solver (verified against every row of
    data/<code>.csv and data/<code>_hurtboxes.csv by tools/plots/verify_shieldpose_js.js).
The only external resource is the Plotly CDN script. In the browser the page:
  * takes a stick position on a pad (or as integer stick units), snaps it to what the game registers
    (clamp to radius 80 with truncation, /80, per-axis 0.28 deadzone), and settles the tilt angle and
    strength (ftCo_80091BC4), including the angle-0/360 hysteresis toggle;
  * poses the fighter (Guard figatree + ShieldPose blend, HSD world matrices) and draws the bubble,
    hurtboxes and the shield-centre paths (current strength and full tilt, 361 samples each);
  * sizes the bubble from shield health and trigger pressure (inlineB0, ftCo_Guard.c:177-191; Yoshi is fixed);
  * measures, in 3D, how much of each hurtbox capsule lies outside the bubble and how far it sticks out.

Nana is left out (her bubble data is identical to Popo's).

Usage:  dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll --export-web     # -> data/shieldpose_web.json
        .venv/Scripts/python.exe tools/plots/make_explorer_web.py [--export FILE]
"""
import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
HERE = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "plots" / "shield_tilt_explorer_web.html"
SKIP = {"Nn"}  # Nana is identical to Popo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default=str(DATA / "shieldpose_web.json"))
    args = ap.parse_args()
    export_path = pathlib.Path(args.export)
    if not export_path.exists():
        raise SystemExit(f"{export_path} not found; run `ShieldPose --export-web` first")
    export = json.loads(export_path.read_text(encoding="utf-8"))
    for code in SKIP:
        export["chars"].pop(code, None)
    for code, c in export["chars"].items():
        print(code, c["name"], f"{len(c['joints'])} joints, {len(c['hurtboxes'])} hurtboxes")

    blob = json.dumps(export, separators=(",", ":"))
    js = (HERE / "shieldpose.js").read_text(encoding="utf-8")
    template = (HERE / "explorer_web_template.html").read_text(encoding="utf-8")
    for token in ("/*__SHIELDPOSE_JS__*/", "/*__EXPORT__*/{}"):
        assert template.count(token) == 1, token
    assert "</script" not in js and "</script" not in blob
    page = template.replace("/*__SHIELDPOSE_JS__*/", js).replace("/*__EXPORT__*/{}", blob)
    OUT.write_text(page, encoding="utf-8", newline="\n")
    print("wrote", OUT.relative_to(ROOT), f"{OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
