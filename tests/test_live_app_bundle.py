"""(tests/live/app_bundle.py) A minimal `.app` around a build: the launcher it names, the build
it runs beside itself, and the working directory it changes into before exec."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

LIVE = Path(__file__).resolve().parent / "live"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("app_bundle", LIVE / "app_bundle.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app_bundle = _load()

DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="`open` launches a `.app` on macOS")


@DARWIN
def test_the_bundle_names_its_launcher_and_runs_the_build_beside_it(tmp_path: Path) -> None:
    source = tmp_path / "build"
    (source / "plugins").mkdir(parents=True)
    (source / "mame").write_text("#!/bin/sh\n")
    app = app_bundle.build(source, tmp_path / "stage")
    macos = app / "Contents" / "MacOS"
    assert app_bundle.executable_of(app) == app_bundle.LAUNCHER
    launcher = macos / app_bundle.LAUNCHER
    assert launcher.is_file() and os.access(launcher, os.X_OK)
    assert (macos / "mame").resolve() == (source / "mame").resolve()
    assert (macos / "plugins").resolve() == (source / "plugins").resolve()


@DARWIN
def test_the_launcher_changes_directory_and_execs_the_emulator_keeping_its_pid(
        tmp_path: Path) -> None:
    """The whole point: MAME writes its logs beside the working directory `open` cannot set."""
    source = tmp_path / "build"
    source.mkdir()
    seen = tmp_path / "seen.txt"
    probe = source / "probe"
    probe.write_text(f"#!/bin/sh\npwd > {seen}\necho $$ >> {seen}\nexit 0\n")
    probe.chmod(probe.stat().st_mode | stat.S_IEXEC)
    app = app_bundle.build(source, tmp_path / "stage", name="probe")
    launcher = app / "Contents" / "MacOS" / app_bundle.LAUNCHER
    proc = subprocess.Popen([str(launcher), "an-argument"],
                            env={**os.environ, "SCRY_APP_CWD": str(tmp_path)})
    assert proc.wait(timeout=10) == 0
    said = seen.read_text().split()
    assert said[0] == str(tmp_path)
    assert said[1] == str(proc.pid), "`exec` keeps the pid the run started with"
