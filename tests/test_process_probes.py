"""`process_probes`, the instrument the lifetime cells judge a pid by, against real processes."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import pytest
from process_probes import alive, children_named, gone_within, parent_of
from scry_core import guardian, host_program


def _sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen([host_program.INTERPRETER, "-c", "import time; time.sleep(60)"])


def test_a_running_child_is_alive_with_this_process_as_its_parent() -> None:
    child = _sleeper()
    try:
        assert alive(child.pid) and parent_of(child.pid) == os.getpid()
        assert not gone_within(child.pid, 0.2)
    finally:
        child.kill()
        child.wait()


def test_a_reaped_child_is_gone_and_has_no_parent() -> None:
    child = _sleeper()
    child.kill()
    child.wait()
    assert gone_within(child.pid, 5.0)
    assert not alive(child.pid) and parent_of(child.pid) is None


@pytest.mark.skipif(os.name == "nt", reason="the other half reads `ps`")
@pytest.mark.parametrize("probe", [alive, parent_of])
def test_a_ps_that_fails_is_an_error_and_not_a_process_that_is_gone(
        probe: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 2, "", "ps: illegal option")

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(OSError, match="rc=2"):
        probe(1)


@pytest.mark.skipif(os.name == "nt", reason="the guardian is a job there, not a process")
def test_the_real_guardian_is_listed_under_its_name_though_the_host_cuts_it() -> None:
    child = _sleeper()
    guard = guardian.spawn(child, "scry-mame")
    assert isinstance(guard, subprocess.Popen)
    try:
        deadline = time.monotonic() + 10.0
        while not children_named(os.getpid(), guardian.name_of("scry-mame")) \
                and time.monotonic() < deadline:
            time.sleep(0.1)
        assert children_named(os.getpid(), guardian.name_of("scry-mame")) == [guard.pid]
        assert children_named(os.getpid(), "scry-other-guardian") == []
    finally:
        guardian.stop(guard)
        child.kill()
        child.wait()
