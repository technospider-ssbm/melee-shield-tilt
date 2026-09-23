"""Launch an isolated Slippi Dolphin instance via libmelee and drive a
fighter's shield tilt to exact stick coordinates.

Uses libmelee's named-pipe controller (method (a) from the brief) with
Console(tmp_home_directory=True), so the netplay user's own Dolphin config
under %APPDATA%\\Slippi Launcher\\netplay\\User is never touched. Gecko codes
injected are libmelee's own (GALE01r2.ini: "Extract Menu Info" + optional
Infinite Time / Instant Match, none enabled by default here) plus whatever
Slippi Dolphin bakes in; none of these touch stick or guard processing
(checked tools/validate/drive.py module docstring / PROGRESS.md).
"""
from __future__ import annotations

import os
import sys
import time

import melee
from melee import enums

DOLPHIN_EXE_DIR = os.path.expandvars(r"%APPDATA%\Slippi Launcher\netplay")

# dolphin-memory-engine only hooks a process literally named "Dolphin.exe".
# Slippi's own launcher-managed binary is "Slippi Dolphin.exe", so we run an
# isolated copy (tools/validate/setup_scratch_dolphin.py makes this once,
# copying the netplay dir minus the User/ config folder into scratch and
# duplicating the exe under the name dolphin-memory-engine expects). This
# never touches the real install or its User/ config.


def load_local_json():
    # local.json contains raw (unescaped) Windows backslashes, which is not
    # strictly valid JSON. Parse the iso path out directly rather than
    # touching the user's file.
    import re
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "local.json"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'"iso"\s*:\s*"(.*)"', text)
    if not m:
        raise RuntimeError("Could not find iso key in local.json")
    return {"iso": m.group(1)}


def make_console(scratch_dir: str, iso_path: str) -> melee.Console:
    home = os.path.join(scratch_dir, "dolphin_home")
    os.makedirs(home, exist_ok=True)
    exe_path = os.path.join(scratch_dir, "dolphin_bin", "Dolphin.exe")
    console = melee.Console(
        path=exe_path,
        dolphin_home_path=home,
        tmp_home_directory=False,  # we pass our own scratch home explicitly
        slippi_port=51441,
        blocking_input=False,
        polling_mode=False,
        setup_gecko_codes=True,
        save_replays=False,
        fullscreen=False,
        disable_audio=True,
        emulation_speed=1.0,
    )
    return console, home


def start(scratch_dir: str, character: enums.Character, stage: enums.Stage = enums.Stage.FINAL_DESTINATION):
    """Boots dolphin, returns (console, controller1, controller2) once in-game."""
    cfg = load_local_json()
    console, home = make_console(scratch_dir, cfg["iso"])
    controller1 = melee.Controller(console=console, port=1, type=enums.ControllerType.STANDARD)
    controller2 = melee.Controller(console=console, port=2, type=enums.ControllerType.STANDARD)

    console.run(iso_path=cfg["iso"])
    console.connect()
    controller1.connect()
    controller2.connect()

    menu_helper = melee.MenuHelper()
    gamestate = None
    while True:
        gamestate = console.step()
        if gamestate is None:
            continue
        if gamestate.menu_state == enums.Menu.IN_GAME:
            break
        menu_helper.menu_helper_simple(
            gamestate, controller1,
            character_selected=character,
            stage_selected=stage,
            connect_code=None,
            cpu_level=0,
            autostart=True,
        )
        menu_helper.menu_helper_simple(
            gamestate, controller2,
            character_selected=enums.Character.FOX,
            stage_selected=stage,
            connect_code=None,
            cpu_level=1,
            autostart=True,
        )
    return console, controller1, controller2


def hold_shield_toward(controller: melee.Controller, stick_x: int, stick_y: int):
    """stick_x/stick_y in melee's internal [-80,80] units (integers)."""
    controller.press_button(enums.Button.BUTTON_L)
    controller.tilt_analog_unit(enums.Button.BUTTON_MAIN, stick_x / 80.0, stick_y / 80.0)
    controller.flush()


def ramp_shield_toward(console, controller, port_index, target_x, target_y,
                        step=0.03, hold_neutral_frames=15, settle_frames=75):
    """Move the main stick from neutral to (target_x, target_y) (melee's
    internal [-80,80] units) gradually while holding a digital shield, to
    avoid tripping the roll/spotdodge/jump smash-input timers (see
    ftCo_Escape.c / ftCo_Jump.c: a stick axis must stay inside the
    smash-deadzone -> full-tilt path for several frames, not snap there).

    Returns the GameState from the final settle frame (or None).
    """
    import ram

    controller.press_button(enums.Button.BUTTON_L)
    controller.tilt_analog_unit(enums.Button.BUTTON_MAIN, 0.0, 0.0)
    controller.flush()
    for _ in range(hold_neutral_frames):
        console.step()
        ram.pin_shield_health(port_index)

    tx = target_x / 80.0
    ty = target_y / 80.0
    dist = max(abs(tx), abs(ty), 1e-9)
    n_steps = max(1, int(dist / step) + 1)
    gs = None
    for i in range(1, n_steps + 1):
        frac = i / n_steps
        controller.tilt_analog_unit(enums.Button.BUTTON_MAIN, tx * frac, ty * frac)
        controller.flush()
        gs = console.step()
        ram.pin_shield_health(port_index)

    for _ in range(settle_frames):
        gs = console.step()
        ram.pin_shield_health(port_index)
    return gs


def release(controller: melee.Controller):
    controller.release_all()
    controller.flush()
