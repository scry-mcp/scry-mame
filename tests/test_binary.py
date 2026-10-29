"""The rungs this server names (`MAME_BINARY`, the PATH) and what `start` does with the build."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from scry_core.host_program import absolute as _abs
from server_support import _running, _stub_boot, _StubProcess
from session_doubles import fake_mame, refused

from scry_mame import binary as binaries
from scry_mame import server as s

VERSION = "0.0 (a stub build)"



def build(where: Path, *, version: str = f"print({VERSION!r})", name: str = "mame") -> Path:
    """An executable answering `-version` with the Python in `version`, console plugin beside it."""
    return fake_mame(where, name=name, version=version)
















def test_a_broken_session_answers_as_such_whatever_the_variable_names(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `MAME_BINARY` naming nothing does not hide the session's own state."""
    ses = _running(monkeypatch, tmp_path)
    ses.broken = "the stub stopped answering"
    monkeypatch.setenv(binaries.VARIABLE, str(tmp_path / "nope"))
    out = s.start(system="x", rompath=_abs(), reference_rom=_abs("x.bin"))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out




















def _start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(image)
    out: dict[str, Any] = s.start(system="m68k", rompath=str(tmp_path), reference_rom=str(rom),
                                  **kw)
    return out


#: The PATH rung's build is a symlink, which Windows reserves to its administrators.
LINKED = pytest.mark.skipif(sys.platform == "win32", reason="Windows reserves symlinks")


@pytest.mark.parametrize("rung", ["argument", "MAME_BINARY", pytest.param("PATH", marks=LINKED)])
def test_start_launches_the_rung_it_resolved_and_says_which(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rung: str) -> None:
    """The build the boot spawns is the one the reply names, with its rung and version."""
    mine = build(tmp_path, name="fake-mame")
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
        if rung != "PATH":      # the stub intercepts only `fake-mame`
            assert _StubProcess.last_argv[0] == str(mine), _StubProcess.last_argv
    finally:
        s.close()


def test_start_with_no_rung_resolving_is_refused_in_the_envelope(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    out = _start(monkeypatch, tmp_path)
    refused("no MAME binary resolves from the PATH rung", out)
    assert out["code"] == "host_failed" and out.get("start_retries", []) == [], out


def test_start_asks_the_version_with_the_launch_s_environment(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`-version` is asked under the launch's `env`."""
    mine = build(tmp_path, name="fake-mame",
                 version="print('built for ' + os.environ.get('SCRY_HINT', 'nobody'))")
    out = _start(monkeypatch, tmp_path, binary=str(mine), env={"SCRY_HINT": "this launch"})
    try:
        assert out["status"] == "ok" and out["version"] == "built for this launch", out
    finally:
        s.close()


TESTED = f"tested on MAME {binaries.RELEASE}"


@pytest.mark.parametrize(("said", "note"), [
    (f"{binaries.RELEASE} (mame0289)", None),
    (f"{binaries.RELEASE} (unknown)", None),
    (f"{binaries.RELEASE}.1 (a point release)", None),
    (f"MAME {binaries.RELEASE} (mame0289)", None),
    ("MAME 0.290.1", "this is MAME 0.290,"),
    ("0.290 (mame0290)", "this is MAME 0.290,"),
    (f"{binaries.RELEASE}0 (a later build)", f"this is MAME {binaries.RELEASE}0,"),
    ("a build that names no release", "named no release ('a build that names no release')"),
    ("x" * 200, f"named no release ('{'x' * 80}')"),
])
def test_start_notes_a_release_other_than_the_one_it_recommends(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, said: str, note: str | None) -> None:
    """Another release boots, with a note naming it and the recommended one."""
    out = _start(monkeypatch, tmp_path, binary=str(build(tmp_path, name="fake-mame",
                                                         version=f"print({said!r})")))
    try:
        assert out["status"] == "ok" and out["recommended_release"] == binaries.RELEASE, out
        if note is None:
            assert TESTED not in out.get("note", ""), out
        else:
            assert note in out["note"] and TESTED in out["note"], out
    finally:
        s.close()


def test_start_notes_a_release_it_could_not_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slow = build(tmp_path, name="fake-mame", version="time.sleep(5)")
    out = _start(monkeypatch, tmp_path, binary=str(slow), boot_seconds=0.4)
    try:
        assert out["status"] == "ok", out
        assert "release could not be read (" in out["note"] and TESTED in out["note"], out
    finally:
        s.close()


def test_start_bounds_a_hanging_version_call_by_its_own_constant(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binaries, "VERSION_TIMEOUT_S", 0.3)
    slow = build(tmp_path / "slow", name="fake-mame", version="time.sleep(5)")
    out = _start(monkeypatch, tmp_path / "slow", binary=str(slow))
    try:
        assert out["status"] == "ok" and "did not return in 0.3 s" in str(out["version"]), out
    finally:
        s.close()


def test_start_bounds_the_version_call_by_the_boot_s_budget_when_it_is_shorter(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `boot_seconds` shorter than the probe's own bound is the bound."""
    slow = build(tmp_path / "slow", name="fake-mame", version="time.sleep(5)")
    out = _start(monkeypatch, tmp_path / "slow", binary=str(slow), boot_seconds=0.4)
    try:
        assert out["status"] == "ok" and "did not return in 0.4 s" in str(out["version"]), out
    finally:
        s.close()


@pytest.mark.parametrize(("view", "said"), [("a\x00b", "NUL"), ("-video", "starts with `-`"),
                                            ("a\ud800", "surrogate")])
def test_a_view_no_command_line_can_carry_is_refused_before_anything_starts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: str, said: str) -> None:
    """`view` is one command-line argument: NUL, a lone surrogate and a leading `-` cannot be."""
    out = _start(monkeypatch, tmp_path, binary=str(build(tmp_path, name="fake-mame")),
                 view=view)
    refused(said, out)
    assert out["code"] == "bad_argument" and "view" in out["message"], out
