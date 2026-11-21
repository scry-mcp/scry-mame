"""The Lua under `src/scry_mame/lua/` as tools read it: StyLua's layout over the files, and every
script the server composes, rendered with representative values, compiled by Lua 5.4 (MAME's) and
passed by luacheck. A tool that is not installed fails the test: a check that did not run is not
a pass."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scry_core import stop_wait

from scry_mame import (
    at_stop,
    callbacks,
    capture,
    film,
    gfx,
    launch,
    lua,
    lua_source,
    machine,
    presence,
    series,
    tally,
    tap,
    transport,
)
from scry_mame import declarations as dec
from scry_mame import manifest as mm
from scry_mame import palette as mpalette
from scry_mame import ramdac_lua as rlua
from scry_mame import recording as mrec
from scry_mame import screen as mscreen

ROOT = Path(__file__).resolve().parents[1]
#: The files are the same bytes on every host; CI's Linux and the macOS hosts judge them.
pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="the Lua is linted on Linux CI and on macOS")
#: Homebrew keeps 5.4 beside a newer default; CI installs it under its own name.
LUAC = ("luac5.4", "/opt/homebrew/opt/lua@5.4/bin/luac5.4", "luac")


def _tool(*names: str) -> str:
    for name in names:
        found = shutil.which(name)
        if found is not None:
            return found
    pytest.fail(f"none of {', '.join(names)} is installed: the Lua is not checked without it")


def _luac() -> str:
    luac = _tool(*LUAC)
    version = subprocess.run([luac, "-v"], capture_output=True, text=True, check=True).stdout
    assert version.startswith("Lua 5.4"), f"{luac} is {version.strip()}, not MAME's Lua 5.4"
    return luac


def _film() -> film.Film:
    fields = {f: None for f in film.Film.__dataclass_fields__}
    return film.Film(**{**fields, "trigger": "0x70001e", "trigger_addr": 0x70001E,  # type: ignore[arg-type]
                        "length": 2, "frames": 4, "keep": 2, "changed": True, "checked": True,
                        "screen": ":screen", "dir": Path("/s/film-1"), "space": "program",
                        "cpu": ":maincpu", "value": 0x12, "pc_addr": 0x400})


def _gate() -> str:
    spec = stop_wait.check("0x400", "", 0, "d0 == 0x7fff")
    assert spec is not None
    decl = dec.Declaration("breakpoint", "address", spec.ref, cpu=":maincpu")
    return at_stop.gate(Path("/s/state"), Path("/s/ctl"), spec, decl, 0x400, ":maincpu",
                        lambda ref: 0x50)


def _ports() -> dict[str, mm.PalettePort]:
    ramdac = mm.PalettePort("x", "palette", "", 1, 3, ("r", "g", "b"), 6, True, 256, "declared",
                            "s")
    latch = mm.PalettePort("y", "palette", "", 0x10, 0x12, ("r", "g", "b"), 5, True, 0,
                           "declared", "s", protocol="latch", index_flag_mask=0x8000)
    sequence = mm.PalettePort("z", "palette", "", 0x10, 0x12, ("r", "g", "b"), 5, True, 0,
                              "declared", "s", protocol="sequence")
    return {"ramdac": ramdac, "latch": latch, "sequence": sequence}


def scripts() -> dict[str, str]:
    """Every chunk the server sends, as it would send it."""
    code = lua_source.Code
    out = {
        "input": lua_source.render("input", port=":IN0", field="P1 Button 1", value=1, frames=2,
                                   mark="MAME_MCP_INPUT#1"),
        "throttle": lua_source.render("throttle", on=False, mark="MAME_MCP_THROTTLE#1"),
        "autoboot": machine.harness(Path("/s/machine.txt")) + lua_source.render(
            "autoboot-throttle", var=launch.THROTTLE_FRAME_VAR, mark=launch.THROTTLE_MARK)
        + presence.drawer(Path("/s")),
        "names": machine.names_harness(Path("/s/names.txt")),
        "audio": lua_source.render("audio", path="/s/a.wav", frames=5, mark="M#1",
                                   no_screen=mrec.NO_SCREEN)
        + mrec.armed("M#1"),
        "record": lua_source.render("record", path="/s/r.avi", frames=5, mark="M#2",
                                    no_screen=mrec.NO_SCREEN, release=code(lua.RELEASE))
        + mrec.armed("M#2"),
        "read-block": lua_source.render("read-block", tag=":mainram", addr=None, offset=0,
                                        length=4, cpu=code("manager.machine.debugger.visible_cpu")),
        "gfx-block": lua_source.render("gfx-block", cpu=code('manager.machine.devices[":maincpu"]'),
                                       bytes_max=1 << 20, share_max=1 << 16)
        + lua_source.render("pens") + f"if {gfx.block_call(Path('/s/b.bin'), ':gfx1', None, 64)} "
        f"then\n{mpalette.pens_call('palette', 0, 16)}\nend\n",
        "palette": lua_source.render("palette", tag="", first=0, count=16, count_max=4096),
        "series-arm": series.arm_script(Path("/s/series"), None, 10, 20, 2, list(range(10, 21, 2))),
        "series-finish": lua_source.render("series-finish"),
        "at-stop-gate": _gate(),
        "film-arm": mscreen.capture_lua() + lua_source.render(
            "film-arm", call=code(mscreen.capture_call(Path("/s/screen-1.txt"), True)),
            snap="/s/snap.bin", cpu=code("manager.machine.debugger.visible_cpu"),
            space="program"),
        "film-install": film.install_script(_film(), Path("/s/film-1/film.txt")),
        "capture-space": capture.install_script("c_1", 0x12, capture.TapSource("space", "", 0x10),
                                                4, Path("/s/h.txt"), Path("/s/r.rows")),
        "capture-region": capture.install_script(
            "c_2", 0x12, capture.TapSource("region", ":gfx1", 0x100), 4, Path("/s/h.txt"),
            Path("/s/r.rows"), ":maincpu"),
        "capture-read": capture.install_script("c_3", 0x12, capture.TapSource("share", ":r", 0),
                                               4, Path("/s/h.txt"), Path("/s/r.rows"),
                                               trigger_type="r"),
        "tap-remove": tap.remove_script("c_1", capture.REGISTRY),
        "dump": rlua.dump_lua(),
    }
    for access in ("w", "r", "rw"):
        out[f"tally-{access}"] = tally.install_script("t_1", 0x2031FC, 4, Path("/s/t.txt"),
                                                      access=access)
    for protocol, port in _ports().items():
        out[f"ramdac-{protocol}"] = rlua.install_script("x", port, Path("/s/h.txt"),
                                                        Path("/s/r.rows"), None)
    assert callbacks.LUA in out["tally-w"]
    return out


def test_every_file_is_among_the_scripts_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file `scripts()` never reaches is formatted and parsed, but never composed or linted."""
    read: set[str] = set()
    plain = lua_source.load.__wrapped__

    def seen(name: str) -> str:
        read.add(name)
        return plain(name)

    monkeypatch.setattr(lua_source, "load", seen)
    scripts()
    # Read once, when their module is imported, and composed from the module's constant since.
    imported = {"record-release": lua.RELEASE,
                "callbacks": callbacks.LUA, "beam-line": capture.BEAM_LINE_LUA,
                "film-dump-own-frame": film._DUMP_OWN_FRAME, "frame-pens": mscreen.FRAME_PENS_LUA,
                "tap-remove-old": tap.REMOVE_OLD_TAP + "\n"}
    for name, text in imported.items():
        assert text.strip() and "__SCRY_" not in text, name
    assert read | set(imported) == {p.stem for p in lua_source.HERE.glob("*.lua")}


def test_the_files_are_in_stylua_s_layout() -> None:
    stylua = _tool("stylua")
    done = subprocess.run([stylua, "--check", str(lua_source.HERE)], capture_output=True,
                          text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr


def test_every_file_compiles_as_it_stands() -> None:
    luac = _luac()
    files = sorted(lua_source.HERE.glob("*.lua"))
    assert files
    for path in files:
        done = subprocess.run([luac, "-p", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("name", sorted(scripts()))
def test_every_script_compiles_and_passes_luacheck_as_sent(name: str, tmp_path: Path) -> None:
    luac, luacheck = _luac(), _tool("luacheck")
    text = scripts()[name]
    assert "__SCRY_" not in text, "a slot was left in the text sent"
    assert len(text) < transport.SCRIPT_MAX, "the console takes no longer script"
    assert not [ln for ln in text.splitlines() if ln.lstrip().startswith("--")], (
        "a comment line is sent")
    path = tmp_path / f"{name}.lua"
    path.write_text(text, encoding="utf-8")
    done = subprocess.run([luac, "-p", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    done = subprocess.run([luacheck, "--no-color", "--codes", "--config",
                           str(ROOT / ".luacheckrc"), str(path)],
                          capture_output=True, text=True, cwd=ROOT,
                          env={**os.environ, "HOME": str(tmp_path)})
    assert done.returncode == 0, done.stdout + done.stderr
