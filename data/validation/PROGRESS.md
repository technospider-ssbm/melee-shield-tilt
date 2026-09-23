# Phase 4 validation progress

## Harness
- `tools/validate/ram.py`: DME pointer chain, offsets confirmed live against
  libmelee's independently-derived GameState (position, facing, action state)
  and against `data/Fx.csv`'s untilted shield-bone position (matched to 1e-5).
  See the module docstring for the full offset table and decomp citations.
- `tools/validate/drive.py`: launches an isolated Slippi Dolphin instance via
  libmelee `Console`/`Controller` (named-pipe method, brief's option (a)).
  - dolphin-memory-engine only hooks a process literally named `Dolphin.exe`.
    Slippi's own binary is `Slippi Dolphin.exe`, so `drive.py` runs a copy of
    the whole netplay folder (minus `User/`) staged under the session scratch
    dir, with the exe duplicated as `Dolphin.exe`. This never touches
    `%APPDATA%\Slippi Launcher\netplay\User` or the real install directory.
  - `ramp_shield_toward()` ramps the main stick from neutral to the target in
    ~0.03/frame steps while holding digital L (full shield / lightshield=1),
    per technospider's note: a fast snap to a large stick value trips the
    roll/spotdodge/jump-out-of-shield smash-timers
    (`ftCo_Escape.c`, `ftCo_Jump.c`; thresholds in `docs/MECHANICS.md` section
    on smash timers, x314/x318/x31C/x320/x2A0/x70/x74). Confirmed live: an
    un-ramped run produced garbage (stuck bone positions, e.g. shield breaks
    and rolls contaminating later samples); the ramped version yields
    `Action.SHIELD` after settle for every attempted target so far (Fox, all
    reachable=True through 90°).
  - Gecko codes: only libmelee's own `GALE01r2.ini` codes are enabled
    (Extract Menu Info; Infinite Time Mode and Instant Match are present in
    the ini but not turned on by our capture.py). None touch stick or guard
    processing — checked the code listing, it's all UI/menu-state extraction.
    Slippi Dolphin's own baked-in netcode/rollback codes are unrelated to
    single-player physics. UCF was not verified to be off/on since we never
    use dashback or shield-drop; per the brief that's the only place it could
    matter and it doesn't apply here.

## Offsets confirmed
- `player_slots` @ 0x80453080, stride 0xE90 (decomp: `.bss:0x80453080`
  size 0x5760 / `Gm_Player_NumMax`(6) = 0xE90). `+0xB0` = `player_entity[0]`.
- `HSD_GObj.user_data` at `+0x2C` -> `Fighter*`.
- `Fighter.motion_id` `+0x10`, `.facing_dir` `+0x2C`, `.cur_pos` `+0xB0`,
  `.input.lstick` `+0x620/+0x624`, `.shield_health` `+0x1998`,
  `.lightshield_amount` `+0x199C`, `.mv.co.guard.x4/x8` `+0x2344/+0x2348`,
  `.parts` `+0x5E8` (array of `FighterBone`, stride 0x10, `.joint` at `+0`).
- `HSD_JObj.mtx` at **+0x44**, not +0x2C as first mis-transcribed from decomp
  (the header literally reads `/* +44 */ Mtx mtx;` — first pass misread the
  hex offset as decimal 44). Caught by live validation: TopN's world
  translation didn't match `cur_pos`/libmelee position until fixed; after the
  fix it matches to float precision, and Fox's untilted shield-bone position
  matches `data/Fx.csv`'s (angle=0, mag=0) row to ~1e-5.
- Fighter shield joint at rest (not actively guarding) is parked somewhere
  irrelevant (observed a nonsensical low position) — you must be in
  `Action.SHIELD` before reading the bone position, not just "not doing
  anything else".
- Digital L press gives `lightshield_amount = 1.0` (a *light* shield), matching
  the brief's "a digital press means ls = 1".

## Known gotchas
- Shield health drains while held (~0.3-0.5/frame observed, drain rate not
  yet correlated to tilt magnitude) and can reach 0 (shield break) if you
  hold+release too fast across many samples without letting it regen.
  `capture.py` now waits (polling every 30 frames, cap 1200) for
  `shield_health >= 55` before each hold, and detects/waits out the
  `SHIELD_BREAK_*` action states if one slips through.
- Snapping the stick straight to a large target while shielding can trigger
  roll / spotdodge / jump-out-of-shield instead of a tilt (confirmed: garbage
  runs before the ramp fix, e.g. many samples locked onto an identical wrong
  bone position — that was the shield-break/dizzy pose, not a real sample).
  Fixed with `drive.ramp_shield_toward` (~0.03/frame ramp from neutral).
  `capture.py` retries with a slower ramp (halving step, up to 4 attempts) if
  the post-settle action isn't `Action.SHIELD`, and records `reachable=False`
  for anything that still can't be reached (to report, not silently drop).

## Shield-health pin (write-only RAM exception)
technospider approved (2026-09-23) writing `Fighter.shield_health` (fp+0x1998)
= 60.0f every frame while ramping/holding shield, since health only scales
the bubble radius, not the pose/position. `tools/validate/ram.py`
`pin_shield_health()` does this; `drive.ramp_shield_toward()` calls it every
step. This is the **only** field ever written besides controller pipe input.
Confirmed live: without the pin, health drains ~0.3-0.5/frame and repeated
sampling could shield-break the character; with the pin, health reads a flat
60.0 for every sample (see `data/validation/Fx.csv`).

## Audit: no persistent writes outside scratch (technospider, 2026-09-23)
Checked after the Fox run:
- `Get-ChildItem -Recurse "%APPDATA%\Slippi Launcher\netplay" | Where LastWriteTime -gt today` -> **no results**. Nothing in the real install (Sys/, User/, exe, DLLs) was touched today.
- ISO `LastWriteTime` is 2021-10-20 (original), untouched.
- `%USERPROFILE%\Documents` has no Slippi folder at all.
- Our isolated `-u` scratch dolphin_home (under the session scratchpad, never
  committed) has its own Config/Cache/GC/Wii/etc, confirming Dolphin wrote
  only there.
- The only file created outside the scratchpad+repo was a copy of the whole
  netplay folder (minus `User/`) *into the scratchpad*, done via
  `Copy-Item` (read from the real install, written only to scratch), plus a
  renamed `Dolphin.exe` duplicate inside that scratch copy (dolphin-memory-engine
  only hooks a process literally named `Dolphin.exe`). The real install
  directory was only ever read from, never written to.

## Results so far
- **Fox (Fx): DONE.** 49/49 samples reachable (16 angles x {0.33,0.66,1.0} +
  untilted). `tools/validate/compare.py Fx`: **max position error = 0.0000,
  mean = 0.0000** (matches to displayed float precision after the health pin
  removed the confound from earlier runs, where un-pinned health caused shield
  breaks/rolls that were already filtered out by `reachable`). This is as
  strong a confirmation as the harness can give: the pose-solver's geometry,
  easing, and blend all match the live emulator exactly for Fox.
- Bowser (Kp, shield_bone_index=74), Game & Watch (Gw, shield_bone_index=51):
  queued next, same harness, not yet run.

## Next steps
1. Finish Fox capture, run `compare.py Fx`, record max/mean error here.
2. Repeat for Bowser (`Kp`, shield_bone_index=74) and Game & Watch
   (`Gw`, shield_bone_index=51) — both already have a `CODE_TO_MELEE_CHAR`
   entry in `capture.py`.
3. If time remains: Kirby (`Kb`), Yoshi (`Ys`, expect fixed bubble / no
   tilt — good sanity check), Marth, Popo.
4. Character enum caveat: `CODE_TO_MELEE_CHAR["Mt"] = "MARTH"` in
   `capture.py` is almost certainly wrong — per `HANDOFF_PROMPT.md`,
   `characters.json` code `Ms` = Marth and `Mt` = Mewtwo (labels were fixed
   in Phase 2). Fix the mapping (`Mt` -> `MEWTWO`, `Ms` -> `MARTH`) before
   ever running capture.py for those codes; not yet exercised.
