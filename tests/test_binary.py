"""The binary ladder: the argument, then `MAME_BINARY`, then the PATH's `mame`, and the three
fields `start` answers with.

The builds are small shell programs of each case's own, run for real, so `shutil.which` and the
version call are exercised as they run in production. `start` itself runs on the stubbed boot
the server's own cases use (`test_server._stub_boot`), with a `fake-mame` that answers
`-version` and the console plugin beside it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from scry_core.reply_contract import Invalid
from session_doubles import fake_mame, refused
from test_server import _running, _stub_boot, _StubProcess

import mame_binary as binaries
import server as s

VERSION = "0.0 (a stub build)"


def build(where: Path, *, version: str = f'echo "{VERSION}"', name: str = "mame") -> Path:
    """An executable at `where/name` answering `-version` with the shell in `version`, and any
    other call (`-listxml`, the boot the stub stands in for) with nothing, with the console
    plugin beside it the way a source build ships it (`session_doubles.fake_mame`)."""
    return fake_mame(where, name=name, version=version)


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `mame` the PATH finds, and nothing else on the PATH."""
    found = build(tmp_path / "path-bin")
    monkeypatch.setenv("PATH", str(found.parent))
    return found


def test_the_argument_wins_over_the_variable(tmp_path: Path, on_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    mine = build(tmp_path / "arg")
    monkeypatch.setenv(binaries.VARIABLE, str(build(tmp_path / "var")))
    assert binaries.resolve(str(mine)) == binaries.Resolved(str(mine), "argument")


def test_the_variable_wins_over_the_path(tmp_path: Path, on_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    held = build(tmp_path / "var")
    monkeypatch.setenv(binaries.VARIABLE, str(held))
    assert binaries.resolve("") == binaries.Resolved(str(held), "MAME_BINARY")


def test_the_path_is_the_last_rung(on_path: Path) -> None:
    assert binaries.resolve("") == binaries.Resolved(str(on_path), "PATH")


def test_nothing_resolvable_is_refused_naming_all_three_rungs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(Invalid) as refusal:
        binaries.resolve("")
    assert refusal.value.code == "host_failed", "the host's PATH, the host's to fix"
    for rung in ("`binary` held nothing", "MAME_BINARY held nothing", "no `mame`"):
        assert rung in str(refusal.value), (rung, str(refusal.value))


def test_a_wrong_first_rung_is_refused_never_passed_over(
        tmp_path: Path, on_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A named build that is not there is refused, though the PATH holds a good one."""
    gone = str(tmp_path / "nope" / "mame")
    with pytest.raises(Invalid, match="from the argument rung") as refusal:
        binaries.resolve(gone)
    assert f"{gone} (no such file)" in str(refusal.value) and str(on_path) in str(refusal.value)
    monkeypatch.setenv(binaries.VARIABLE, gone)
    with pytest.raises(Invalid, match=r"from the MAME_BINARY rung.*\(no such file\)"):
        binaries.resolve("")


def test_a_dangling_link_is_no_such_file_not_a_missing_exec_bit(
        tmp_path: Path, on_path: Path) -> None:
    link = tmp_path / "mame"
    link.symlink_to(tmp_path / "gone")
    with pytest.raises(Invalid, match=r"\(no such file\)"):
        binaries.resolve(str(link))


def test_a_broken_session_answers_as_such_whatever_the_variable_names(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ladder is climbed after the session gate: a `MAME_BINARY` naming nothing does not
    hide the session's own state."""
    ses = _running(monkeypatch, tmp_path)
    ses.broken = "the stub stopped answering"
    monkeypatch.setenv(binaries.VARIABLE, str(tmp_path / "nope"))
    out = s.start(system="x", rompath="/", reference_rom="/x.bin")
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out


def test_a_wrong_argument_does_not_fall_through_to_the_variable(
        tmp_path: Path, on_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(binaries.VARIABLE, str(build(tmp_path / "var")))
    with pytest.raises(Invalid, match="from the argument rung"):
        binaries.resolve(str(tmp_path / "nope" / "mame"))


@pytest.mark.parametrize("given", ["mame", "bin/mame", "./mame"])
def test_a_relative_path_is_refused_in_the_argument_and_in_the_variable(
        given: str, on_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Invalid) as refusal:
        binaries.resolve(given)
    assert refusal.value.code == "bad_argument" and "binary=" in str(refusal.value)
    monkeypatch.setenv(binaries.VARIABLE, given)
    with pytest.raises(Invalid) as refusal:
        binaries.resolve("")
    assert refusal.value.code == "bad_argument" and "MAME_BINARY=" in str(refusal.value)


def test_the_path_answered_is_the_file_which_approved(tmp_path: Path, on_path: Path) -> None:
    """Through a symlinked directory, `..` names the target's parent; collapsed by spelling it
    would name a file beside the link, which is not the one checked."""
    target = tmp_path / "real" / "deep"
    target.mkdir(parents=True)
    build(tmp_path / "real")
    (tmp_path / "link").symlink_to(target)
    given = str(tmp_path / "link" / ".." / "mame")
    assert binaries.resolve(given).path == given


def test_the_version_is_the_first_line_from_either_stream_whatever_the_exit_code(
        tmp_path: Path) -> None:
    assert binaries.version(str(build(tmp_path))) == VERSION
    on_stderr = build(tmp_path / "err", version='printf "\\n  v 1.2  \\n" >&2; exit 1')
    assert binaries.version(str(on_stderr)) == "v 1.2"


def test_a_version_call_that_prints_nothing_is_unavailable(tmp_path: Path) -> None:
    got = binaries.version(str(build(tmp_path, version="exit 1")))
    assert got == {"available": False,
                   "why": f"`{tmp_path / 'mame'} -version` printed nothing (rc=1)"}


def test_a_version_call_that_hangs_is_unavailable_within_its_bound(
        tmp_path: Path) -> None:
    got = binaries.version(str(build(tmp_path, version="exec sleep 5")), seconds=0.2)
    assert isinstance(got, dict) and got["available"] is False
    assert "did not return in 0.2 s" in got["why"], got


def test_a_version_call_that_cannot_run_is_unavailable(tmp_path: Path) -> None:
    got = binaries.version(str(tmp_path / "gone"))
    assert isinstance(got, dict) and got["available"] is False and "could not run" in got["why"]


def test_a_relative_path_entry_through_a_link_names_the_file_which_found(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "real" / "deep"
    target.mkdir(parents=True)
    build(tmp_path / "real" / "bin")
    (tmp_path / "link").symlink_to(target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "link/../bin")
    got = binaries.resolve("")
    assert Path(got.path).resolve() == (tmp_path / "real" / "bin" / "mame").resolve(), got


def test_the_path_rung_answers_an_absolute_path(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    build(tmp_path / "rel")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "rel")
    got = binaries.resolve("")
    assert got == binaries.Resolved(os.path.join(str(tmp_path), "rel", "mame"), "PATH")


# ------------------------------------------------------------------------- through `start`

def _start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(image)
    out: dict[str, Any] = s.start(system="m68k", rompath=str(tmp_path), reference_rom=str(rom),
                                  **kw)
    return out


@pytest.mark.parametrize("rung", ["argument", "MAME_BINARY", "PATH"])
def test_start_launches_the_rung_it_resolved_and_says_which(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rung: str) -> None:
    """Each rung through the tool itself: the build the boot is spawned from is the one the
    reply names, with the rung and the build's own version line."""
    mine = build(tmp_path, name="fake-mame")       # the name the stubbed boot answers for
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    kw: dict[str, Any] = {}
    if rung == "argument":
        kw["binary"] = str(mine)
    elif rung == "MAME_BINARY":
        monkeypatch.setenv("MAME_BINARY", str(mine))
    else:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "mame").symlink_to(mine)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    out = _start(monkeypatch, tmp_path, **kw)
    try:
        assert out["status"] == "ok", out
        expected = str(tmp_path / "bin" / "mame") if rung == "PATH" else str(mine)
        assert (out["binary"], out["binary_origin"], out["version"]) == (expected, rung, VERSION)
        if rung != "PATH":      # the stubbed boot intercepts only a build named `fake-mame`
            assert _StubProcess.last_argv[0] == str(mine), _StubProcess.last_argv
    finally:
        s.close()


def test_start_with_no_rung_resolving_is_refused_in_the_envelope(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    out = _start(monkeypatch, tmp_path)
    refused("no MAME binary resolves from the PATH rung", out)
    assert out["code"] == "host_failed" and out["start_retries"] == [], out


def test_start_asks_the_version_with_the_launch_s_environment(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A build that needs the caller's `env` to load answers `-version` under it, as the boot
    will run."""
    mine = build(tmp_path, name="fake-mame", version='echo "built for ${SCRY_HINT:-nobody}"')
    out = _start(monkeypatch, tmp_path, binary=str(mine), env={"SCRY_HINT": "this launch"})
    try:
        assert out["status"] == "ok" and out["version"] == "built for this launch", out
    finally:
        s.close()


def test_start_bounds_a_hanging_version_call_by_its_own_constant(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binaries, "VERSION_TIMEOUT_S", 0.3)    # the bound, shortened
    slow = build(tmp_path / "slow", name="fake-mame", version="exec sleep 5")
    out = _start(monkeypatch, tmp_path / "slow", binary=str(slow))
    try:
        assert out["status"] == "ok" and "did not return in 0.3 s" in str(out["version"]), out
    finally:
        s.close()


@pytest.mark.parametrize(("view", "said"), [("a\x00b", "NUL"), ("-video", "starts with `-`"),
                                            ("a\ud800", "surrogate")])
def test_a_view_no_command_line_can_carry_is_refused_before_anything_starts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: str, said: str) -> None:
    """`view` becomes one argument of MAME's command line: a NUL or a lone surrogate cannot
    be passed at all, and a leading `-` would be read as an option of its own."""
    out = _start(monkeypatch, tmp_path, binary=str(build(tmp_path, name="fake-mame")),
                 view=view)
    refused(said, out)
    assert out["code"] == "bad_argument" and "view" in out["message"], out
