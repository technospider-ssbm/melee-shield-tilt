# melee-shield-tilt

Per-character shield tilt range for Super Smash Bros. Melee (NTSC v1.02), derived from game data and the
[doldecomp/melee](https://github.com/doldecomp/melee) decompilation, validated against Slippi Dolphin.

## Layout
| Path | Contents |
|---|---|
| `external/` | gitignored clones: `melee` (decomp), `HSDLib` |
| `gamedata/` | gitignored files extracted from the ISO |
| `tools/iso_extract/` | Python GCM/FST reader |
| `tools/ShieldPose/` | C# offline pose solver (references `external/HSDLib/HSDRaw`) |
| `tools/validate/` | Dolphin RAM reader, input driver, comparison |
| `tools/plots/` | chart generation |
| `data/` | derived CSV/JSON (tracked) |
| `plots/` | generated charts |
| `docs/MECHANICS.md` | engine notes with decomp citations |

## Setup
```bash
git clone --depth 1 https://github.com/doldecomp/melee external/melee
git clone --depth 1 https://github.com/Ploaj/HSDLib external/HSDLib
dotnet build external/HSDLib/HSDRaw/HSDRaw.csproj -c Release
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Game files are never committed. Extract them from your own vanilla v1.02 ISO.
