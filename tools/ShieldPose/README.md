# ShieldPose

This is an offline model of Melee's settled shield-tilt pose (NTSC 1.02). It implements `docs/MECHANICS.md` sections 1 to 5 and 7.
For each settled stick state (angle θ, weight m), it evaluates the Guard figatree (subaction 38) at frame 10 + θ, blends it
with ShieldPose as `ftCo_80091E78` does, and composes HSD world matrices. It writes out the shield-bubble centre and the posed hurtboxes.

## Build / run (from the repo root)
```bash
dotnet build tools/ShieldPose -c Release
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll                 # all 27 characters -> data/
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll --char Fx Ms    # a subset
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll --sanity        # bubble at neutral/up/down/forward/back
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll --selftest      # FObj port vs HSDLib FOBJ_Player
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll --pose-dump --char Fx --angle 90 --mag 1 [--facing -1] [--out f.csv]
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll --export-web [--out data/shieldpose_web.json] [--char ...]
```
Options: `--gamedata <dir>` (default `gamedata`), `--data <dir>` (default `data`), `--no-hurtboxes`.
The exit code is non-zero if a character fails to load or fails a check.

`--pose-dump` writes one row per joint for a single (θ, m, facing). Each row has the part index, parent, costume flags, and the live local
SRT (Euler or quaternion). It also has the world translation, so you can compare it with emulator RAM (`parts[i].joint->mtx`).

`--export-web` writes `data/shieldpose_web.json` (about 190 KiB for all 27 characters; not committed, as it holds raw
Guard FObj bytes). It has everything `tools/plots/shieldpose.js` needs to pose a character in the browser:
* `common`: the PlCo stick deadzones and the inlineB0 shield constants (x260, x264, x2D4, x2D8);
* per character: name, kind, `has_tilt` (false for Yoshi, whose fixed pose is the costume rest pose), the figatree
  end frame, model scale, initial shield size and the shield joint;
* `joints`: only the joints on the shield chain and the hurtbox chains (closed under parent, preorder, re-indexed).
  Each is `[parent, flags, rest SRT, ShieldPose SRT, tracks]`. Flags: 1 = classical scale, 2 = item-hold part
  (scale 1/model_scale), 4 = dynamics (flags_b0, not blended), 8 = flags_b4 (TransN, part_to_joint[0x35], Mewtwo
  parts[1]; take ShieldPose when m < 1). Tracks are `[type, startframe, frac_value, frac_slope, length, base64 bytes]`;
* `hurtboxes`: `[joint, part, type, grabbable, x1, y1, z1, x2, y2, z2, radius]` (local);
* Nana is exported too (Popo's Guard figatree) with a note; the explorer skips her.

`tools/plots/verify_shieldpose_js.js` (Node) re-computes every row of `data/<code>.csv` and `data/<code>_hurtboxes.csv`
with the JS port and reports the max error per character. Bubble centres and radii match bit-for-bit (Donkey Kong: 1 ulp
in 0.03% of rows); posed hurtboxes are within 5.7e-6 (the port rounds libm results from double, see shieldpose.js).

## Outputs
* `data/<code>.csv`: `sweep,stick_x,stick_y,angle,mag,bone_x,bone_y,bone_z,shield_radius_full,shield_radius_min`.
  `grid` rows cover every lstick value the engine can hold (8153 after clamp, /80 and per-axis deadzone), given in integer
  stick units. `polar` rows cover θ = 0..360 in steps of 1 and m = 0..1 in steps of 0.05. `angle` is the settled eased angle g = x8 − 10.
  A stick at exactly 0° has two settled states, g = 0 (frame 10) and g = 360 (frame 370), depending on approach direction
  (MECHANICS 1.2). Each such grid stick with m > 0 therefore gets two rows, 58 extra per tilting character. The fighter faces right and +x is forward. Positions are relative to
  TopN (cur_pos) and include model scale.
* `data/<code>_hurtboxes.csv`: the same sample keys, plus the hurtbox index, part, joint, type, grabbable, the world capsule
  endpoints and the scaled radius. This file is not committed (about 500 MB in total). Regenerate it with the command above.
* `data/<code>_meta.json`: sources, the part-to-joint map, the shield chain with costume flags, b4 and dynamics parts,
  the radius formula with citations, check results, and notes.

## Model notes
* Part index vs joint index: parts[] slots for which `ftParts_8007506C(kind, i) != 0` get no costume joint. The rest
  take costume joints in preorder. Both the shield bone (`ModelLookupTables.ShieldBone`) and the hurtbox `bone_index` are parts
  indices.
* `flags_b4` comes from `part_to_joint[FtPart_TransN]` and `part_to_joint[0x35]`, read from the PlCo bone tables. Mewtwo also gets parts[1].
  For Mewtwo and Game & Watch the table maps FtPart_TransN to part 2, which is on their shield chain.
* Dynamics bones (`flags_b0`, FighterData+0x2C, limited to `dynamicsNum`) are physics-driven in game. Here they keep the
  costume rest local pose, which only affects hurtboxes on them (listed in meta).
* Yoshi does not tilt. The GuardHold state uses the costume rest pose, and the bubble scale is `initial_shield_size`.
* Nana has no Guard figatree of her own, so Popo's (PlPpAJ.dat) is used, per `ftData_80085FD4`.

## float32 fidelity and deviations
Pose math is done in `float` in decomp operation order: FObj interpreter, EulerToQuat, slerp, lb_8000C868 blend,
HSD_MtxSRT/SRTQuat, and the stick clamp, atan2 and deadzone. Known deviations:
* `sinf/cosf/atanf/acosf` use .NET `MathF`, not the game's MSL libm. The two may differ in the last ULP.
* `PSMTXConcat` is emulated with fused multiply-adds in paired-single order. Gekko's 25-bit rounding of frC in
  `ps_madd` is not emulated.
* `MTXQuat` uses the C reference formula. The game's `PSMTXQuat` computes 2/|q|² with `fres` plus one Newton step.
* `MTXMultVec` (hurtbox endpoints) is a plain float dot product.
* Doubles appear only where the source uses them: `1.0/fterm`, `1.0/scale` in MtxSRT, `M_PI_2*facing`, and `pi - atanf`
  in lb_8000D008. Doubles are also used for diagnostics: the radius chain scale `cbrt(|det|)`, singular values, and check distances.
* Settled state: frame = `10 + deg` (plus the 370 variant at 0°, see above) and x4 = `min(1, |ls|)`. MECHANICS 1.1 says these are exact to about 1e-4 deg. The easing loop is not iterated.

Measured effect: the FObj port matches HSDLib's FOBJ_Player to 3e-6 on every Guard track (`--selftest`). The facing-left
mirror is exact to within 1e-6, which is the residual of cosf(π/2).
