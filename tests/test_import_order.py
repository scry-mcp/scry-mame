"""Every module of the server imports FIRST, alone, in an interpreter of its own.

A cycle between modules hides inside one process: once some other module has finished importing
the shared one, the cycle never runs, so a suite collected in one order passes while a lone test
file, or a client importing one module, dies at its first line. Only a fresh interpreter per
module asks each one the question it is asked in the field.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
MODULES = sorted(p.stem for p in SERVER_DIR.glob("*.py"))
CHILD_TIMEOUT_S = 60.0


def _import_alone(module: str) -> tuple[str, int | None, str]:
    """The module, its child's exit code (None when it ran past the timeout) and the last
    line it printed to stderr: a hang is one more failure in the list, never the end of it."""
    try:
        done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=SERVER_DIR,
                              capture_output=True, text=True, timeout=CHILD_TIMEOUT_S,
                              check=False)
    except subprocess.TimeoutExpired:
        return module, None, f"still importing after {CHILD_TIMEOUT_S:g} s"
    last = done.stderr.strip().splitlines()[-1:] or [""]
    return module, done.returncode, last[0]


def test_the_list_is_the_server() -> None:
    # A glob that found nothing would pass the test below having examined nothing.
    assert {"server", "mame_running", "mame_iotaps", "mame_capture", "mame_lua",
            "mame_advance", "mame_focus"} <= set(MODULES)


def test_every_module_imports_first() -> None:
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(_import_alone, MODULES))
    failing = [f"{m}: rc {rc}: {why}" for m, rc, why in results if rc != 0]
    assert not failing, "imported first, these modules fail:\n" + "\n".join(failing)
