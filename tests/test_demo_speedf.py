"""The Speed Fight demo's MAME binding, without an emulator: where it refuses to start, and what
the call adds to the game's own recipe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scry_core.demo import Reply, Run, StepFailed

from demos import free_set
from demos.speedf import demo


def _game(folder: Path, *, built: bool = True) -> Path:
    for p in (demo.PROFILE, *((demo.IMAGE, demo.ROMSET / "speedf.zip", demo.ROMSET / "speedf.map")
                              if built else ())):
        (folder / p).parent.mkdir(parents=True, exist_ok=True)
        (folder / p).write_bytes(b"x")
    return folder


def test_the_demo_says_why_it_cannot_run(tmp_path: Path) -> None:
    assert demo.precheck(Run(dir=tmp_path)).startswith("pass --cwd")
    assert demo.precheck(Run(dir=tmp_path, options={"binary": "mame"})).startswith(
        "the server takes absolute paths only: --binary mame")
    assert demo.precheck(Run(dir=tmp_path, options={"cwd": "../game"})).startswith(
        "the server takes absolute paths only: --cwd ../game")
    unbuilt = _game(tmp_path / "unbuilt", built=False)
    said = demo.precheck(Run(dir=tmp_path, options={"cwd": str(unbuilt)}))
    assert said.startswith("no build/speedf.bin")
    built = _game(tmp_path / "built")
    elsewhere = Run(dir=tmp_path, options={"cwd": str(built), "rompath": str(tmp_path / "x")})
    assert demo.precheck(elsewhere).startswith("no speedf.zip in")
    assert demo.precheck(Run(dir=tmp_path, options={"cwd": str(built), "rompath": "roms"})
                         ).startswith("the server takes absolute paths only: --rompath roms")
    (built / demo.ROMSET / "speedf.map").unlink()
    assert "speedf.map under --cwd" in demo.precheck(Run(dir=tmp_path, options={"cwd": str(built)}))


def test_a_built_checkout_passes_to_the_host_s_canary(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    built = _game(tmp_path / "built")
    monkeypatch.setattr(free_set, "host_ready",
                        lambda run, system, rompath: f"canary: {system} off {rompath}")
    assert demo.precheck(Run(dir=tmp_path, options={"cwd": str(built)})) == (
        f"canary: speedf off {built / demo.ROMSET}")


def test_the_call_adds_only_the_run_s_own_to_the_recipe(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    run = Run(dir=tmp_path / "run", options={"cwd": str(game)})
    run.dir.mkdir()
    args = demo.boot(run)
    assert args == {"profile": str(game / demo.PROFILE), "inipath": run.dir / "speedf-ini",
                    "state_dir": run.dir / "speedf-states", "shared": True,
                    "background": True, "display": 0}
    assert (run.dir / "speedf-ini" / "mame.ini").read_text() == "joystickprovider none\n"
    given = Run(dir=run.dir, options={"cwd": str(game), "rompath": str(tmp_path / "roms")})
    assert demo.boot(given)["rompath"] == tmp_path / "roms"
    own = Run(dir=run.dir, options={"cwd": str(game), "rompath": str(game / demo.ROMSET)})
    assert "rompath" not in demo.boot(own), "the recipe's own directory is left to the recipe"


def test_a_state_left_by_an_earlier_run_is_emptied(tmp_path: Path) -> None:
    game = _game(tmp_path / "game")
    run = Run(dir=tmp_path / "run", options={"cwd": str(game)})
    (run.dir / "speedf-states").mkdir(parents=True)
    (run.dir / "speedf-states" / "old.sta").write_bytes(b"x")
    assert not any(Path(demo.boot(run)["state_dir"]).iterdir())


def test_a_cwd_led_by_a_tilde_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert demo.game(Run(dir=tmp_path, options={"cwd": "~"})) == tmp_path


def test_the_start_must_have_come_from_the_recipe(tmp_path: Path) -> None:
    reply: dict[str, Any] = {"rom_check": "OK", "version": "0.289", "system": "speedf",
                             "symbols_total": 223,
                             "profile": {"name": "x", "file": "x", "supplied": ["binary"]}}
    with pytest.raises(StepFailed, match="the recipe supplied"):
        demo.started(Reply(reply), Run(dir=tmp_path))
    reply["profile"]["supplied"] = ["binary", "system", "rompath", "reference_rom", "symbols"]
    assert demo.started(Reply(reply), Run(dir=tmp_path)).startswith(
        "speedf on MAME from the game's own recipe (5 keys), rom_check OK, 223 symbols")
    for partial in (["system", "reference_rom"], ["system", "symbols"],
                    ["reference_rom", "symbols"]):
        reply["profile"]["supplied"] = partial
        with pytest.raises(StepFailed, match="the recipe supplied"):
            demo.started(Reply(reply), Run(dir=tmp_path))


def test_the_scene_is_one_byte(tmp_path: Path) -> None:
    assert demo.scene(Reply({"hex": "02"}), Run(dir=tmp_path)).startswith("_sceneId 2")


def test_every_step_name_is_unique() -> None:
    names = [s.name for s in demo.DEMO.steps]
    assert len(names) == len(set(names)), "a step name is the key its reply is kept by"
