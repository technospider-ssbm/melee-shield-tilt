# melee-shield-tilt

> [!WARNING]
> **This project was made entirely with AI.**
>
> Claude (Anthropic's AI model), running in Claude Code, did all of the following:
> - the research into the game's code;
> - the data extraction;
> - the pose solver;
> - the Dolphin testing;
> - the charts, the explorer and this README.
>
> I (hi technospider here, this is the only text in this repos written by me) did pretty much nothing, and I know I have many friends
> who will get bad vibes from this. I just want to say that I get it, but that if people find the results interesting, they should 
> have full access. Much love <3
>


How far every character can move their shield bubble by tilting it in Super Smash Bros. Melee (NTSC v1.02).

The numbers come from the game's own data and the engine logic in the [doldecomp/melee](https://github.com/doldecomp/melee)
decompilation. They were then checked frame-exactly in Dolphin. All 26 selectable characters match the emulator to within
0.00001 units. Nana is identical to Popo.

**Interactive explorer:** [Melee Shield-Tilt Explorer](https://claude.ai/artifact/1yUPcEPjkd5K3EorbJDLWX). It's a private
link, so only people the owner has shared it with can open it. The same page is in the repo as
[`plots/shield_tilt_explorer_web.html`](plots/shield_tilt_explorer_web.html). GitHub doesn't render HTML, so download it and
open it in a browser.

In the explorer you can:
- pick a character;
- move a control-stick pad that snaps to the stick values the game can actually read (the dead zone and the gate
  are shown);
- set shield health and trigger pressure;
- see the tilted bubble, the hurtboxes in that pose, and how much of the body is left outside the shield. That exposure
  is measured in 3D and shows what's open to shield pokes.

Everything is computed live in the browser by a JavaScript port of the solver (`tools/plots/shieldpose.js`). It
reproduces the solver's output for every row of every character's data to within 0.00001 units. The page embeds the
per-character pose data this needs: bone rest poses, shield poses and Guard animation keyframes.

![Shield-centre reach for every character on shared axes](plots/all_characters.png)

## Reach per character

This is how far the shield **centre** moves from its untilted position at full tilt, in game units, facing right. The
bubble radius is at full health with a hard press. Characters are sorted by the area the centre can cover. Each name links
to that character's chart.

| Character | Up | Down | Forward | Back | Area covered by centre | Bubble radius |
|---|---:|---:|---:|---:|---:|---:|
| [Falco](plots/Fc.png) | 6.60 | 6.60 | 3.04 | 5.76 | 90.4 | 7.91 |
| [Fox](plots/Fx.png) | 5.76 | 5.76 | 2.66 | 5.02 | 68.8 | 7.94 |
| [Bowser](plots/Kp.png) | 3.55 | 3.04 | 3.10 | 6.18 | 49.2 | 12.40 |
| [Link](plots/Lk.png) ¹ | 4.32 | 3.72 | 3.73 | 4.00 | 47.8 | 8.15 |
| [Luigi](plots/Lg.png) | 5.00 | 4.12 | 3.12 | 3.75 | 42.3 | 7.73 |
| [Pikachu](plots/Pk.png) | 3.49 | 3.69 | 2.31 | 4.52 | 40.7 | 6.21 |
| [Zelda](plots/Zd.png) | 2.87 | 6.82 | 3.73 | 2.23 | 38.1 | 8.60 |
| [Young Link](plots/Cl.png) ¹ | 4.72 | 2.72 | 2.93 | 3.15 | 36.5 | 6.42 |
| [Popo / Nana](plots/Pp.png) | 4.59 | 3.80 | 2.98 | 3.48 | 36.0 | 7.11 |
| [Dr. Mario](plots/Dr.png) | 4.40 | 3.63 | 2.75 | 3.30 | 32.8 | 6.80 |
| [Mario](plots/Mr.png) | 4.40 | 3.63 | 2.75 | 3.30 | 32.8 | 6.80 |
| [Jigglypuff](plots/Pr.png) ² | 2.93 | 2.81 | 3.96 | 3.50 | 32.3 | 7.09 |
| [Peach](plots/Pe.png) | 2.62 | 6.23 | 3.40 | 2.04 | 31.7 | 7.85 |
| [Kirby](plots/Kb.png) ² | 2.86 | 2.75 | 3.88 | 3.42 | 31.0 | 7.78 |
| [Ness](plots/Ns.png) | 4.01 | 3.29 | 2.50 | 2.50 | 26.7 | 7.91 |
| [Donkey Kong](plots/Dk.png) ¹ | 5.16 | 2.84 | 3.03 | 0.93 | 21.4 | 10.06 |
| [Marth](plots/Ms.png) | 3.30 | 2.84 | 2.16 | 2.83 | 21.0 | 7.77 |
| [Roy](plots/Fe.png) | 3.10 | 2.67 | 2.03 | 2.66 | 18.5 | 7.30 |
| [Mewtwo](plots/Mt.png) | 2.77 | 3.24 | 2.22 | 1.42 | 17.1 | 9.34 |
| [Ganondorf](plots/Gn.png) | 4.86 | 1.94 | 3.24 | 1.08 | 16.2 | 9.32 |
| [Sheik](plots/Sk.png) | 3.55 | 2.05 | 2.03 | 2.17 | 15.5 | 9.36 |
| [Captain Falcon](plots/Ca.png) | 4.37 | 1.75 | 2.91 | 0.97 | 13.1 | 8.37 |
| [Pichu](plots/Pc.png) | 1.94 | 2.05 | 1.28 | 2.51 | 12.5 | 6.99 |
| [Samus](plots/Ss.png) | 3.96 | 1.58 | 2.64 | 0.88 | 10.8 | 8.22 |
| [Mr. Game & Watch](plots/Gw.png) | 2.03 | 1.33 | 1.53 | 2.04 | 5.8 | 6.30 |
| [Yoshi](plots/Ys.png) | – | – | – | – | 0 (no tilt) | 6.30 |

¹ A straight-forward tilt has two resting positions, depending on how the stick got there (see below).
² In game the bubble is slightly oval, up to about 15% stretched at downward angles.

The same data is in [`data/reach_summary.csv`](data/reach_summary.csv). The full per-stick positions are in `data/<code>.csv`.

![Reach summary](plots/reach_summary.png)

## Findings

- **Space animals move furthest.** Falco's shield centre travels 6.6 units up and down, and Fox's travels 5.8.
  Mr. Game & Watch's barely moves.
- **Many characters tilt very unevenly.** Zelda and Peach can drop their shield much further than they can raise it.
  Ganondorf, Captain Falcon, Samus and Donkey Kong can hardly angle it backwards at all.
- **Yoshi's shield neither tilts nor shrinks.** It stays at the same place and size whatever the stick input or shield
  health, because his shield code sets the bubble scale to 1.
- **Donkey Kong, Young Link and Link have two forward positions.** The tilt angle eases toward the stick, and at exactly
  forward it can come to rest at either 0° or 360°:
  - a fresh shield press, or reaching forward from above, rests at 0°;
  - sweeping round from below rests at 360°.
  
  Each angle picks a frame of the shield animation, and these three animations don't loop cleanly, so the two ends look
  different. Swept in from below, Donkey Kong's forward tilt barely moves the shield at all: the two resting points are
  3.0 units apart. For Young Link they're 1.5 apart and for Link 0.24.
- **Mario and Dr. Mario are identical.** Luigi's files contain Mario's shield animation, but his skeleton gives him a
  different reach.

## Per-character charts

Each chart has two panels. On the left, **where the shield can go**:
- the full-tilt centre path (thick charcoal);
- weaker tilts (sky blue);
- the untilted bubble (bluish green) and the smallest bubble just before a break (dashed orange);
- the bubble at each of the 8 stick extremes.

On the right, **the body at each extreme**: the tilted-pose hurtboxes and the bubble for each stick direction. The
colours are an Okabe-Ito set, chosen to stay readable with colour blindness.

<details>
<summary>Show every character</summary>

![Captain Falcon](plots/Ca.png)
![Donkey Kong](plots/Dk.png)
![Dr. Mario](plots/Dr.png)
![Falco](plots/Fc.png)
![Fox](plots/Fx.png)
![Ganondorf](plots/Gn.png)
![Jigglypuff](plots/Pr.png)
![Kirby](plots/Kb.png)
![Bowser](plots/Kp.png)
![Link](plots/Lk.png)
![Luigi](plots/Lg.png)
![Mario](plots/Mr.png)
![Marth](plots/Ms.png)
![Mewtwo](plots/Mt.png)
![Mr. Game & Watch](plots/Gw.png)
![Ness](plots/Ns.png)
![Peach](plots/Pe.png)
![Pichu](plots/Pc.png)
![Pikachu](plots/Pk.png)
![Popo](plots/Pp.png)
![Roy](plots/Fe.png)
![Samus](plots/Ss.png)
![Sheik](plots/Sk.png)
![Yoshi](plots/Ys.png)
![Young Link](plots/Cl.png)
![Zelda](plots/Zd.png)

</details>

## How it works

1. **Mechanics** ([`docs/MECHANICS.md`](docs/MECHANICS.md)). This covers the engine's shield-tilt maths, traced through the
   decompilation with file and line citations:
   - stick processing and the deadzone;
   - the eased angle and strength;
   - sampling the Guard animation at frame θ + 10;
   - the blend with the shield pose (a quaternion slerp);
   - HSD world matrices;
   - the bubble-size formula.
2. **Extraction** (`tools/iso_extract`, `tools/CharInfo`). This reads the fighter files from your own ISO and catalogues
   each character's shield bone, shield size and hurtboxes into [`data/characters.json`](data/characters.json).
3. **Solver** ([`tools/ShieldPose`](tools/ShieldPose/README.md)). A C# model on [HSDLib](https://github.com/Ploaj/HSDLib)
   that reproduces the pose blend in float32. It covers every stick value the game can register (8,153) plus a dense
   angle × strength sweep, and writes out the bubble centre and posed hurtboxes.
4. **Validation** (`tools/validate`). This drives Slippi Dolphin through libmelee. It holds the shield with the stick ramped
   slowly, to avoid rolls and spot dodges. It then reads the shield bone's world matrix from RAM and compares it with the
   solver. Results are in [`data/validation/PROGRESS.md`](data/validation/PROGRESS.md).
5. **Charts** (`tools/plots`). `make_plots.py` produces the static charts. `make_explorer_web.py` produces the interactive
   explorer.

## Layout
| Path | Contents |
|---|---|
| `external/` | gitignored clones: `melee` (decomp), `HSDLib` |
| `gamedata/` | gitignored files extracted from the ISO |
| `tools/iso_extract/` | Python GCM/FST reader |
| `tools/CharInfo/` | C# character-data cataloguer |
| `tools/ShieldPose/` | C# offline pose solver (references `external/HSDLib/HSDRaw`) |
| `tools/validate/` | Dolphin RAM reader, input driver, capture and comparison |
| `tools/plots/` | static charts and the interactive explorer |
| `data/` | derived CSV/JSON (the posed-hurtbox CSVs are gitignored; regenerate them with ShieldPose) |
| `plots/` | generated charts and explorer pages |
| `docs/MECHANICS.md` | engine notes with decomp citations |

## Setup
```bash
git clone --depth 1 https://github.com/doldecomp/melee external/melee
git clone --depth 1 https://github.com/Ploaj/HSDLib external/HSDLib
dotnet build external/HSDLib/HSDRaw/HSDRaw.csproj -c Release
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Then rebuild everything:
```bash
dotnet build tools/ShieldPose -c Release
dotnet tools/ShieldPose/bin/Release/net8.0/ShieldPose.dll
.venv/Scripts/python tools/plots/make_plots.py
.venv/Scripts/python tools/plots/make_explorer_web.py
```

Game files are never committed. Extract them from your own vanilla v1.02 ISO with
`tools/iso_extract/gcm_extract.py --iso <path> ...`. The Dolphin validation reads the ISO path from a gitignored
`local.json` (`{"iso": "..."}`).
