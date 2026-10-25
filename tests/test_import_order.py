"""Each server module imported first, alone: cycles hide in shared processes."""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
MODULES = sorted(p.stem for p in SERVER_DIR.glob("*.py"))
CHILD_TIMEOUT_S = 60.0


def _import_alone(module: str) -> tuple[str, int | None, str]:
    """The module, its exit code (None on timeout), last stderr line."""
    try:
        done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=SERVER_DIR,
                              capture_output=True, text=True, timeout=CHILD_TIMEOUT_S,
                              check=False)
    except subprocess.TimeoutExpired:
        return module, None, f"still importing after {CHILD_TIMEOUT_S:g} s"
    last = done.stderr.strip().splitlines()[-1:] or [""]
    return module, done.returncode, last[0]


def test_the_list_is_the_server() -> None:
    # An empty glob would make the next test examine nothing.
    assert {"server", "mame_running", "mame_iotaps", "mame_capture", "mame_lua",
            "mame_advance", "mame_focus"} <= set(MODULES)


def test_every_module_imports_first() -> None:
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(_import_alone, MODULES))
    failing = [f"{m}: rc {rc}: {why}" for m, rc, why in results if rc != 0]
    assert not failing, "imported first, these modules fail:\n" + "\n".join(failing)
