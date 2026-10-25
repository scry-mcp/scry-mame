"""The rungs this server names (`MAME_BINARY`, the PATH) and what `start` does with the build."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from server_support import _running, _stub_boot, _StubProcess
from session_doubles import fake_mame, refused

import mame_binary as binaries
import server as s

VERSION = "0.0 (a stub build)"



#: Windows runs no shebang.
POSIX_BUILDS = pytest.mark.skipif(os.name == "nt", reason="the builds are POSIX shell programs")

def build(where: Path, *, version: str = f'echo "{VERSION}"', name: str = "mame") -> Path:
    """An executable answering `-version` with the shell in `version`, console plugin beside it."""
    return fake_mame(where, name=name, version=version)
















def test_a_broken_session_answers_as_such_whatever_the_variable_names(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `MAME_BINARY` naming nothing does not hide the session's own state."""
    ses = _running(monkeypatch, tmp_path)
    ses.broken = "the stub stopped answering"
    monkeypatch.setenv(binaries.VARIABLE, str(tmp_path / "nope"))
    out = s.start(system="x", rompath="/", reference_rom="/x.bin")
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out




















def _start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(image)
    out: dict[str, Any] = s.start(system="m68k", rompath=str(tmp_path), reference_rom=str(rom),
                                  **kw)
    return out


@POSIX_BUILDS
@pytest.mark.parametrize("rung", ["argument", "MAME_BINARY", "PATH"])
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


@POSIX_BUILDS
def test_start_asks_the_version_with_the_launch_s_environment(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`-version` is asked under the launch's `env`."""
    mine = build(tmp_path, name="fake-mame", version='echo "built for ${SCRY_HINT:-nobody}"')
    out = _start(monkeypatch, tmp_path, binary=str(mine), env={"SCRY_HINT": "this launch"})
    try:
        assert out["status"] == "ok" and out["version"] == "built for this launch", out
    finally:
        s.close()


@POSIX_BUILDS
def test_start_bounds_a_hanging_version_call_by_its_own_constant(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binaries, "VERSION_TIMEOUT_S", 0.3)
    slow = build(tmp_path / "slow", name="fake-mame", version="exec sleep 5")
    out = _start(monkeypatch, tmp_path / "slow", binary=str(slow))
    try:
        assert out["status"] == "ok" and "did not return in 0.3 s" in str(out["version"]), out
    finally:
        s.close()


@POSIX_BUILDS
def test_start_bounds_the_version_call_by_the_boot_s_budget_when_it_is_shorter(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `boot_seconds` shorter than the probe's own bound is the bound."""
    slow = build(tmp_path / "slow", name="fake-mame", version="exec sleep 5")
    out = _start(monkeypatch, tmp_path / "slow", binary=str(slow), boot_seconds=0.4)
    try:
        assert out["status"] == "ok" and "did not return in 0.4 s" in str(out["version"]), out
    finally:
        s.close()


@POSIX_BUILDS
@pytest.mark.parametrize(("view", "said"), [("a\x00b", "NUL"), ("-video", "starts with `-`"),
                                            ("a\ud800", "surrogate")])
def test_a_view_no_command_line_can_carry_is_refused_before_anything_starts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: str, said: str) -> None:
    """`view` is one command-line argument: NUL, a lone surrogate and a leading `-` cannot be."""
    out = _start(monkeypatch, tmp_path, binary=str(build(tmp_path, name="fake-mame")),
                 view=view)
    refused(said, out)
    assert out["code"] == "bad_argument" and "view" in out["message"], out
