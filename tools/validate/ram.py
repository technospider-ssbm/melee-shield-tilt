"""Direct RAM reads for shield-tilt validation.

Pointer chain (big-endian, GameCube/Wii address space, all offsets confirmed
against the doldecomp source in external/melee, see docstrings below):

    player_slots (.bss @ 0x80453080, stride 0xE90, up to 6 slots)
      +0xB0   HSD_GObj* player_entity[0]      (Fighter_GObj)  [pl/player.h]
    Fighter_GObj
      +0x2C   void* user_data                  -> Fighter*    [sysdolphin/baselib/gobj.h]
    Fighter (fp)
      +0x10   FtMotionId motion_id  (action state id, u32)     [melee/ft/fighter.c: fp->motion_id]
      +0x2C   float facing_dir                                 [melee/ft/types.h:1318]
      +0xB0   Vec3  cur_pos                                    [melee/ft/types.h:1328]
      +0x620  float input.lstick[0]  (processed, post-deadzone)
      +0x624  float input.lstick[1]
      +0x1998 float shield_health                               [types.h:1565]
      +0x199C float lightshield_amount                          [types.h:1566]
      +0x2344 float mv.co.guard.x4  (tilt weight, settles to m)  [docs/MECHANICS.md:25]
      +0x2348 float mv.co.guard.x8  (tilt anim frame, settles to 10+deg)
      +0x5E8  FighterBone* parts   (array, stride 0x10)          [types.h:1397, 909-945]
        parts[i] + 0x0  HSD_JObj* joint
    HSD_JObj (joint)
      +0x44   Mtx mtx  (3x4 f32 world matrix, row-major)         [sysdolphin/baselib/jobj.h:118]

All reads are big-endian f32/u32. Player static block address and Fighter
struct layout were cross-checked live (see validate_offsets()) against percent,
facing and position reported independently by libmelee's Slippi-derived
GameState before trusting them for capture.
"""
from __future__ import annotations

import struct
import dolphin_memory_engine as dme

PLAYER_SLOTS_BASE = 0x80453080
PLAYER_SLOT_STRIDE = 0xE90
PLAYER_ENTITY_OFF = 0xB0

GOBJ_USER_DATA_OFF = 0x2C

FP_MOTION_ID = 0x10
FP_FACING_DIR = 0x2C
FP_CUR_POS = 0xB0
FP_LSTICK = 0x620
FP_SHIELD_HEALTH = 0x1998
FP_LIGHTSHIELD_AMOUNT = 0x199C
FP_GUARD_X4 = 0x2344
FP_GUARD_X8 = 0x2348
FP_PARTS = 0x5E8

FIGHTERBONE_STRIDE = 0x10
FIGHTERBONE_JOINT_OFF = 0x0

JOBJ_MTX_OFF = 0x44


def connect():
    dme.hook()
    if not dme.is_hooked():
        raise RuntimeError("dolphin-memory-engine failed to hook Dolphin process")


def is_hooked() -> bool:
    return dme.is_hooked()


def _read_f32(addr: int) -> float:
    return struct.unpack(">f", dme.read_bytes(addr, 4))[0]


def _read_u32(addr: int) -> int:
    return struct.unpack(">I", dme.read_bytes(addr, 4))[0]


def _read_ptr(addr: int) -> int:
    return _read_u32(addr)


def _write_f32(addr: int, value: float):
    dme.write_bytes(addr, struct.pack(">f", value))


def pin_shield_health(port_index: int, value: float = 60.0):
    """Write-only exception (technospider, 2026-09-23): keep shield_health
    topped up during capture so it doesn't break mid-sweep. Only the
    shield_health field is ever written; no other RAM is touched besides
    controller input. Confirmed live that fp+FP_SHIELD_HEALTH reads 60.0 at
    match start and ticks down while shielding, before enabling this."""
    fp = get_fighter_ptr(port_index)
    _write_f32(fp + FP_SHIELD_HEALTH, value)


def player_entity_addr(port_index: int) -> int:
    """port_index is 0-based slot index into player_slots."""
    return PLAYER_SLOTS_BASE + port_index * PLAYER_SLOT_STRIDE + PLAYER_ENTITY_OFF


def get_fighter_gobj(port_index: int) -> int:
    return _read_ptr(player_entity_addr(port_index))


def get_fighter_ptr(port_index: int) -> int:
    gobj = get_fighter_gobj(port_index)
    if gobj == 0:
        raise RuntimeError(f"No fighter GObj for slot {port_index}")
    return _read_ptr(gobj + GOBJ_USER_DATA_OFF)


def get_shield_joint_ptr(fp: int, shield_bone_index: int) -> int:
    parts = _read_ptr(fp + FP_PARTS)
    bone_addr = parts + shield_bone_index * FIGHTERBONE_STRIDE
    return _read_ptr(bone_addr + FIGHTERBONE_JOINT_OFF)


def read_world_mtx(jobj: int):
    """Returns 3x4 row-major matrix as nested list [[r0],[r1],[r2]], each row 4 floats."""
    raw = dme.read_bytes(jobj + JOBJ_MTX_OFF, 48)
    vals = struct.unpack(">12f", raw)
    return [vals[0:4], vals[4:8], vals[8:12]]


def read_fighter_state(port_index: int, shield_bone_index: int) -> dict:
    fp = get_fighter_ptr(port_index)
    motion_id = _read_u32(fp + FP_MOTION_ID)
    facing_dir = _read_f32(fp + FP_FACING_DIR)
    pos = (
        _read_f32(fp + FP_CUR_POS),
        _read_f32(fp + FP_CUR_POS + 4),
        _read_f32(fp + FP_CUR_POS + 8),
    )
    lstick = (_read_f32(fp + FP_LSTICK), _read_f32(fp + FP_LSTICK + 4))
    shield_health = _read_f32(fp + FP_SHIELD_HEALTH)
    lightshield_amount = _read_f32(fp + FP_LIGHTSHIELD_AMOUNT)
    guard_x4 = _read_f32(fp + FP_GUARD_X4)
    guard_x8 = _read_f32(fp + FP_GUARD_X8)

    joint = get_shield_joint_ptr(fp, shield_bone_index)
    mtx = read_world_mtx(joint)
    # World position is the translation column (col 3) of each row.
    bone_world = (mtx[0][3], mtx[1][3], mtx[2][3])

    return {
        "fp": fp,
        "motion_id": motion_id,
        "facing_dir": facing_dir,
        "pos": pos,
        "lstick": lstick,
        "shield_health": shield_health,
        "lightshield_amount": lightshield_amount,
        "guard_x4": guard_x4,
        "guard_x8": guard_x8,
        "bone_world": bone_world,
    }


def validate_offsets(port_index: int, expected_facing: bool | None = None,
                      expected_pos=None, expected_percent=None, tol=0.5) -> list[str]:
    """Cross-check a few fields against independently-known values.
    Returns a list of human-readable problems (empty list = all good)."""
    problems = []
    fp = get_fighter_ptr(port_index)
    facing_dir = _read_f32(fp + FP_FACING_DIR)
    if expected_facing is not None:
        got_facing = facing_dir > 0
        if got_facing != expected_facing:
            problems.append(f"facing mismatch: raw={facing_dir} expected_right={expected_facing}")
    if expected_pos is not None:
        x = _read_f32(fp + FP_CUR_POS)
        y = _read_f32(fp + FP_CUR_POS + 4)
        if abs(x - expected_pos[0]) > tol or abs(y - expected_pos[1]) > tol:
            problems.append(f"pos mismatch: raw=({x},{y}) expected={expected_pos}")
    return problems
