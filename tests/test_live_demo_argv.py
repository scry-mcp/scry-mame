"""The live check's demo loop: the argv it builds parses under every demo's own parser."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from scry_core import demo as demo_core

ROOT = Path(__file__).resolve().parents[1]
DEMOS = sorted(d.name for d in (ROOT / "demos").iterdir() if (d / "demo.py").is_file())


def _argv_module() -> object:
    spec = importlib.util.spec_from_file_location("demo_argv", ROOT / "tests/live/demo_argv.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", DEMOS)
def test_the_argv_the_loop_builds_parses_under_the_demo_s_own_parser(name: str) -> None:
    demo = demo_core.load(ROOT / "demos" / name / "demo.py")
    argv = _argv_module().demo_argv(demo, Path("/roms"), Path("/game"))  # type: ignore[attr-defined]
    parsed = demo_core._parser(demo).parse_args(argv)
    assert Path(parsed.rompath) == Path("/roms")
    given = getattr(parsed, "cwd", None)
    assert (given is not None and Path(given) == Path("/game")) == ("cwd" in demo.offers)


def test_at_least_one_demo_takes_the_game_s_checkout_and_one_does_not() -> None:
    takes = [name for name in DEMOS
             if "cwd" in demo_core.load(ROOT / "demos" / name / "demo.py").offers]
    assert takes and len(takes) < len(DEMOS)
