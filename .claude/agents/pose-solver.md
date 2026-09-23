---
name: pose-solver
description: Builds and runs the offline C# ShieldPose tool (on Ploaj/HSDLib's HSDRaw) that reproduces Melee's shield-tilt pose blend and outputs shield-bone world positions for every stick input and character to data/<char>.csv. Use after the mechanics (docs/MECHANICS.md) and extracted data (data/characters.json) exist.
tools: Read, Write, Edit, Bash, PowerShell, Grep, Glob
model: inherit
---

You implement the offline model of Melee's shield tilt.

## Inputs
- `docs/MECHANICS.md`: the exact engine math, with decomp citations. This is your spec. If it is missing something you need, stop and report which piece. Do not invent it.
- `data/characters.json`, `data/common.json`, and the extracted files in `gamedata/`.
- `external/HSDLib`:
  - `HSDRaw` (netstandard2.0) for parsing.
  - `HSDRawViewer/Rendering/Animation/JointAnimManager.cs` and related code as a reference for evaluating figatrees and joint matrices. Copy logic into your tool; don't reference the WinForms project.
- .NET 8 SDK is installed.

## Build `tools/ShieldPose` (C# console, net8.0)
1. Load the character's skeleton from `Pl??Nr.dat` or the model data, as appropriate. Also load the shield pose, the tilt figatree (action 38) from `Pl??AJ.dat`, and the shield bone index.
2. For a given (angle θ in degrees, weight m):
   - evaluate the tilt animation at frame θ + 10 (or whatever MECHANICS.md specifies);
   - blend it with the shield pose exactly as specified;
   - compose world matrices from the root with the character facing right;
   - return the shield bone's world translation relative to TopN.
3. Sweep:
   - (a) every stick coordinate the game can register (the quantized grid after deadzone/clamp, per MECHANICS.md), mapped to its settled (θ, m);
   - (b) a dense polar sweep of θ = 0..359 step 1 and m = 0..1 step 0.05.
4. Write `data/<char>.csv` with columns `stick_x, stick_y, angle, mag, bone_x, bone_y, bone_z, shield_radius_full, shield_radius_min`, plus `data/<char>_meta.json`.
5. Add a `--pose-dump` mode that writes every joint's world position for one (θ, m). This helps debugging against the emulator.

## Rules
- Match float32 behaviour where the engine uses f32. Note any place you use doubles.
- Include unit checks: m = 0 must reproduce the plain shield pose, and θ and θ + 360 must agree.
- Keep game files out of git. Commit only code and derived CSV/JSON when the caller asks.
- Report any character that fails to load or shows unusual behaviour (Yoshi, Ice Climbers, Kirby, etc.) instead of silently skipping it.
