"""What the MAME demos share (`demos/free_set.py`), without an emulator: where a demo refuses to
start, the reference image it takes out of a free set's zip, and the checks every demo runs."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from scry_core import host_program, live_host
from scry_core.demo import Reply, Run, StepFailed

from demos import free_set

ROM = b"\x7e\xa0\x00" * 8


def _zip(folder: Path, *members: tuple[str, bytes]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "someset.zip", "w") as z:
        for name, data in members:
            z.writestr(name, data)
    return folder


def _crc(data: bytes) -> int:
    return zipfile.crc32(data)  # type: ignore[attr-defined, no-any-return]


@pytest.mark.parametrize(("options", "said"), [
    ({}, "no someset.zip in --rompath (not given). Get it from "
         "https://www.mamedev.org/roms/someset/someset.zip"),
    ({"rompath": "roms"}, "the server takes absolute paths only: --rompath roms"),
    ({"binary": "mame", "rompath": "/r"}, "the server takes absolute paths only: --binary mame"),
])
def test_a_demo_says_why_it_cannot_run(options: dict[str, str], said: str) -> None:
    assert free_set.precheck("someset")(Run(dir=Path("/x"), options=options)).startswith(said)


def _mame(tmp_path: Path, body: str) -> Path:
    """A MAME of the test's own: a program whose Python `body` is what the canary sees it do."""
    return host_program.write(tmp_path / "mame", f"import os, sys, time\n{body}\n")


def test_a_demo_with_its_zip_on_a_host_that_starts_mame_runs(tmp_path: Path) -> None:
    roms = _zip(tmp_path / "roms", ("a.bin", ROM))
    binary = _mame(tmp_path, "roms = os.path.join(os.path.dirname(sys.argv[0]), 'roms')\n"
                             "sys.exit(sys.argv[2:5] != ['-rompath', roms, '-joystickprovider'])")
    run = Run(dir=tmp_path, options={"rompath": str(roms), "binary": str(binary)})
    assert free_set.precheck("someset")(run) == ""


def test_a_demo_on_a_host_that_cannot_start_mame_says_so_before_any_step(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roms = _zip(tmp_path / "roms", ("a.bin", ROM))
    binary = _mame(tmp_path, "time.sleep(20)")
    monkeypatch.setattr(live_host, "CANARY_S", 0.5)
    run = Run(dir=tmp_path, options={"rompath": str(roms), "binary": str(binary)})
    assert "the host cannot start this emulator" in free_set.precheck("someset")(run)


def test_a_binary_that_resolves_to_nothing_is_left_to_start_to_name(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roms = _zip(tmp_path / "roms", ("a.bin", ROM))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert free_set.precheck("someset")(Run(dir=tmp_path, options={"rompath": str(roms)})) == ""


def test_the_reference_image_comes_out_of_the_zip_by_its_crc(tmp_path: Path) -> None:
    roms = _zip(tmp_path / "roms", ("decoy.bin", b"no"), ("renamed.bin", ROM))
    run = Run(dir=tmp_path / "run", options={"rompath": str(roms)})
    run.dir.mkdir()
    args = free_set.boot("someset", _crc(ROM), "0xa000")(run)
    assert Path(args["reference_rom"]).read_bytes() == ROM
    assert (args["reference_addr"], args["reference_base"]) == ("0xa000", "0xa000")
    assert (Path(args["inipath"]) / "mame.ini").read_text() == "joystickprovider none\n"
    assert Path(args["state_dir"]).is_dir() and not any(Path(args["state_dir"]).iterdir())


def test_a_state_left_by_an_earlier_run_is_emptied(tmp_path: Path) -> None:
    roms = _zip(tmp_path / "roms", ("a.bin", ROM))
    run = Run(dir=tmp_path / "run", options={"rompath": str(roms)})
    (run.dir / "someset-states").mkdir(parents=True)
    (run.dir / "someset-states" / "old.sta").write_bytes(b"old")
    args = free_set.boot("someset", _crc(ROM), "0x0")(run)
    assert not any(Path(args["state_dir"]).iterdir())


@pytest.mark.parametrize("members", [(("a.bin", b"other"),), (("a.bin", ROM), ("b.bin", ROM))])
def test_a_zip_without_exactly_one_rom_of_that_crc_fails_the_start(
        tmp_path: Path, members: tuple[tuple[str, bytes], ...]) -> None:
    roms = _zip(tmp_path / "roms", *members)
    run = Run(dir=tmp_path, options={"rompath": str(roms)})
    with pytest.raises(StepFailed, match="not one"):
        free_set.boot("someset", _crc(ROM), "0x0")(run)


def _reply(**data: object) -> Reply:
    return Reply(dict(data))


def test_the_shared_checks_pass_on_a_right_answer_and_name_a_wrong_one(tmp_path: Path) -> None:
    run = Run(dir=tmp_path)
    (tmp_path / "screen.png").write_bytes(b"png")
    (tmp_path / "s.sta").write_bytes(b"sta")
    run.replies["save"] = _reply(frame=7)
    rights = [
        (free_set.started, _reply(rom_check="OK", system="x", version="v", pc="0x0"),
         "x on MAME v, rom_check OK, pc 0x0"),
        (free_set.started, _reply(rom_check="OK", system="x", version="v", pc="0x0",
                                  start_retries=[{"why": "a"}]),
         "x on MAME v, rom_check OK, pc 0x0, after 1 start retry"),
        (free_set.started, _reply(rom_check="OK", system="x", version="v", pc="0x0",
                                  start_retries=[{"why": "a"}, {"why": "b"}]),
         "x on MAME v, rom_check OK, pc 0x0, after 2 start retries"),
        (free_set.ran, _reply(verdict="ELAPSED", frame_before=1, frame_after=2, cycles=3),
         "ran to frame 2, 3 cycles"),
        (free_set.scanned("0x0", 4), _reply(hits_total=4), "4 candidate bytes in 0x0+0x4"),
        (free_set.saved, _reply(path=str(tmp_path / "s.sta"), name="n", frame=7),
         "state n saved at frame 7"),
        (free_set.loaded, _reply(verified=True, frame=7, name="n"),
         "state n loaded and verified, frame 7"),
        (free_set.pictured("the screen"), _reply(width=2, height=3, image={
            "path": str(tmp_path / "screen.png"), "sha256": "ab" * 32}),
         "the screen, 2x3"),
        (free_set.closed, _reply(ended_by="quit"), "closed: MAME quit on its own"),
    ]
    for check, reply, said in rights:
        assert check(reply, run) == said
    wrongs = [
        (free_set.started, _reply(rom_check="MISMATCH")),
        (free_set.started, _reply(rom_check="OK", system="x", pc="0x0",
                                  version={"available": False, "why": "did not return in 5 s"})),
        (free_set.ran, _reply(verdict="TIMEOUT")),
        (free_set.ran, _reply(verdict="ELAPSED", frame_before=2, frame_after=2)),
        (free_set.scanned("0x0", 4), _reply(hits_total=3)),
        (free_set.saved, _reply(path=str(tmp_path / "missing.sta"))),
        (free_set.loaded, _reply(verified=False)),
        (free_set.loaded, _reply(verified=True, frame=8)),
        (free_set.pictured("x"), _reply(image={"path": str(tmp_path / "other.png")})),
        (free_set.closed, _reply(ended_by="killed")),
    ]
    for check, reply in wrongs:
        with pytest.raises(StepFailed):
            check(reply, run)


def test_a_demo_is_declared_where_every_free_set_demo_keeps_its_files(tmp_path: Path) -> None:
    demo_file = tmp_path / "repo" / "demos" / "someset" / "demo.py"
    moments = (free_set.Moment("a", "b", "It moves."),)
    declared = free_set.demo("someset", str(demo_file), [], moments, "A set moving")
    assert declared.root == tmp_path / "repo"
    assert declared.server[1:] == ["-m", "scry_mame.server"]
    assert declared.readme == demo_file.parent / "README.md"
    assert declared.capture is not None
    assert declared.capture(Run(dir=tmp_path)) == tmp_path / "screen.png"
    assert declared.offers == frozenset({"rompath", "display"})
    assert (declared.moments, declared.alt) == (moments, "A set moving")
    assert declared.front == tmp_path / "repo" / "README.md"
    assert declared.volatile == free_set.VOLATILE
