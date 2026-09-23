# Shield tilt mechanics (NTSC v1.02)

Engine notes taken from doldecomp/melee @89c2401 (`external/melee`), cross-checked against the extracted
vanilla data in `gamedata/`. Paths are relative to `external/melee/src/` unless stated otherwise.
Anything unresolved is marked **UNKNOWN**, together with what would resolve it.

**Trust level.** Every source file used here is `Object(Matching, ...)` in `configure.py`
(ftCo_Guard.c l.698, ftanim.c l.656, ftparts.c l.658, ftdata.c l.670, fighter.c l.655, lb_00B0.c l.583,
lb_00CE.c l.584, lbanim.c l.603, lbcollision.c l.580, jobj.c l.1904, aobj.c l.1899, fobj.c l.1902,
mtx.c l.1913, quatlib.c l.1923, controller.c l.1910, dolphin/pad/pad.c l.1823, ftyoshiguard.c l.990).
The code therefore compiles to the original bytes. Struct field *types* and *names* can still be wrong,
though; see section 3.4 (`ftData_x20`). The only `@todo` markers in the relevant code are in
`ftCo_Guard.c` (`ftCo_80091AD8` l.86, `ftCo_80092F2C` "What happens to this value?" l.693, `ftCo_800932DC` "Fake." l.747,
`ftCo_800939B4`/`ftCo_80093A50` shared-code notes l.916/936, `ftCo_GuardOff_IASA` l.605). None of them touch the tilt path.

Glossary: `fp` = `Fighter*`. `parts[i].joint` = the live skeleton JObj. `parts[i].x4_jobj2` = the
"interpolation" skeleton JObj (`fp->x8AC_animSkeleton` tree, ftparts.c:457-498 `ftParts_8007462C`).
`SP` = the ShieldPose joint tree. `A(f)` = the Guard figatree evaluated at frame `f`.

---

## 1. Per-frame tilt state update: `ftCo_80091BC4` (ft/kinds/ftCommon/ftCo_Guard.c:130-175)

State (fighter-motion vars, `ft/kinds/ftCommon/types.h:149-162`):
`guard.x4` = tilt weight (fp+0x2344), `guard.x8` = tilt anim frame (fp+0x2348), both `float`.
They are initialised in `ftCo_800921DC` (ftCo_Guard.c:305-333): `x8 = 10`, `x4 = 0`.
`Fighter_ChangeMotionState` does **not** clear `fp->mv` (no reference in fighter.c), so the values
survive GuardOn -> Guard -> GuardSetOff -> Guard.

Exact update (single-precision floats; `K = p_ftCommonData->x44C`):

```
rad = lb_8000D008(ls.y, ls.x * facing_dir)       // custom atan2(y, x), lb/lb_00CE.c:106-151
if rad < 0: rad += 2*(float)M_PI
deg = rad * 57.29577951f                         // MTXRadToDeg, libs/dolphin/include/dolphin/mtx.h:60
deg = clamp(deg, 0, 359)
g   = x8 - 10
d   = deg - g
if d > 180: d -= 360  elif d < -180: d += 360    // shortest path; exactly +/-180 is NOT wrapped
s   = d*K + g
g   = (s > 360) ? s - 360 : (s < 0 ? s + 360 : s) // g in [0, 360]; exactly 360 is kept
x8  = 10 + g
m   = min(1, sqrtf(ls.x^2 + ls.y^2))
x4 += K * (m - x4)
```

`ls` is `fp->input.lstick[0]` after the fighter deadzone (section 5). `lb_8000D008(y, x)` is:
if |x| < 1e-5: return 0 when |y| < 1e-5, else +/-pi/2 by sign(y). If x > 0: `atanf(y/x)`. If x < 0:
`sign(y) * (pi - atanf(|y/x|))`, with sign(0) = +1, so (x<0, y=0) gives pi. This is an ordinary atan2.

Angle convention: 0 deg = toward facing direction, 90 = up, 180 = backward, 270 = down
(x is multiplied by `facing_dir`).

**Stick at neutral**: `lb_8000D008(0,0)` returns 0, so the *angle also eases toward 0 deg* (forward)
while `x4` eases toward 0. Releasing the stick does not freeze the angle.

Value read from PlCo.dat: `K = x44C = 0.5`. After n frames with the stick held,
angle error = D0 * 0.5^n and `x4 = x4_0 + (m - x4_0)(1 - 0.5^n)`.

### 1.1 Does x8 settle exactly, and is frame = angle+10 exact?
* The frame the pose code uses is literally `x8 = 10 + g`, where g is the eased angle in degrees
  (1 animation frame per degree). The range of `x8` is [10, 370]. Frame 10 is 0 deg. Frame 370 is 360 deg,
  which can only occur transiently, for example while easing across 0 deg from below.
* The settled value is a fixed point of `g <- g + 0.5(s - g)`. In float arithmetic it converges to
  within a few ULP of `deg` (about 3e-5 deg near 300) and then stays there. The -10/+10 round-trip each
  frame is also ULP-level. **For the solver, settled `x8 = 10 + deg` is exact to about 1e-4 deg.**
  Whether the compiler used `fmadds` (one rounding) or `fmuls`+`fadds` only changes the last ULP.
  It is **UNKNOWN** without disassembly, and it does not matter for ranges.
* The `[0, 359]` clamp **never binds for real controller input.** Angles in (359, 360) would need
  a tiny negative y. The per-axis deadzone (section 5) makes |y| >= 23/80 or y = 0, so the smallest
  below-forward angle reachable is about -16 deg.
* Settled `x4 = min(1, |ls|)` exactly (float halving reaches 1.0 exactly after about 25 frames by
  round-to-even). For many diagonal notches `|ls| < 1`, so **the settled blend weight is the stick
  magnitude, not 1.** With the stick released, x4 halves each frame and reaches exactly 0 only
  after about 150 frames (denormal underflow, or flush-to-zero if Gekko NI mode is set: **UNKNOWN**,
  harmless).

---

## 2. Animation index 38

`ftData_80085E50(fp, 38)` (ft/ftdata.c:1785-1838) indexes the fighter's **action (subaction)
table** `fp->x24[]`, the same table `Fighter_ChangeMotionState` uses via `anim_id`
(fighter.c:1248-1263). It is *not* a motion-state (`ftCo_MS_*`) id. The index enum is
`ftCo_Submotion` (ft/kinds/ftCommon/forward.h:633-675): `ftCo_SM_DeadUpFallHitCamera = 0` at l.635,
so l.672-675 give **37 = GuardOn, 38 = Guard, 39 = GuardOff, 40 = GuardDamage**.

Verified in data (FighterData+0x0C action table, 0x18-byte entries): entry 38 is
`PlyFox5K_Share_ACTION_Guard_figatree`, `PlyMars5K_..._Guard_...`, `PlyKirby5K_..._Guard_...`, and so on.
**Every Guard figatree checked has `frames = 370.0`, `type = 1`, `flags = 0`** (Fox, Marth, Kirby,
Peach, Popo, Mario). So there is **no dedicated "tilt" animation**. The regular *Guard* subaction is
authored as a 360-degree sweep over frames 10..370. The Guard motion state itself never plays it as a
normal animation (see section 3.1).

Fetch mechanics (ftdata.c:1785-1838): entry `x14` is the data source (ARAM offset if < 0x80000000,
else a RAM address). It is loaded into the fighter's *secondary* anim buffer `x5A0` and parsed, and the
public root is cached in `fp->x598`. It is re-loaded only when `x14 != fp->x5A8`. The main motion
anim uses a separate buffer (`x59C/x590/x5A4`, `ftData_80085CD8`, ftdata.c:1732-1783).

**Ice Climbers**: `ftData_80085FD4` (ftdata.c:1840-1849). For Nana, if the slot is not Demo and her own
entry has `x14 == 0`, **Popo's** entry is used. In PlNn.dat entries 37-40 are all empty (checked),
so Nana tilts with Popo's Guard figatree. `ftData_80086060` (ftdata.c:1851-1862) lets her copy Popo's
already-loaded buffer.
**Yoshi**: entries 38 and 40 are empty in PlYs.dat. This is consistent with Yoshi never calling the tilt code (section 6).

GuardOn length: `fp->x2E8 = frames(ftData_80085E50(fp, 0x25))` (fighter.c:843), i.e. the GuardOn
figatree length (Fox 8, Kirby 7 frames).

---

## 3. The pose blend: `ftCo_80091E78(gobj, arg1)` (ftCo_Guard.c:214-248)

### 3.1 Call sites / arg1
* Whole body runs only if `fp->reflecting || fp->x221B_b0` (shield or powershield active).
* `ftCo_800921DC` (shield start) calls it with `arg1 = 0` (l.331).
* `ftCo_GuardOn_Anim` calls it with `arg1 = x0 / x2E8` (l.447), where `x0` is the frame counter,
  incremented first. The same happens for GuardReflect (powershield) via `ftCo_GuardOn_Anim_inline` (l.1039).
* When `x0 >= x2E8`, it switches to Guard (`ftCo_80092908`, l.506-527) and calls `arg1 = 1`.
  `ftCo_Guard_Anim` calls `arg1 = 1` every frame (l.529-537).
* GuardOn, Guard and GuardReflect are entered with `Ft_MF_SkipAnim` (l.386, 509, 940). In
  `Fighter_ChangeMotionState` that sets `anim_id = -1`, which **removes all AObjs from both the live
  skeleton and x8AC** (fighter.c:1352, 1356-1361). So no regular animation drives the body while shielding.
  The live joints hold whatever this function writes.
* **GuardSetOff (shieldstun) does NOT call it.** `ftCo_80092F2C` (l.661-716) enters
  `ftCo_MS_GuardSetOff` with `Ft_MF_None`, so subaction 40 *GuardDamage* plays as a normal animation,
  with the blend frames from the fighter's `x28` table. The tilt state (x4, x8) is kept and
  re-applied instantly (`arg1 = 1`) when stun ends (`ftCo_800928CC_inline_arg`, l.781-809).
  **UNKNOWN**: the exact bubble position during shieldstun, since that depends on the GuardDamage anim and its blend.
  Verify in emulator RAM (shield pos, section 4.4).
* GuardOff (release) also plays its own anim (subaction 39, `Ft_MF_None`, l.587). No tilt.

### 3.2 Exact order of operations
```
if x4 != 0:
  J2 = x8AC tree (interp skeleton; parts[i].x4_jobj2)
  (a) ftAnim_8006F4C8(fp, do_blending=true, Guard_figatree)     // attach fresh AObj/FObjs to J2
  (b) ftAnim_80070710(J2root, x8) = HSD_JObjReqAnimAllByFlags(J2root, 1, x8)   // request frame x8
  (c) ftAnim_8006FB88(fp, TransN, costume_joint->child)         // reset J2 SRT to COSTUME REST pose
  (d) HSD_JObjAnimAll(J2root)                                   // write tracked channels at frame x8
  (e) if x4 < 1: ftAnim_80070108(fp, TransN, 1-x4, x4, SP_root->child)  // blend J2 toward SP
  (f) if arg1 < 1: ftAnim_8006FE9C(fp, TransN, arg1, 1-arg1)    // live = lerp(live, J2, arg1)
      else:        ftAnim_8006FF74(fp, TransN)                  // live = copy(J2)
else (x4 == 0):
  if arg1 < 1: ftAnim_80070010(fp, TransN, arg1, 1-arg1, SP_root->child) // live = lerp(live, SP, arg1)
  else:        ftAnim_8006FA58(fp, TransN, SP_root->child)                // live = SP
then: parts[shieldBone].joint.scale = (b,b,b), b = bubble scale (section 7)   // l.241-244
      efLib_SetParamAlpha (lightshield alpha, cosmetic)
```

Details, with the lines that establish each step:

* **(a)** `ftAnim_8006F4C8` (ftanim.c:594-636) walks the figatree node list. Node k goes to the k-th
  part that has `flags_b1` (the part exists). Parts with `flags_b2` (attached extras such as Kirby hats)
  are skipped unless their `ftParts_8007506C` bits are in `x594_bits`. `x594_bits` is 0 here, because
  SkipAnim zeroes `x594_s32`, fighter.c:1357. Parts with `flags_b0` (dynamics) or `flags_b5`
  (part-anim override) are not animated. `lbAnim_8001E6D8` (lb/lbanim.c:89-112) removes any old AObj,
  allocates a new one (`end_frame = tree->frames = 370`, rewind 0, flags = `tree->flags` = 0, so no
  loop), and builds one FObj per track. It sets `JOBJ_CLASSICAL_SCALE` on the J2 joint because
  `tree->type & 1`. That flag stays on J2 and is not copied to live joints.
* **(b)** `HSD_AObjReqAnim` (baselib/aobj.c:91-105) sets `curr_frame = x8` and `AOBJ_FIRST_PLAY`.
  `HSD_FObjReqAnim` (baselib/fobj.c:54-72) sets `fobj->time = track.startframe + x8`. In
  `HSD_AObjInterpretAnim` (aobj.c:121-172) the first play uses rate 0, so channels are evaluated at
  exactly frame x8. If `end_frame (370) <= x8` the AObj is stopped *after* being evaluated. The
  AObj is re-created every frame, so there is no hidden state. Interpolation is standard HSD FObj:
  CON, LIN, SPL0/SPL/SLP (Hermite `splGetHelmite`) and KEY (fobj.c:336-388). Replicate with HSDLib's FOBJ player.
* **(c)** `ftAnim_8006FB88` (ftanim.c:830-858) walks the **costume** Joint tree (`fp->x108_costume_joint`,
  the costume model root, fighter.c:570-572) from `->child` (TransN) in preorder. It uses
  `ftAnim_GetNextJointInTree` (ftanim.c:94-127), which also visits TransN's siblings. The part index
  starts at 1 and skips indices where `ftParts_8007506C(kind,i) != 0` (optional slots, section 6). Per joint:
  * part == ItemHold bone (`ft_data->x8->x10`): rot+trans from Joint (`lb_8000B5DC`, lb_00B0.c:150-163).
    If dynamics (`b0`), trans only (`lb_8000B760`). Then scale = 1/model_scaling
    (`ftCommon_8007F6A4`, ftcommon.c:1434-1441).
  * dynamics bone (`b0`): scale+trans (`lb_8000B6A4`, l.165-175), quaternion flag cleared.
  * otherwise, unless `b5`: full SRT (`lb_8000B4FC`, lb_00B0.c:134-148). Euler rotation, quaternion flag cleared.
  So **every channel the Guard figatree does not animate takes the costume model's rest value.**
* **(d)** `JObjUpdateFunc` (jobj.c:351-529) writes ROTX/Y/Z (Euler radians), TRAX/Y/Z and SCAX/Y/Z
  (scale clamped to |s| >= 1e-3) into J2.
* **(e)** `ftAnim_80070108` (ftanim.c:977-999) walks the **ShieldPose** tree from `SP_root->child`,
  with the same part-index rule as (c). For each part with `!b0 && !b5`:
  * if `flags_b4`: `lb_8000B4FC(J2, SPjoint)`. **J2 := SP SRT verbatim, no blend.** `flags_b4` is set on
    `GetBoneIndex(TransN)` and `GetBoneIndex(0x35)` for every fighter (ftparts.c:691-692), and again on
    `parts[1]` for Mewtwo (ftMewtwo/ftmewtwo.c:295). Part 0x35 = 53 has no name in the decomp enum
    (ft/forward.h:258-314 ends at TransN2 = 52): **UNKNOWN name**.
  * else `lb_8000C868(SPjoint, J2, J2, t = 1-x4, t_inv = x4)` (lb_00B0.c:560-641), in pseudo-code:

```
J2.T = SP.T*(1-x4) + J2.T*x4
J2.S = SP.S*(1-x4) + J2.S*x4
if J2 not quaternion and |SP.R.e - J2.R.e| <= 1e-4 for e in x,y,z:
    J2.R = SP.R (Euler), clear USE_QUATERNION                 // near-equal shortcut
else:
    qa = EulerToQuat(SP.R); qb = J2 quaternion or EulerToQuat(J2.R)
    if |qa-qb|^2 > |qa+qb|^2: qb = -qb                         // hemisphere fix
    J2.R = slerp(qa, qb, x4); set USE_QUATERNION               // HSD_QuatLib_8037EF28
```

  **Direction:** ShieldPose has weight `1 - x4` and the Guard anim frame has weight `x4`.
  `x4 = 1` means pure tilt anim and `x4 -> 0` means pure ShieldPose.
  `HSD_QuatLib_8037EF28(p, q, out, t)` (baselib/quatlib.c:148-199) is slerp with `t=0 -> p`,
  `t=1 -> q`. It falls back to lerp if `1-cos < 1e-10`, and has a special antipodal branch.
  * Step (e) is **skipped entirely when x4 == 1**. Then flags_b4 joints (TransN) keep the anim/costume value
    instead of the SP value, so there is a potential discontinuity at |stick| = 1 if costume-rest TransN != SP TransN.
    **UNKNOWN**: compare Pl??Nr.dat TransN with ShieldPose TransN.
* **(f)** `ftAnim_8006FF74` (ftanim.c:942-952): for every part i from 1 to `parts_num-1` with
  `b1 && !b0 && !b5`: `lbCopyJObjSRT(J2, live)` (lb_00B0.c:547-558). This copies rotate (Euler *or*
  quaternion), scale and translate, copies the `USE_QUATERNION` flag, and marks the matrix dirty.
  `ftAnim_8006FE9C` (ftanim.c:925-940) used during GuardOn: b4 parts copy; others
  `lb_8000C490(J2, live, live, arg1, 1-arg1)` (lb_00B0.c:461-545): `live.T = J2.T*arg1 + live.T*(1-arg1)`
  (same for S), `live.R = slerp(q(J2), q(live), 1-arg1)`. So during GuardOn the live pose moves
  recursively toward the tilt pose. It is fully the tilt pose once in Guard.
* x4 == 0 path: `ftAnim_80070010` (ftanim.c:954-975) = `lb_8000C868(SP, live, live, arg1, 1-arg1)`
  (b4: `lb_8000B4FC(live, SP)`). `ftAnim_8006FA58` (ftanim.c:802-828) = like (c) but writes SP into the
  **live** joints (ItemHold special case included).

**Which joints**: TopN (part 0) is never touched by any of these walkers (they start at `FtPart_TransN`
= 1). Every other joint in the SP tree is included, TransN included, except dynamics (`b0`) and
part-anim-override (`b5`) bones. Attached extra parts (Kirby hats, Link item joints) are *not* in the
SP/costume Joint trees. They are still copied J2 -> live by (f), but they are never on the shield-bone chain.

### 3.3 Settled pose for the solver (Guard state, arg1 = 1)
For a stick with settled angle theta (deg) and magnitude m = min(1, |ls|):

```
f = 10 + theta
for each joint j in SP preorder starting at TransN (skip b0/b5 parts):
    A_j = CostumeRest_j, then overwrite channels that have Guard-figatree tracks with FObj(f)
          (ItemHold bone: A_j.scale = 1/model_scaling unless a scale track exists)
    if m == 0:   L_j = SP_j                                     // x4 == 0 branch
    elif m == 1: L_j = A_j                                      // no blend at all
    elif b4(j):  L_j = SP_j                                     // TransN and part 53
    else:        L_j.T = lerp(SP_j.T, A_j.T, m)
                 L_j.S = lerp(SP_j.S, A_j.S, m)
                 L_j.R = slerp(q(SP_j.R), q(A_j.R), m), or SP_j.R if all |dEuler| <= 1e-4
TopN: T = cur_pos, R = (0, facing*pi/2, 0), S = (ms, ms, ms)     // section 4.4
```

The shield-bone scale is then overwritten with the bubble scale. It does not affect the centre.

### 3.4 What `ft_data->x20->x0[2]` really is
The decomp declares `ftData_x20 { HSD_Joint** x0; f32 x8; }` (ft/types.h:703-706). The data says
otherwise: FighterData+0x20 points to a 4-byte container whose +0 is a pointer to **one HSD_Joint, the
root (TopN) of a complete skeleton pose tree**. This matches HSDLib `SBM_ShieldModelContainer.ShieldPose`
(`TrimmedSize = 4`). `x0[2]` indexes 32-bit words, so it reads `root + 0x8`, which is
`HSD_Joint.child` (sysdolphin/baselib/jobj.h:127-142, `child` at +8). **`x0[2]` == `ShieldPose->child` ==
the TransN joint.** This is the same thing `ftCo_80091E78` does with `fp->x108_costume_joint->child` in (c).
Checked in data: the Fox SP root (PlFx.dat data+0x9960, flags 0x8, identity SRT) has child 0x99A0
(flags 0x8), and that child has a `next` sibling. The tree has 73 joints, matching parts_num 73.
The single joint HSDLib models is the root pointer. The decomp's field type is wrong but compiles to
the same instructions.

---

## 4. Shield-bone world position

### 4.1 Bone and collider
* Shield bone = `ft_data->x8->x11` (HSDLib `SBM_PlayerModelLookupTables.ShieldBone`, byte 0x11;
  `x10` = ItemHoldBone). The collider is registered by `ftColl_8007B1B8` (ft/ftcoll.c:3133-3145) from
  the AbsorbDesc built in `ftCo_80092450_inline` (ftCo_Guard.c:259-266): `bone = parts[x11].joint`,
  `offset = (0,0,0)`, `size = 1`.
* Position: `lbColl_80007BCC` (lb/lbcollision.c:1577-1629) calls
  `lb_8000B1CC(bone, &offset, &pos)` (lb_00B0.c:97-132). With a zero offset and a parent present that is
  `HSD_JObjSetupMatrix(bone)` followed by `pos = bone->mtx[0..2][3]`, the **world translation column**.
  It is cached once per frame (`skip_update_pos`, reset by `ftColl_8007AEE0` in the Phys callbacks,
  ftcoll.c:3035-3038). If `x34_scale.z != 1`, `pos.z = cur_pos.z`.
* The hit test uses the bone's full world matrix with radius `size = 1` (`lbColl_80006E58`,
  lbcollision.c:1121+). So world radius = bubble scale x parent-chain scales.
  **UNKNOWN (not needed for position)**: exact ellipsoid handling.

### 4.2 The "translation reset" is transient
`ftCo_800921DC` zeroes the translation of `parts[x11].joint` (ftCo_Guard.c:329-330). Yoshi does the same in
ftyoshiguard.c:67-68 and 344-345. But (f) copies J2's translation into the live shield bone:
with arg1 = 0 the value is left alone, every later GuardOn frame lerps it, and every Guard frame overwrites it.
**During Guard the shield bone's local T is the blended value L.T, not zero.** The Guard figatree
animates the shield-bone translation directly. Track types on the shield-bone node in subaction 38
(1/2/3 = ROTX/Y/Z, 5/6/7 = TRAX/Y/Z):
Fox, Falco, Marth, Roy, Peach, Zelda, Sheik, Samus, Ganon, Falcon, DK, Bowser, Pikachu, Pichu, Mewtwo,
Link, YLink: [5,6,7]. Mario, Luigi, Doc, Popo, Ness, Puff, Kirby: [6,7]. G&W: [1,2,3,5,6,7].
The SP translations of the shield bone are non-zero (for example Fox (-0.443, 1.5, 2.232)).
**Bubble centre = W_parent(shieldBone) * L_shield.T.** The bone's own R and S do not affect it.

### 4.3 World matrix construction (HSD JObj)
`HSD_JObjMakeMatrix` (sysdolphin/baselib/jobj.c:138-195):

```
// accumulated scale "scl" (may be NULL)
if flags & JOBJ_CLASSICAL_SCALE (0x8): scl_j = parent.scl (copy) if parent has scl, else NULL
else:                                  scl_j = S_j * parent.scl (componentwise), or S_j if parent has none
P = diag(parent.scl) if parent has scl, else I
if flags & JOBJ_USE_QUATERNION (0x20000): M_j = T(t) * inv(P) * Rq(q) * P * S(s)    // HSD_MtxSRTQuat, mtx.c:412-434
else:                                     M_j = T(t) * inv(P) * Rz*Ry*Rx * P * S(s)  // HSD_MtxSRT, mtx.c:362-410
W_j = W_parent * M_j                                                                  // PSMTXConcat, jobj.c:183-185
```

The Euler order is **R = Rz(z) * Ry(y) * Rx(x)** acting on column vectors (`HSD_MkRotationMtx`,
mtx.c:323-355: m[2][0] = -sinY, m[0][0] = cosY*cosZ). `EulerToQuat` (quatlib.c:120-146) uses the same ZYX
convention, so the quaternion path and the Euler path give the same rotation.
If every joint on the chain has CLASSICAL_SCALE, scl stays NULL and `M_j = T*R*S`. The SP joints
all carry flags 0x8. The **live** joint flags come from the costume model (`HSD_JObjLoadJoint`,
fighter.c:574). Main anims can also set or clear them (`lbAnim_8001E6D8`/`8001E7E8` on `parts[].joint`).
**UNKNOWN**: confirm the costume (Pl??Nr.dat) flags on the shield chain. IK and RObj constraints
(`HSD_JObjSetupMatrixSub`, jobj.c:1386+) are not expected on the TopN-TransN-XRotN-YRotN chain,
but that is **UNKNOWN** until the costume flags are read.

### 4.4 TopN, facing, parent chains, RAM hooks
* `TopN` = `GET_JOBJ(gobj)` = `parts[0].joint`. Its translation is set to `fp->cur_pos` every frame
  (fighter.c:2492/2516/2544/2549, collision phase). Its rotation is set to `(0, facing_dir*pi/2, 0)` on every
  motion change (fighter.c:1175-1177). Scale is set by `Fighter_UpdateModelScale` (fighter.c:213-230):
  `(x34_scale.z != 1 ? x34_scale.z : ms, ms, ms)` with `ms = x34_scale.y * co_attrs.model_scaling`
  (ftcommon.c:1429-1432; attribute +0x8C). Normally x34_scale = (1,1,1).
* Facing is therefore a **rotation about Y by +/-90 deg**, not a mirror matrix. With v = a vector in
  TopN-child space: world x = facing*ms*v_z, world y = ms*v_y, world z = -facing*ms*v_x
  (plus a residual of about 4e-8 from cos((float)pi/2)). The angle is also measured with `x*facing`.
  Together these make the **(x, y) offset of the bubble from cur_pos an exact mirror** between facings,
  for the same stick angle relative to facing. The z offset is generally non-zero.
* Parent chains observed in the SP trees (joint preorder indices, after the part-to-joint mapping in
  section 6): most fighters use shield -> 3 (YRotN) -> 2 (XRotN) -> 1 (TransN) -> 0 (TopN).
  **Mewtwo (66 -> 4 -> 3 -> 2 -> 0) and G&W (51 -> 4 -> 3 -> 2 -> 0) do not have TransN as an ancestor.**
* RAM hooks for emulator checks (decomp layout, ft/types.h): `mv.co.guard.x4/x8` at fp+0x2344/0x2348,
  `input.lstick[0]` at fp+0x620, `shield_health` fp+0x1998, `lightshield_amount` fp+0x199C,
  `shield_hit` (HitResult) at fp+0x19C0, with `pos` expected at +0x8 (**verify**: bitfield padding).

---

## 5. Stick processing (what `fp->input.lstick[0]` holds)

1. SDK `PADSetSpec(5)` selects `SPEC2_MakeStatus` (gm/gmmain.c:45; libs/dolphin/src/dolphin/pad/pad.c:787-803,
   898-961). This subtracts 128 from the raw byte, applies `ClampS8` against the calibration origin, then subtracts
   the origin (pad.c:874-888). The result is an s8 per axis.
2. `HSD_PadClamp` runs `HSD_PadClampCheck3(x, y, shift=1, min=0, max=80)` (sysdolphin/baselib/controller.c:171-191,
   193-215; parameters from gm/gmmain.c:47-51): `r = |(x,y)|`; if `r > 80`: `x = (s8)(x*80/r)`,
   `y = (s8)(y*80/r)` (float to s8 **truncation**). `min = 0`, so there is no radial deadzone.
3. `HSD_PadScale`: `nml = s8 / 80` (controller.c:290-302, `scale_stick = 80`).
4. `Fighter_procInput` (fighter.c:1779-1990): `lstick[0] = nml` (CPU players use `ftCo_GetCpuLStickX/Y`,
   l.1804-1806). Then a **per-axis** deadzone: `if |x| <= p_ftCommonData+0x0 then x = 0` and
   `if |y| <= +0x4 then y = 0` (l.1843-1853). Both are 0.28 in PlCo.dat, so |k| <= 22 becomes 0 and |k| >= 23 is kept
   (22/80 = 0.275, 23/80 = 0.2875).
   So every component is `k/80` with k in {0} or {+/-23..+/-80}, and |(kx,ky)| <= 80 after truncation.
   `lstick[1]` holds the previous frame's value.
5. Smash timers (fighter.c:1905-1990+): `active_timer.lstick.x/y` resets to 0 on the frame the axis
   crosses +/-`horizontal/vertical_stick_smash_deadzone` (+0x8/+0xC = 0.25) from inside, then counts up
   (capped at 254). It is 254 while the axis is inside +/-0.25.

Transitions checked from Guard (`ftCo_Guard_IASA`, ftCo_Guard.c:539-548). Order matters and the first match wins.
GuardOn/GuardReflect add powershield and `ftCo_800D8B9C` (l.466-477/1052-1063).

| order | check | condition (PlCo value) |
|---|---|---|
| 1 | release | `!(held & LR)` sets `guard.xC`; the shield ends when `xC && !x10`, or when the shield is gone (inlineC0, l.452-466) |
| 2 | `ftCo_8009515C` (ftCo_ItemThrow.c:142) | item action (not stick-related) |
| 3 | spotdodge `ftCo_8009980C` (ftCo_Escape.c:218-226) | `ls.y <= x314 (-0.70)` and `timer.y < x318 (4)`, or C-stick (`ftCo_800DF8E8`) |
| 4 | roll `ftCo_8009917C` (ftCo_Escape.c:50-66) | `abs(ls.x) >= x31C (0.70)` and `timer.x < x320 (4)`, or C-stick; forward/back by `sign(x*facing)` |
| 5 | grab `ftCo_Catch_CheckInput` | button |
| 6 | jump `ftCo_800CB024` (ftCo_Jump.c:86-99) | `ls.y >= tap_jump_threshold +0x70 (0.6625)` and `timer.y < tap_jump_window +0x74 (4)`; X/Y; C-stick up |
| 7 | shield drop `ftCo_8009A080` (ftCo_Pass.c:53-62) | `ls.y <= -x464 (-0.66)` and `timer.y < x468 (6.0f)` and on a platform |

So **every held stick position is reachable as a tilt** if the stick gets there slowly: the axis has
to take at least 4 frames (roll, spotdodge, jump) or 6 frames (shield drop) from the +/-0.25 crossing to the
threshold. It can also already be held when the shield comes out, in which case the timers are 254.
The tilt code has no thresholds of its own.

---

## 6. Special cases

* **Part index vs joint index** (applies to all walkers). Part indices skip slots `i` where
  `ftParts_8007506C(kind, i) != 0` (ftparts.c:712-727; the table is `Fighter_804D6540` = PlCo `ftLoadCommonData`
  pData[5], fighter.c:193). Read from PlCo.dat: **Kirby** has 13 optional slots {7-10, 15, 16, 28-34}
  (parts_num 59, 46 joints; shield part 57 = joint 44). **Link** has slot {68} (76 parts / 75 joints;
  shield part 74 = joint 73). **Young Link** has slot {72} (80 / 79; shield part 78 = joint 77). All other
  characters have none, so parts index = SP/costume preorder index.
* **Yoshi**: never calls `ftCo_80091BC4`/`ftCo_80091E78`. Shield entry `ftYs_Init_8012BECC`
  (ftyoshiguard.c:90-98) and hold `ftYs_Shield_8012C1D4` (l.171-184) use normal animations
  (`Ft_MF_None`/0). The hold state first resets the live skeleton to the costume rest pose (`ftAnim_8006FA58`
  with `costume->child`, l.176). The bubble scale is constant `initial_shield_size` (`inlineB0`,
  ftCo_Guard.c:179-180). **Yoshi has no shield tilt.** Exclude Yoshi, or plot a single point.
* **Marth** (`Ft_Kind_Mars`): `ftCo_800923B4`/`ftCo_800939B4` add `ftParts_80074B0C(gobj, 1, 1)`
  (a model-part visibility switch) and SFX 190115 (ftCo_Guard.c:342-346, 924-928). This is cosmetic and does not change
  position. Roy (`Ft_Kind_Emblem`) has no such case.
* **Ice Climbers**: Nana uses Popo's Guard/GuardOn figatrees (section 2), plus her own ShieldPose and shield bone
  (PlNn.dat bone 47). Her stick is CPU-generated (fighter.c:1804-1806). **UNKNOWN**: how Nana's CPU
  stick follows Popo's (delay and values). Resolve via the CPU-input code (`ftCo_GetCpuLStickX`) or emulator RAM.
* **Kirby**: hat parts are optional slots. `x594_bits = 0` in the shield states, so the Guard tree never
  animates the hats, and they are not in the SP tree. Only the index mapping above matters.
* **Mewtwo**: `parts[FtPart_TransN].flags_b4 = true` (redundant with ftparts.c:691) and `x2221_b2 = true`
  (ftmewtwo.c:292-296). `x2221_b2` only affects `ftAnim_8006DF0C` (called from CapturePulled). Mewtwo's Guard
  figatree animates TransN (tracks 1,2,3,5,6,7), but TransN is not an ancestor of its shield bone.
* **Game & Watch**: the shield node has rotation and translation tracks, and the chain skips TransN (section 4.4).
* **Peach, Zelda, Sheik, Samus, others**: no special-case code in the guard path. Dynamics bones
  (`flags_b0`, ftdynamics.c) are excluded by every walker, and none are on a shield chain.
* **Powershield** (`ftCo_80093A50`, motion 182): uses the same tilt code via `ftCo_GuardOn_Anim_inline`.

---

## 7. ftCommonData fields (PlCo.dat)

`Fighter_LoadCommonData` (fighter.c:179-188) loads the symbol `ftLoadCommonData`.
`p_ftCommonData = pData[0]`, the first pointer inside that root struct. In the extracted PlCo.dat the root is at
data+0xECD8, and its word 0 points to **data+0x9FC0 = file offset 0x9FE0** (file offset = data offset + 0x20 header).
Offsets below are relative to that struct (ft/types.h:77+). The offsets in the struct comments match how the code uses them.

| field | struct off | file off | PlCo value | used for |
|---|---|---|---|---|
| horizontal_stick_deadzone | +0x000 | 0x9FE0 | 0.28 | section 5 |
| vertical_stick_deadzone | +0x004 | 0x9FE4 | 0.28 | section 5 |
| horizontal/vertical_stick_smash_deadzone | +0x008/+0x00C | 0x9FE8/0x9FEC | 0.25/0.25 | smash timers |
| analog_shoulder_deadzone | +0x010 | 0x9FF0 | 0.30 | lightshield |
| z_press_analog_value | +0x014 | 0x9FF4 | 0.35 | Z = light press |
| tap_jump_threshold / window | +0x070/+0x074 | 0xA050/0xA054 | 0.6625 / 4 | section 5 |
| x260_startShieldHealth | +0x260 | 0xA240 | 60.0 | bubble scale |
| x264 (min scale fraction) | +0x264 | 0xA244 | 0.15 | bubble scale |
| x2D4 (light factor at ls=0) | +0x2D4 | 0xA2B4 | 1.0 | bubble scale |
| x2D8 (light factor at ls=1) | +0x2D8 | 0xA2B8 | 0.5 | bubble scale |
| x314 / x318 | +0x314/+0x318 | 0xA2F4/0xA2F8 | -0.70 / 4 | spotdodge |
| x31C / x320 | +0x31C/+0x320 | 0xA2FC/0xA300 | 0.70 / 4 | roll |
| **x44C (tilt easing K)** | +0x44C | **0xA42C** | **0.5** | section 1 |
| x464 / x468 | +0x464/+0x468 | 0xA444/0xA448 | 0.66 / 6.0f | shield drop |

Bubble scale (`inlineB0`, ftCo_Guard.c:177-191), non-Yoshi:
`b = initial_shield_size(+0x90) * (x264 + (1 - x264) * (shield_health/x260) * (ls*(x2D8 - x2D4) + x2D4))`,
with `ls = lightshield_amount = (trigger - 0.30)/(1 - 0.30)` (ftCo_Guard.c:318-326, 400-411). A digital
press forces trigger = 1 (fighter.c:1888-1890). With the PlCo values this is
`initial_shield_size * (0.15 + 0.85 * (health/60) * (1 - 0.5*ls))`, so light shield is larger. **Size does not
affect the centre.**

---

## 8. Open items (UNKNOWN) and how to resolve them
1. **Costume rest pose** (Pl??Nr.dat and the other costume files; `x108_costume_joint`) supplies every
   channel the Guard figatree does not animate (section 3.2c). These files are not extracted yet, and the solver needs them.
   Also check whether rest poses differ between costumes (costume_id picks the Joint, fighter.c:570-572).
2. Costume joint flags (CLASSICAL_SCALE / IK / INSTANCE) on the shield chain (section 4.3).
3. TransN discontinuity at x4 == 1 (the b4 path, section 3.2e). Compare costume TransN with SP TransN.
4. Whether Guard figatree frame 370 equals frame 10. It is only reached transiently. Confirm by evaluating the FObjs.
5. Bubble position during GuardSetOff/shieldstun (section 3.1). Verify in emulator RAM.
6. Name of part 0x35 (flags_b4).
7. Nana's CPU stick (section 6).
8. Exact float rounding of the easing (fmadds vs fmuls+fadds). This does not matter for settled ranges.
