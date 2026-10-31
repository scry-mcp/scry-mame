"""The window tier of MAME: a full-screen application takes the Space the emulator's window is on,
and `window(front=True)` brings it back. It switches the owner's desk, so it is out of every
default run (`-m window`, with `SCRY_FOCUS_CONTROL=1` on a Mac)."""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import window as core_window
from scry_core import window_stand_ins as stand_ins

from scry_mame import server as s

BINARY = os.environ.get("MAME_BINARY", "")
ROMS = os.environ.get("MAME_TEST_ROMS", "")
NEEDS = pytest.mark.skipif(not (BINARY and ROMS), reason="set MAME_BINARY and MAME_TEST_ROMS")


@pytest.mark.live
@NEEDS
@stand_ins.on_the_desk
def test_window_front_brings_mame_back_from_behind_a_full_screen_application(
        tmp_path: Path) -> None:
    image = tmp_path / "circus.ref"
    with zipfile.ZipFile(Path(ROMS) / "circus.zip") as z:
        image.write_bytes(z.read("9004a.1a"))
    ini = tmp_path / "ini"
    ini.mkdir()
    (ini / "mame.ini").write_text("joystickprovider none\n")
    started = cast(dict[str, Any], s.start(
        binary=BINARY, system="circus", rompath=ROMS, reference_rom=str(image),
        reference_addr="0x1000", reference_base="0x1000", boot_seconds=30.0, presence=False,
        inipath=str(ini), shared=True, display=0, background=False))
    assert started["status"] == "ok", started
    host = core_window.host()
    cover = subprocess.Popen([str(stand_ins.built(tmp_path, "cover"))])
    try:
        pid = cast(int, started["pid"])
        stand_ins.until("the full-screen application taking the Space",
                        lambda: (w := core_window.state_of(pid, host.windows(), host.displays(),
                                                           host.above)) is not None
                        and not w.onscreen)
        behind = cast(dict[str, Any], s.window())["window"]
        assert behind["onscreen"] is False, behind
        front = cast(dict[str, Any], s.window(front=True))
        assert front["status"] == "ok", front
        assert front["window"]["onscreen"] is True and front["window"]["front"] is True, front
    finally:
        cover.terminate()
        cover.wait(timeout=10)
        s.close()
