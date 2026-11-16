"""`scry_core.probe` judged on this server's own surface: tasks, captures, pre-gate check, texts."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from scry_core import probe, probe_checks
from scry_core.host_program import absolute as _abs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mcp_probe"

# At collection: `servers.load` says why.
REPO = probe_checks.repository(ROOT)
SURFACE = probe.load_surface(REPO, "mame")


def _tasks() -> list[dict[str, Any]]:
    text = (FIXTURES / "tasks" / "mame.json").read_text()
    doc: dict[str, list[dict[str, Any]]] = json.loads(text)
    return doc["tasks"]




def _narrowed() -> probe.Surface:
    return probe_checks.narrowed(SURFACE, _tasks())


def _judge(task_id: str, line: str) -> probe.Verdict:
    return probe_checks.judge_line(SURFACE, _tasks(), task_id, line)


def test_the_tasks_cover_the_server() -> None:
    assert probe_checks.refused(REPO, "mame") == []


def test_every_task_is_captured_and_judged_as_it_was() -> None:
    assert probe_checks.captures_misjudged(REPO, "mame") == []


def test_the_probe_reads_the_server_the_suite_imports() -> None:
    from scry_mame import mcp as mame_mcp
    from scry_mame import server

    assert REPO.modules["mame"] is server and REPO.checks["mame"] is mame_mcp.probe_check


def test_every_instructions_and_tool_description_fits_the_client_cap(
        capsys: pytest.CaptureFixture[str]) -> None:
    """Over the cap fails; the margins print on every run."""
    with capsys.disabled():
        print("\nthe texts nearest the client's cap:\n  " + "\n  ".join(probe_checks.margins(REPO)))
    if over := probe_checks.over_cap(REPO):
        pytest.fail("\n".join(over), pytrace=False)


def test_the_servers_own_check_takes_a_right_call() -> None:
    line = 'M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}'
    assert _judge("M1", line).right


def test_the_mame_check_receives_the_defaults_the_tool_would_pass() -> None:
    task = {"id": "M1", "prompt": "p", "tool": "read_memory", "args": {"ref": "PlayerX"},
            "allow": ["length"]}
    for length, right in [(1024, True), (1025, False), (0, False)]:
        line = f'M1: {{"tool": "read_memory", "args": {{"ref": "PlayerX", "length": {length}}}}}'
        assert probe.judge(_narrowed(), task, probe.parse(line, ["M1"])["M1"]).right is right


def test_a_task_whose_right_answer_the_server_refuses_is_refused() -> None:
    task = {"id": "M1", "prompt": "p", "tool": "read_memory",
            "args": {"ref": "PlayerX", "length": {"any_of": [0, 6]}}}
    problems = probe.task_problems(_narrowed(), [task])
    assert problems == ["mame task M1: its own expected call is refused: the server's check "
                        "refuses it: length=0 is outside 1..1024: for more bytes use `memdump`, "
                        "which writes them to a file instead of into the reply"]


@pytest.mark.parametrize(("boot_lua", "said"), [
    ("emu.print('booted')", "boot_lua=\"emu.print('booted')\" must be an absolute path"),
    ("harness.lua", "boot_lua='harness.lua' must be an absolute path"),
])
def test_a_start_whose_expected_boot_lua_is_not_a_path_is_refused(boot_lua: str, said: str) -> None:
    """`start` is judged by the shape of its paths: inline Lua or an unexpanded `~` is refused."""
    task = {"id": "M1", "prompt": "p", "tool": "start",
            "args": {"binary": _abs("b", "mame"), "system": "m68k-dual", "rompath": _abs("r"),
                     "reference_rom": _abs("r", "rom.bin"), "boot_lua": boot_lua}}
    (problem,) = probe.task_problems(SURFACE, [task])
    assert problem.startswith("mame task M1: its own expected call is refused: the server's "
                              "check refuses it: "), problem
    assert said in problem, problem


def test_a_start_with_absolute_paths_is_judged_by_shape_not_by_what_is_on_disk() -> None:
    """The control: paths no machine holds are taken; a file being there is the host's to judge."""
    task = {"id": "M1", "prompt": "p", "tool": "start",
            "args": {"binary": _abs("no", "such", "mame"), "system": "m68k-dual",
                     "rompath": _abs("no", "roms"),
                     "reference_rom": _abs("no", "rom.bin"), "boot_lua": _abs("no", "harness.lua"),
                     "symbols": {"maincpu": _abs("no", "a.map")}}}
    assert probe.task_problems(SURFACE, [task]) == []
