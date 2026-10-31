"""The window tier of MAME: a full-screen application takes the Space the emulator's window is on,
and `window(front=True)` brings it back, launched in front or behind. It moves the owner's desk:
`-m window`, with `SCRY_FOCUS_CONTROL=1` on a Mac."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import window_stand_ins as stand_ins

from scry_mame import server as s

BINARY = os.environ.get("MAME_BINARY", "")
ROMS = os.environ.get("MAME_TEST_ROMS", "")
NEEDS = pytest.mark.skipif(not (BINARY and ROMS), reason="set MAME_BINARY and MAME_TEST_ROMS")


def _window(**arguments: Any) -> dict[str, Any]:
    return cast(dict[str, Any], s.window(**arguments))


def _started(tmp_path: Path, background: bool) -> int:
    image = tmp_path / "circus.ref"
    with zipfile.ZipFile(Path(ROMS) / "circus.zip") as z:
        image.write_bytes(z.read("9004a.1a"))
    ini = tmp_path / "ini"
    ini.mkdir()
    (ini / "mame.ini").write_text("joystickprovider none\n")
    started = cast(dict[str, Any], s.start(
        binary=BINARY, system="circus", rompath=ROMS, reference_rom=str(image),
        reference_addr="0x1000", reference_base="0x1000", boot_seconds=30.0, presence=False,
        inipath=str(ini), shared=True, display=0, background=background))
    assert started["status"] == "ok" and started["background"] is background, started
    return cast(int, started["pid"])


@pytest.mark.live
@NEEDS
@stand_ins.on_the_desk
def test_window_front_brings_mame_back_from_behind_a_full_screen_application(
        tmp_path: Path) -> None:
    try:
        with stand_ins.under_a_cover(_started(tmp_path, background=False), tmp_path):
            stand_ins.comes_forward(_window)
    finally:
        s.close()


@pytest.mark.live
@NEEDS
@stand_ins.on_the_desk
def test_window_front_brings_a_background_session_back_too(tmp_path: Path) -> None:
    try:
        with stand_ins.under_a_cover(_started(tmp_path, background=True), tmp_path):
            stand_ins.comes_forward(_window)
    finally:
        s.close()
