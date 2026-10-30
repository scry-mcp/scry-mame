"""The LineUp demo's MAME binding, without an emulator: where it refuses to start, and the
reference image and symbols it starts the board with."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from scry_core.demo import Reply, Run, StepFailed
from scry_core.games import lineup

from demos.lineup import demo


def _romset(folder: Path, *, with_map: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "lineup.zip", "w") as z:
        z.writestr("1.bin", bytes([0x10, 0x30]))
        z.writestr("2.bin", bytes([0x20, 0x40]))
    if with_map:
        (folder / "lineup.map").write_text("Player1\t28000\t_DATA\t8000\tDATA\n")
    return folder


@pytest.mark.parametrize(("options", "said"), [
    ({}, "no lineup.zip or lineup.map in --rompath (not given)"),
    ({"rompath": "roms"}, "the server takes absolute paths only: --rompath roms"),
])
def test_the_demo_says_why_it_cannot_run(options: dict[str, str], said: str) -> None:
    assert demo.precheck(Run(dir=Path("/x"), options=options)).startswith(said)


def test_a_romset_without_its_symbols_is_refused(tmp_path: Path) -> None:
    roms = _romset(tmp_path / "roms", with_map=False)
    assert demo.precheck(Run(dir=tmp_path, options={"rompath": str(roms)})).startswith(
        "no lineup.map in --rompath")


def test_the_board_starts_on_the_image_its_halves_make_with_the_romsets_map(
        tmp_path: Path) -> None:
    roms = _romset(tmp_path / "roms")
    run = Run(dir=tmp_path / "run", options={"rompath": str(roms)})
    run.dir.mkdir()
    args = demo.boot(run)
    assert Path(args["reference_rom"]).read_bytes() == bytes([0x10, 0x20, 0x30, 0x40])
    assert Path(args["symbols"]).read_text() == (roms / "lineup.map").read_text()
    assert Path(args["symbols"]).parent == run.dir
    assert (args["reference_addr"], args["bases"]) == ("0x30000", demo.BASES)
    assert (Path(args["inipath"]) / "mame.ini").read_text() == "joystickprovider none\n"
    assert args["shared"] is True and "display" not in args


def test_a_start_whose_release_could_not_be_read_is_not_a_demo_start() -> None:
    run = Run(dir=Path("/x"))
    right = Reply({"rom_check": "OK", "system": "lineup", "symbols_total": 3, "version": "0.289"})
    assert demo.started(right, run) == "lineup on MAME, rom_check OK, 3 symbols"
    slow = Reply({**right, "version": {"available": False, "why": "did not return in 5 s"}})
    with pytest.raises(StepFailed):
        demo.started(slow, run)


def test_the_binding_fires_every_action_the_script_declares() -> None:
    assert set(demo.INPUTS) == set(lineup.ACTIONS)
    names = [s.name for s in demo.DEMO.steps]
    assert len(names) == len(set(names)), "a step name is the key its reply is kept by"
    assert demo.INPUTS["FIRE1"].args["field"] == "P1 Button 2", "the arcade's J_FIRE1 is bit 7"
    assert demo.BINDING.frames(2000) == 101
