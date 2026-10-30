"""`process_probes`, the instrument the lifetime cells judge a pid by, against real processes."""
from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest
from process_probes import alive, gone_within, parent_of
from scry_core import host_program


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
