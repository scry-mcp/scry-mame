"""Every path argument is judged by one rule (`mame_inputs.absolute`), whichever tool takes it.

The server runs MAME from a scratch directory, so the relative paths these cases use exist from
the test's working directory on purpose: only the absolute rule refuses them.
"""

import contextlib
import errno
import os
import shutil
import socket
import stat
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from lua_support import _channel
from server_support import _never_spawns
from session_doubles import fake_mame, refused

import mame_binary as mbinary
import mame_files as files
import mame_launch as mlaunch
import mame_machine as mmachine
import mame_state as mstate
import mame_symbols as syms
import server as s

R_ABS = "must be an absolute path"


def _common(tmp_path: Path) -> dict[str, Any]:
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    return dict(binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom))


@pytest.fixture
def here(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The working directory, holding the relative paths the cases name, each one real."""
    _never_spawns(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    for d in ("roms", "run"):
        (tmp_path / d).mkdir()
    (tmp_path / "game.map").write_text("_start\tED000\t_TEXT\t0\tCODE\n")
    (tmp_path / "types.txt").write_text("_start: u16\n")
    (tmp_path / "boot.lua").write_text("-- a harness\n")
    (tmp_path / "v30.cfg").write_text("<mameconfig version=\"10\"/>\n")
    return tmp_path


@pytest.mark.parametrize(("argument", "value", "named", "remedy"), [
    ("binary", "fake-mame", "binary=", "must be an absolute path"),
    ("rompath", "roms", "rompath=", "must be an absolute path"),
    ("reference_rom", "ref.bin", "reference_rom=", "must be an absolute path"),
    ("symbols", "game.map", "symbols=", "must be an absolute path"),
    ("symbols", {"maincpu": "game.map"}, "symbols['maincpu']=", "must be an absolute path"),
    ("boot_lua", "boot.lua", "boot_lua=", "must be an absolute path"),
    ("inipath", "run", "inipath=", "must be an absolute path"),
    ("cfg", "v30.cfg", "cfg=", "must be an absolute path"),
    ("state_dir", "run", "state_dir=", "must be an absolute path"),
])
def test_a_relative_path_that_exists_from_here_is_refused_naming_its_argument(
        here: Path, argument: str, value: Any, named: str, remedy: str) -> None:
    out = refused("must be an absolute path", s.start(**(_common(here) | {argument: value})))
    assert out["code"] == "bad_argument" and named in out["message"], out
    assert remedy in out["message"], "the remedy rides with the rule"


@pytest.mark.parametrize(("types", "named"), [("types.txt", "types="),
                                              ({"maincpu": "types.txt"}, "types['maincpu']=")])
def test_a_relative_types_file_is_refused_naming_its_argument(
        here: Path, types: Any, named: str) -> None:
    symbols = ({"maincpu": str(here / "game.map")} if isinstance(types, dict)
               else str(here / "game.map"))
    out = refused(R_ABS, s.start(**_common(here), symbols=symbols, types=types))
    assert named in out["message"], out


@pytest.mark.parametrize(("inipath", "said"), [
    ("{d}/run;run", "inipath[1]="),
    ("{d}/run;;{d}/roms", "empty"),
    ("{d}/run;", "empty"),
])
def test_every_element_of_inipath_is_judged(here: Path, inipath: str, said: str) -> None:
    """`-inipath` is a `;`-separated list: each element is a path, an empty one a mistake."""
    out = refused("inipath", s.start(**_common(here), inipath=inipath.format(d=here)))
    assert said in out["message"], out


def test_an_inipath_that_does_not_exist_is_handed_to_mame(here: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """MAME ignores an ini directory it cannot find, so an absent absolute one reaches the spawn."""
    with pytest.raises(AssertionError, match="SPAWNED"):
        s.start(**_common(here), inipath=f"{here}/absent;{here}/run")


def test_a_relative_reference_rom_is_refused_by_rom_check_too(here: Path) -> None:
    """`rom_check` judges the file before it asks for a session."""
    _common(here)
    out = refused("must be an absolute path", s.rom_check(reference_rom="ref.bin"))
    assert "reference_rom=" in out["message"], out


@pytest.mark.parametrize(("call", "named"), [
    (lambda d: s.start(**_common(d), state_dir=f"{d}/st\x00ate"), "state_dir="),
    (lambda d: s.memdump(ref="0x0", length=4, dest=f"{d}/a\x00b.bin"), "dest="),
    (lambda d: s.snapshot(dest=f"{d}/a\x00b.png"), "dest="),
    (lambda d: s.gfx_load(path=f"{d}/a\x00b.yaml"), "path="),
])
def test_a_nul_in_a_path_is_refused_naming_it(here: Path, call: Any, named: str) -> None:
    """A NUL ends a C string, so no file call can take it."""
    out = refused("NUL", call(here))
    assert out["code"] == "bad_argument" and named in out["message"], out


def test_a_relative_manifest_gets_the_remedy_and_keeps_what_is_loaded(here: Path) -> None:
    relative = refused("must be an absolute path", s.gfx_load(path="gfx.yaml"))
    assert "would be judged in one directory" in relative["message"], relative
    assert "still_loaded" in relative, relative
    assert refused("path is empty", s.gfx_load(path=""))["code"] == "bad_argument"


def test_a_manifest_from_home_is_looked_for_there(here: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(here))
    monkeypatch.setenv("USERPROFILE", str(here))
    out = s.gfx_load(path="~/absent.yaml")
    assert out.get("code") == "bad_argument" and str(here / "absent.yaml") in out["message"], out


def test_gfx_drafts_dest_takes_the_same_rule(here: Path) -> None:
    out = refused("must be an absolute path", s.gfx_draft(dest="draft.yaml"))
    assert "dest=" in out["message"], out


def test_a_missing_input_file_is_no_such_whichever_tool_reads_it(here: Path) -> None:
    gone = here / "absent.yaml"
    manifest = refused("no such manifest", s.gfx_load(path=str(gone)))
    assert "still_loaded" in manifest, manifest
    types = refused("no such types file", s.start(**_common(here), symbols=str(here / "game.map"),
                                                  types=str(here / "absent.txt")))
    assert types["code"] == "bad_argument", types


def test_the_absolute_rule_is_said_once_for_every_argument(here: Path) -> None:
    """The same words whichever argument trips it, the argument's name the only difference."""
    sym = str(here / "game.map")
    said = {arg: refused(R_ABS, s.start(**(_common(here) | {arg: "rel"})))["message"]
            for arg in ("binary", "rompath", "reference_rom", "symbols", "boot_lua", "cfg",
                        "state_dir", "inipath")}
    said["types"] = refused("must be an absolute path", s.start(**_common(here), symbols=sym,
                                                types="rel"))["message"]
    said["path"] = refused("must be an absolute path", s.gfx_load(path="rel"))["message"]
    said["dest"] = refused(R_ABS, s.memdump(ref="0x0", length=4, dest="rel"))["message"]
    shapes = {m.replace(f"{arg}=", "<arg>=", 1) for arg, m in said.items()}
    assert len(shapes) == 1, shapes


@pytest.mark.parametrize("bad", [{"symbols": "game.map"}, {"boot_lua": "boot.lua"},
                                 {"symbols": "/abs/game.map"},
                                 {"reference_addr": "0xffff0"},
                                 {"bases": {"data": "400"}}])
def test_a_refused_input_file_leaves_a_persistent_state_dir_untouched(
        here: Path, bad: dict[str, str]) -> None:
    """`state_dir` is never deleted, so every input is judged before `cfg/` is made."""
    fresh = here / "fresh-state"
    refused("must be an absolute path|no such|OUTSIDE|no `symbols` file",
            s.start(**_common(here), state_dir=str(fresh), **bad))
    assert not fresh.exists(), sorted(p.name for p in fresh.iterdir())


def test_an_empty_entry_of_a_types_mapping_is_not_given(here: Path) -> None:
    """`""` means "not given" for a mapping entry too: the start reaches the spawn."""
    with pytest.raises(AssertionError, match="SPAWNED"):
        s.start(**_common(here), symbols={"maincpu": str(here / "game.map")},
                types={"maincpu": ""})


def test_a_types_mapping_whose_entries_are_empty_loads_the_table_untyped(here: Path) -> None:

    loaded = syms.load({"maincpu": str(here / "game.map")}, None, {"maincpu": ""},
                       [":maincpu"])
    assert loaded.tables[":maincpu"].types == {}, loaded


@pytest.mark.parametrize("call", [
    lambda dest: s.memdump(ref="0x0", length=4, dest=dest),
    lambda dest: s.snapshot(dest=dest),
])
def test_a_dest_that_is_a_dangling_link_already_exists(here: Path, call: Any) -> None:
    """A link to nowhere is something there, and a `dest` never replaces it."""
    link = here / "link.bin"
    link.symlink_to(here / "nowhere" / "target.bin")
    out = refused("already exists", call(str(link)))
    assert out["code"] == "bad_argument", out


@pytest.mark.parametrize(("char", "shown"), [("\x1b", "'\\x1b'"), ("\x7f", "'\\x7f'"),
                                             ("\x85", "'\\x85'")])
def test_a_dest_holding_a_control_character_is_refused_naming_it(
        here: Path, char: str, shown: str) -> None:
    out = refused("control character", s.memdump(ref="0x0", length=4, dest=f"{here}/a{char}b.bin"))
    assert shown in out["message"] and out["code"] == "bad_argument", out
    assert "no comma, semicolon, quote, whitespace" in out["message"], "the console's set is named"


def test_a_path_the_server_hands_the_console_is_judged_by_the_same_set() -> None:

    with pytest.raises(mstate.Invalid) as err:
        files.refuse_console_path(Path("/tmp/scr\x1batch/x.bin"))
    assert err.value.code == "host_failed" and "'\\x1b'" in str(err.value), err.value


@pytest.mark.parametrize("argument", ["state_dir", "rompath", "cfg", "binary"])
def test_a_lone_surrogate_in_any_path_argument_is_refused_naming_it(
        here: Path, argument: str) -> None:
    """No file call can encode a lone surrogate."""
    out = refused("lone surrogate", s.start(**(_common(here) | {argument: f"{here}/x\ud800"})))
    assert f"{argument}=" in out["message"] and "'\\ud800'" in out["message"], out
    dest = refused("lone surrogate", s.memdump(ref="0x0", length=4, dest=f"{here}/a\ud800b.bin"))
    assert "dest=" in dest["message"], dest


def test_a_joiner_or_a_name_in_another_script_is_a_name(here: Path) -> None:
    """A ZWJ, a ZWNJ or an accent is a real file name, so the call goes on to the session gate."""
    for name in ("a\u200db.bin", "a\u200cb.bin", "caf\u00e9.bin"):
        out = s.memdump(ref="0x0", length=4, dest=f"{here}/{name}")
        assert out["code"] == "no_session", (name, out)


def test_boot_lua_refuses_only_a_lone_surrogate(here: Path) -> None:
    """`boot_lua` never reaches a console line, so a space in its directory keeps working."""
    spaced = here / "a dir"
    spaced.mkdir()
    (spaced / "boot.lua").write_text("-- a harness\n")
    with pytest.raises(AssertionError, match="SPAWNED"):
        s.start(**_common(here), boot_lua=str(spaced / "boot.lua"))
    out = refused("surrogate", s.start(**_common(here), boot_lua=f"{here}/b\ud800.lua"))
    assert "boot_lua=" in out["message"], out


def test_a_state_whose_file_is_a_dangling_link_already_exists(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A link where the state would go is something there: refused before `statesave`."""
    ses, sta = _state_folder(monkeypatch, tmp_path)
    (sta / "linked.sta").symlink_to(tmp_path / "nowhere.sta")
    out = refused("already exists", s.state_write("save", name="linked"))
    assert out["code"] == "bad_argument" and "statesave linked" not in ses.commands, out


def _state_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Path]:

    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    sta = ses.scratch / "sta" / "m68k-dual"
    sta.mkdir(parents=True, exist_ok=True)
    return ses, sta


def _dangling_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Path, Path]:
    """A session double whose state folder holds `x.sta`, a dangling link."""
    ses, sta = _state_folder(monkeypatch, tmp_path)
    target = tmp_path / "gone" / "x.sta"
    (sta / "x.sta").symlink_to(target)
    return ses, sta / "x.sta", target


def test_state_list_lists_a_dangling_link_with_null_bytes_and_says_why(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Shown with `bytes`, `frame` and `pc` null and a `why` naming where the link points."""
    _, link, target = _dangling_state(monkeypatch, tmp_path)
    out = s.state_list()
    assert out["status"] == "ok", out
    (row,) = out["states"]
    assert row["name"] == "x" and row["path"] == str(link), row
    assert all(row[k]["available"] is False for k in ("bytes", "frame", "pc")), row
    assert str(target) in row["bytes"]["why"] and "no file is reached" in row["bytes"]["why"], row


def test_state_load_refuses_a_dangling_link_by_name(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The refusal names the link and where it points; nothing reaches the console."""
    ses, link, target = _dangling_state(monkeypatch, tmp_path)
    out = refused("no file is reached through it", s.state_write("load", name="x"))
    assert out["code"] == "unknown_ref", out
    assert str(link) in out["message"] and str(target) in out["message"], out
    assert "state_write(method=\"save\")" in out["message"], out
    assert not any(c.startswith("stateload") for c in ses.commands), ses.commands


def test_a_link_to_a_state_that_exists_is_a_state_and_a_dangling_one_hides_none_after_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only a dangling link is singled out; a link to a real state lists with its size."""
    ses, _, _ = _dangling_state(monkeypatch, tmp_path)
    sta = ses.scratch / "sta" / "m68k-dual"
    real = tmp_path / "real.sta"
    real.write_bytes(bytes(40))
    (sta / "a.sta").symlink_to(real)
    (sta / "z.sta").write_bytes(bytes(24))
    rows = {row["name"]: row for row in s.state_list()["states"]}
    assert sorted(rows) == ["a", "x", "z"], rows
    assert rows["a"]["bytes"] == 40 and rows["z"]["bytes"] == 24, rows
    assert "no file is reached" not in str(rows["a"]), rows


def _exists_letting_other_errors_out(self: Path, *, follow_symlinks: bool = True) -> bool:
    """`Path.exists` as older interpreters write it: any `OSError` but "nothing there" escapes."""
    try:
        self.stat(follow_symlinks=follow_symlinks)
    except OSError as e:
        if e.errno not in (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP):
            raise
        return False
    except ValueError:
        return False
    return True


def _mode_letting_other_errors_out(test: Any) -> Any:
    """`Path.is_file` or `Path.is_dir` as older interpreters write them."""
    def held(self: Path, *, follow_symlinks: bool = True) -> bool:
        try:
            return bool(test(self.stat(follow_symlinks=follow_symlinks).st_mode))
        except OSError as e:
            if e.errno not in (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP):
                raise
            return False
        except ValueError:
            return False
    return held


def test_a_link_into_a_directory_nobody_may_search_is_answered_like_a_dangling_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A link into an unsearchable directory is dangling on every interpreter, though older ones
    raise `PermissionError` from `exists`, `is_file` and `is_dir`: all three are held to that."""
    ses, sta = _state_folder(monkeypatch, tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "y.sta").write_bytes(bytes(24))
    (sta / "y.sta").symlink_to(locked / "y.sta")
    locked.chmod(0)
    try:
        if os.access(locked, os.X_OK):
            pytest.skip("this process may search any directory, so the case cannot be built")
        monkeypatch.setattr(Path, "exists", _exists_letting_other_errors_out)
        monkeypatch.setattr(Path, "is_file", _mode_letting_other_errors_out(stat.S_ISREG))
        monkeypatch.setattr(Path, "is_dir", _mode_letting_other_errors_out(stat.S_ISDIR))
        (row,) = s.state_list()["states"]
        assert row["bytes"]["available"] is False, row
        assert "no file is reached" in row["bytes"]["why"], row
        assert refused("no file is reached through it", s.state_write("load", name="y"))["code"] \
            == "unknown_ref"
        assert refused("already exists", s.state_write("save", name="y"))["code"] == "bad_argument"
        assert not any(c.startswith(("stateload", "statesave")) for c in ses.commands)
    finally:
        locked.chmod(0o700)


@pytest.fixture
def short_tmp() -> Iterator[Path]:
    """A directory with a path short enough to bind an AF_UNIX socket in."""
    short = Path(tempfile.mkdtemp(prefix="s"))
    yield short
    shutil.rmtree(short, ignore_errors=True)


def _not_a_file(sta: Path, tmp_path: Path, kind: str, short_tmp: Path) -> tuple[Path, str]:
    """`d.sta` made as `kind`, and the words its `why` must hold."""
    path = sta / "d.sta"
    if kind == "directory":
        path.mkdir()
        return path, "a directory"
    if kind == "link to a directory":
        (tmp_path / "elsewhere").mkdir()
        path.symlink_to(tmp_path / "elsewhere")
        return path, f"a link to {tmp_path / 'elsewhere'}, which is a directory"
    if kind == "link to a device":
        path.symlink_to("/dev/null")
        return path, "a link to /dev/null, which is a character device"
    if kind == "socket":
        short = short_tmp / "s"
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(short))
        sock.close()          # the file it bound stays, and is what the case needs
        path.symlink_to(short)
        return path, f"a link to {short}, which is a socket"
    os.mkfifo(path)
    # opened from the other end later, so a regression that opens the FIFO fails, not hangs
    threading.Thread(target=_release_fifo, args=(path,), daemon=True).start()
    return path, "a FIFO"


def _release_fifo(path: Path) -> None:
    time.sleep(3.0)
    with contextlib.suppress(OSError):
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))


_NOT_FILES = ["directory", "link to a directory", "fifo", "socket", "link to a device"]


@pytest.mark.parametrize("kind", _NOT_FILES)
def test_state_list_lists_a_sta_that_is_no_file_with_null_bytes_and_says_what_it_is(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str, short_tmp: Path) -> None:
    """Shown with `bytes`, `frame` and `pc` null and a `why` saying what is there."""
    _, sta = _state_folder(monkeypatch, tmp_path)
    path, what = _not_a_file(sta, tmp_path, kind, short_tmp)
    out = s.state_list()
    assert out["status"] == "ok", out
    (row,) = out["states"]
    assert row["name"] == "d" and row["path"] == str(path), row
    assert all(row[k]["available"] is False for k in ("bytes", "frame", "pc")), row
    assert what in row["bytes"]["why"] and "not a state" in row["bytes"]["why"], row


@pytest.mark.parametrize("kind", _NOT_FILES)
def test_state_load_refuses_a_sta_that_is_no_file_as_unknown_ref_never_a_traceback(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str, short_tmp: Path) -> None:
    """Judged by what the path resolves to before anything opens it (a FIFO would block)."""
    ses, sta = _state_folder(monkeypatch, tmp_path)
    path, what = _not_a_file(sta, tmp_path, kind, short_tmp)
    out = refused("not a state", s.state_write("load", name="d"))
    assert out["code"] == "unknown_ref", out
    assert str(path) in out["message"] and what in out["message"], out
    assert "state_write(method=\"save\")" in out["message"], out
    assert not any(c.startswith("stateload") for c in ses.commands), ses.commands
    assert refused("already exists", s.state_write("save", name="d"))["code"] == "bad_argument"


@pytest.mark.parametrize("name", ["a;b.yaml", "a b.yaml", "a(b.yaml", "a\x1bb.yaml"])
def test_gfx_drafts_dest_holds_none_of_the_characters_no_dest_may_hold(
        here: Path, name: str) -> None:
    out = refused("holds", s.gfx_draft(dest=f"{here}/{name}"))
    assert out["code"] == "bad_argument" and "dest=" in out["message"], out


def test_gfx_drafts_dest_needs_a_directory_that_exists(here: Path) -> None:

    refused("is not a directory", s.gfx_draft(dest=f"{here}/newboard/gfx.yaml"))
    assert not (here / "newboard").exists()


@pytest.mark.parametrize("call", [
    lambda d: s.gfx_draft(dest=f"{d}/afile/gfx.yaml"),
    lambda d: s.memdump(ref="0x0", length=4, dest=f"{d}/afile/x.bin"),
])
def test_a_dest_under_a_file_says_the_file_is_not_a_directory(here: Path, call: Any) -> None:
    (here / "afile").write_text("x")
    out = refused("is not a directory", call(here))
    assert str(here / "afile") in out["message"], out


def test_gfx_draft_refuses_a_link_where_the_draft_or_its_report_goes(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Replacing a link would drop it and following it would write unnamed: refused up front."""
    _channel(monkeypatch, tmp_path)
    draft = tmp_path / "l.yaml"
    draft.symlink_to(tmp_path / "nowhere.yaml")
    link = "is a link, where gfx_draft writes a file"
    assert refused(link, s.gfx_draft(dest=str(draft)))["code"] == "bad_argument"
    report = tmp_path / "r.report.json"
    report.symlink_to(tmp_path / "nowhere.json")
    assert refused(link, s.gfx_draft(dest=str(tmp_path / "r.yaml")))["code"] == "bad_argument"
    assert draft.is_symlink() and report.is_symlink()


def test_a_types_file_that_is_not_utf8_is_refused_naming_it(here: Path) -> None:
    bad = here / "types.bin"
    bad.write_bytes(b"x\xff: u16\n")
    out = refused("not UTF-8 text", s.start(**_common(here), symbols=str(here / "game.map"),
                                            types=str(bad)))
    assert out["code"] == "bad_argument" and str(bad) in out["message"], out


def test_a_types_file_nobody_may_read_is_refused_naming_it(here: Path) -> None:
    locked = here / "locked.types"
    locked.write_text("_start: u16\n")
    locked.chmod(0)
    if os.access(locked, os.R_OK):
        pytest.skip("this user reads a mode-0 file (root), so nothing is unreadable")
    out = refused("cannot read the types file", s.start(
        **_common(here), symbols=str(here / "game.map"), types=str(locked)))
    assert str(locked) in out["message"], out


@pytest.mark.parametrize(("content", "bases", "said"), [
    ("_start\tED000\t_TEXT\t0\tCODE\nstack\t2B000\t_STACK\t0\tSTACK\n", {"DATA": "0x400"}, "STACK"),
    ("- addr: 16\n  name: first\n", {"DATA": "0x400"}, "bases"),
    (b"_st\xffart\tED000\t_TEXT\t0\tCODE\n", None, "symbols: .* is not UTF-8 text"),
    ("", None, "symbols: "),
])
def test_a_fault_in_the_symbol_file_is_the_arguments_refusal(
        here: Path, content: str | bytes, bases: dict[str, str] | None, said: str) -> None:
    """A fault in the caller's symbol file is a `bad_argument`, never an exception."""
    sym = here / "faulty.map"
    if isinstance(content, bytes):
        sym.write_bytes(content)
    else:
        sym.write_text(content)
    out = refused(said, s.start(**_common(here), symbols=str(sym),
                                **({"bases": bases} if bases else {})))
    assert out["code"] == "bad_argument", out


def test_a_symbol_file_nobody_may_read_is_the_arguments_refusal(here: Path) -> None:
    locked = here / "locked.map"
    locked.write_text("_start\tED000\t_TEXT\t0\tCODE\n")
    locked.chmod(0)
    if os.access(locked, os.R_OK):
        pytest.skip("this user reads a mode-0 file (root), so nothing is unreadable")
    out = refused("cannot read the symbol file", s.start(**_common(here), symbols=str(locked)))
    assert out["code"] == "bad_argument", out


def test_the_manifest_and_the_types_file_say_not_utf8_in_one_sentence(here: Path) -> None:
    types, manifest = here / "types.bin", here / "manifest.bin"
    for bad in (types, manifest):
        bad.write_bytes(b"\xff\xfe")
    for bad, out in [
            (types, s.start(**_common(here), symbols=str(here / "game.map"), types=str(types))),
            (manifest, s.gfx_load(path=str(manifest)))]:
        said = refused("not UTF-8 text", out)["message"]
        assert said.startswith(f"{bad} is not UTF-8 text"), said


def test_a_types_line_the_grammar_reader_chokes_on_is_the_arguments_refusal(here: Path) -> None:
    """An array count too long for an int still refuses naming the file."""
    huge = here / "huge.types"
    huge.write_text("_start: u8[" + "9" * 5000 + "]\n")
    out = refused(str(huge), s.start(**_common(here), symbols=str(here / "game.map"),
                                     types=str(huge)))
    assert out["code"] == "bad_argument", out


def test_a_mapping_entrys_fault_is_named_as_the_caller_keyed_it(here: Path) -> None:

    faulty = here / "empty.map"
    faulty.write_text("")
    with pytest.raises(mstate.Invalid) as err:
        syms.load({"maincpu": str(faulty)}, None, "", [":maincpu"])
    assert str(err.value).startswith("symbols['maincpu']: "), err.value


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_a_sta_gone_between_the_listing_and_its_stat_is_left_out_never_a_traceback(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str) -> None:
    """A state removed while the folder is read is no state, and the call still answers."""
    _, sta = _state_folder(monkeypatch, tmp_path)
    gone = sta / "gone.sta"
    gone.mkdir() if kind == "directory" else gone.write_bytes(bytes(32))
    (sta / "kept.sta").write_bytes(bytes(24))
    real = os.stat

    def vanished(path: object, *a: object, **k: object) -> os.stat_result:
        if str(path).endswith("gone.sta"):
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real(path, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", vanished)
    out = s.state_list()
    assert out["status"] == "ok", out
    assert [r["name"] for r in out["states"]] == ["kept"], out
    assert refused("no state named", s.state_write("load", name="gone"))["code"] == "unknown_ref"


def test_a_home_path_reaches_mame_expanded(here: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MAME runs from its own scratch, where `~/roms` names nothing, so it gets the expansion."""
    monkeypatch.setenv("HOME", str(here))
    monkeypatch.setenv("USERPROFILE", str(here))
    seen: list[list[str]] = []
    real = mlaunch.build_command

    def build(*a: Any, **k: Any) -> list[str]:
        seen.append(real(*a, **k))
        raise mstate.Invalid("host_failed", "the case ends at the command line")
    monkeypatch.setattr(mlaunch, "build_command", build)
    monkeypatch.setattr(mmachine, "ask_listxml", lambda *_a: (None, "not asked here"))
    monkeypatch.setattr(mbinary, "facts", lambda r, *_a: {"binary": r.path})
    out = s.start(**_common(here) | {"rompath": "~/roms", "boot_lua": "~/boot.lua",
                                     "state_dir": "~/run", "inipath": "~/run",
                                     "reference_rom": "~/ref.bin"})
    assert "the case ends at the command line" in out["message"], out
    argv = seen[0]
    assert not [a for a in argv if a.startswith("~")], argv
    assert argv[argv.index("-rompath") + 1] == str(here / "roms")
    assert argv[argv.index("-inipath") + 1] == str(here / "run")


def test_a_home_manifest_and_draft_are_read_and_written_there(
        here: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(here))
    monkeypatch.setenv("USERPROFILE", str(here))
    (here / "m.yaml").write_text("not: a manifest\n")
    out = s.gfx_load(path="~/m.yaml")
    assert "cannot read" not in out.get("message", "") and "no such" not in out.get(
        "message", ""), out
    assert str(here / "m.yaml") in out.get("message", str(here / "m.yaml")), out


def test_a_console_path_is_judged_as_the_console_sees_it(
        here: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    home = here / "a b"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    out = refused("holds ' '", s.memdump(ref="0x0", length=4, dest="~/x.bin"))
    assert f"(as {home / 'x.bin'})" in out["message"], out
