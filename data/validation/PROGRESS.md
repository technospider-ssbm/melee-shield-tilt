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

## CPU opponent contamination (found, fixed) — technospider, 2026-09-23
First Bowser run used `cpu_level=1` for the port-2 opponent (copied from the
smoke-test default). A level-1 CPU walks and attacks occasionally; several
Bowser samples near angle 0/337.5/315 took real hits (`SHIELD_STUN`,
`DAMAGE_AIR_2`, even a death/respawn). Root cause of the resulting position
errors: taking a hit can turn the fighter to face the opponent
(`facing_dir` flips). `fp->input.lstick` is raw/absolute (not
facing-relative; MECHANICS.md's `theta = atan2(y, x*facing)` multiplies by
facing separately), but the pose-solver's `data/<code>.csv` was generated
assuming `facing = +1` throughout. So a facing-left sample driven with the
same raw stick target actually settles to a *mirrored* effective angle
(confirmed: a `sx=80,sy=0` sample taken while facing left settled to
`guard_x8=190` = 10+180°, and its bone position matched the solver's
`angle=180` row exactly, not `angle=0`) — `compare.py`'s nearest-stick match
doesn't correct for this, so those rows produced large (4-9 unit) false
errors. Fixed two ways:
1. `drive.py`: port 2 is now `cpu_level=0` (a "human" pipe controller we
   never send input to after character select, so it just stands still) —
   not a real CPU at all. A level-1 CPU is not reliable for this ("they
   still walk and attack sometimes").
2. `capture.py`: a sample is only accepted if the action is `Action.SHIELD`
   **and** `ram.get_facing_dir(0) > 0` at settle end; otherwise it retries
   from neutral with a slower ramp, same as an action-state failure.

The first Bowser run (`data/validation/Kp.csv` as originally written) is
being redone with the fix rather than patched in place, since so few samples
were affected that a full clean rerun was simpler than partial-resume logic.

## Results so far
- **Fox (Fx): DONE.** 49/49 samples reachable (16 angles x {0.33,0.66,1.0} +
  untilted). `tools/validate/compare.py Fx`: **max position error = 0.0000,
  mean = 0.0000** (matches to displayed float precision after the health pin
  removed the confound from earlier runs, where un-pinned health caused shield
  breaks/rolls that were already filtered out by `reachable`). This is as
  strong a confirmation as the harness can give: the pose-solver's geometry,
  easing, and blend all match the live emulator exactly for Fox.
- **Bowser (Kp): DONE.** 49/49 reachable, **max/mean position error = 0.0000**
  after the CPU-opponent/facing fix above (first run had 6/49 rows with
  4-9 unit errors purely from CPU-inflicted facing flips; fully traced and
  fixed, not a pose-solver or harness bug — see the section above).
- **Game & Watch (Gw): DONE.** 49/49 reachable, **max/mean position error =
  0.0000**, no retries needed at all (clean run start to finish). This is a
  good extra confirmation since G&W's shield bone does *not* hang under
  TransN (per HANDOFF_PROMPT.md's Phase-3 watch-out); the pose-solver's
  alternate parent-chain handling for that case checks out live too.
- **Yoshi (Ys): attempted, blocked, root cause not found (2 attempts spent,
  per instruction).** Diagnostic script (`scratchpad/diag_ys.py`, not
  committed): character select is confirmed correct
  (`gs.players[1].character == Character.YOSHI`); the fighter falls in
  normally (`ENTRY_END` -> `FALLING` -> `LANDING`) with `lstick == (0, 0)`
  the whole time (main stick genuinely neutral, our tilt_analog_unit(0,0)
  is reaching the game correctly) and `facing_dir == 1.0` throughout; then
  on the landing frame it settles into `Action.NEUTRAL_B_CHARGING` and
  **stays there indefinitely**, with `guard_x4` pinned at `0.0` and
  `guard_x8` pinned at a constant `1.05` the entire time (never eases, never
  matches the `x4=0,x8=10` baseline every other character shows at rest).
  This is despite `controller.press_button(BUTTON_L)` being sent every
  frame from before the character even lands.
  - **Attempt 1:** hypothesized stale menu-navigation input carrying into
    the match (the pipe protocol is stateful — a `PRESS` stays held until an
    explicit `RELEASE`, and `drive.start()` never cleared controller1's
    state after CSS/stage-select, only controller2's). Added
    `controller1.release_all()` right after the menu loop in `drive.py`
    (harmless for the other 5 characters, keep it either way).
  - **Attempt 2:** reran the same diagnostic with the fix in place — **no
    change**, identical output down to the exact `x8=1.05` constant.
  - **Not yet explained:** why L held from before landing doesn't produce
    `Action.SHIELD`, and specifically why the landing frame goes to
    `NEUTRAL_B_CHARGING` (a state that implies `B` is held, but we never
    send `B` and `lstick`/`facing` both read as expected — no evidence of a
    stray input on the *stick*, only a mystery on the *button* side, or
    possibly on Yoshi's `mv.co.guard` fields being repurposed/not written by
    `ftyoshiguard.c` the same way as the shared `ftCo_Guard.c` path other
    characters use — the constant `x8=1.05` (not `10.0`) hints the guard
    union might not even be what's active for Yoshi here, i.e. this could
    be a real character-specific action-state quirk rather than a stuck
    button. Not confirmed either way within the 2-attempt budget.
  - **Next steps for a future session:** (a) verify manually/by controller
    log whether `B` is truly never sent (log the raw pipe commands written,
    not just our own belief about what we sent); (b) check whether
    `Action.NEUTRAL_B_CHARGING`'s raw ID is being systematically
    misdecoded by libmelee for Yoshi's custom action-state table
    (`ftyoshiguard.c`) rather than actually being "neutral B charging"; (c)
    try holding L starting from a fully-idle grounded state (wait several
    seconds after landing with no input at all) instead of pressing L while
    still airborne/landing, in case Yoshi's shield-entry requires being
    already grounded and idle first. `data/validation/Ys.csv` was not
    produced/committed (would be all `reachable=False`).
- **Kirby (Kb): DONE.** 49/49 reachable, **max/mean position error = 0.0000**.
  The "part-index -> joint-index remap" concern above turned out to be a
  false alarm for RAM reads specifically: `fp->parts[]` in the running game
  is indexed by **part** (not joint) already, i.e. `parts[57].joint` (part
  57 = the shield part) directly gives the correct `HSD_JObj*` for joint 44
  — confirmed against `data/Kb_meta.json`'s `part_to_joint[57] == 44` and by
  the exact position match. The part/joint distinction only matters when
  walking the *animation/pose* data directly (which is what the offline
  pose-solver and `data/Kb_meta.json`'s `part_to_joint` table are for); the
  live `parts[]` array the game itself maintains is already part-indexed
  the same way `characters.json`'s `shield_bone_index` is, so no code change
  was needed beyond what Fox/Bowser/G&W already did.
  - **Ellipsoid check** (`ram.py` now also returns `axis_scale`, the column
    norms of the shield joint's 3x3 world-matrix submatrix — exact
    semi-axis lengths since the whole parent chain is `classical_scale`):
    live axis_scale ranged **7.05 - 8.12** across the 49 samples, live
    anisotropy `(max-min)/mean` ranged **0.0 - 0.138**. `data/Kb_meta.json`
    predicts `radius_full` about 7.78 and `max_anisotropy` about 0.152 (from
    its own, denser offline sweep) — live max anisotropy is a bit lower
    only because our 16-angle grid doesn't happen to sample the exact
    extremum stick value; same order of magnitude and consistent with the
    predicted ellipsoidal (not spherical) bubble.
- **Marth (Ms): DONE.** 49/49 reachable, **max/mean position error = 0.0000**,
  no retries. Spherical bubble (`axis_scale` constant 7.7429, aniso 0.0000
  throughout) as expected for a character without a non-uniform parent
  scale chain.
- **Popo (Pp): DONE.** 49/49 reachable, **max err = 0.0074, mean = 0.0002**
  (not a perfect 0.0000 like the others, but negligible — 2 of 49 rows,
  `angle=337.5` at `mag=0.33` and `mag=0.66`, off by 0.003-0.008 units on a
  ~7-unit-radius bubble, both in the z-component only). Spherical bubble
  (`axis_scale` constant 7.0839, aniso 0.0000). Not investigated further
  given the size (<0.1% of scale) — plausibly a keyframe-boundary rounding
  edge case in the offline solver rather than a real mismatch, but flagged
  here rather than silently rounded away.

## Summary table

| Char | code | samples | reachable | max err | mean err |
|------|------|---------|-----------|---------|----------|
| Fox | Fx | 49 | 49/49 | 0.0000 | 0.0000 |
| Bowser | Kp | 49 | 49/49 | 0.0000 | 0.0000 |
| Game & Watch | Gw | 49 | 49/49 | 0.0000 | 0.0000 |
| Kirby | Kb | 49 | 49/49 | 0.0000 | 0.0000 |
| Marth | Ms | 49 | 49/49 | 0.0000 | 0.0000 |
| Popo | Pp | 49 | 49/49 | 0.0074 | 0.0002 |

All three characters match the pose-solver's `data/<code>.csv` exactly
(to displayed float precision) once the harness bugs (JObj mtx offset,
CPU-opponent facing flips) were fixed. No pose-solver discrepancies found
for these three characters.

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
