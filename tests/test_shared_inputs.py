"""The inputs two tools share besides a ref, each read by one rule: a cpu named by whitespace alone
is no cpu; an empty pattern is every line wherever a pattern filters a log; a list of one kind of
declaration narrows to a cpu the same way for every kind; an argument that would do nothing is
refused, never dropped; and a count, a vocabulary and a name are each refused in one sentence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import refused  # noqa: E402
from test_gfx_layout import CIRCUS_CHARLAYOUT  # noqa: E402
from test_lua import _channel  # noqa: E402
from test_machine import _cached  # noqa: E402
from test_server import _running  # noqa: E402

import mame_machine as machine  # noqa: E402
import server as s  # noqa: E402


def test_a_cpu_of_whitespace_alone_is_no_cpu_for_machine_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _cached(monkeypatch, tmp_path)
    whole, blank = machine.machine_map(), machine.machine_map(cpu="  ")
    assert blank["status"] == "ok", blank
    assert blank["counts"] == whole["counts"], (blank, whole)


def test_an_empty_drive_pattern_is_refused_as_log_refuses_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    out = s.drive(act=[{"op": "status"}], pattern="")
    assert out["code"] == "bad_argument" and "'.' for every line" in out["message"], out
    assert s.log(pattern="", channel="emulator")["code"] == "bad_argument"


def test_regpoint_list_narrows_to_any_cpu_as_breakpoint_list_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only `regpoint_add` needs the visible cpu (`rpset` names none); a list narrows to any."""
    _running(monkeypatch, tmp_path)
    out = s.regpoint_list(cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert s.breakpoint_list(cpu="subcpu")["cpu"] == ":subcpu"


@pytest.mark.parametrize("tool, args", [
    ("read_block", {"tag": "blitram", "length": 4}),
    ("gfx_view", {"tag": "gfx1", "layout": CIRCUS_CHARLAYOUT, "palette": "palette"}),
    ("gfx_sweep", {"tag": "gfx1"}),
    ("gfx_locate", {"tag": "gfx1", "layouts": [CIRCUS_CHARLAYOUT], "patch": [0, 0, 8, 8]}),
])
def test_a_cpu_beside_a_block_named_by_tag_is_refused_as_doing_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str, args: dict[str, object],
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    before = list(ses.commands)
    out = refused(r"`cpu` goes with `ref`", getattr(s, tool)(cpu="subcpu", **args))
    assert out["code"] == "bad_argument" and ses.commands == before, out
    assert ses.stdin.getvalue() == b"", "nothing reached the console's pipe"
    assert getattr(s, tool)(**args)["code"] != "bad_argument", "the same call with no cpu is sound"


@pytest.mark.parametrize("tool, args, said", [
    ("record", {"frames": 2.5}, r"frames is a count; got 2\.5"),
    ("input", {"port": ":P1", "field": "Coin 1", "frames": 1.5},
     r"frames is a count; got 1\.5"),
    ("screen_view", {"mode": "zoom"}, r"mode is one of \(.*\); got 'zoom'"),
    ("scan_start", {"ref": "0x0", "length": 4, "cell_bytes": 3},
     r"cell_bytes is one of \(1, 2, 4\); got 3"),
    ("scan_filter", {"operator": "~"}, r"operator is one of \(.*\); got '~'"),
    ("palette_log", {"palette_port": "a b"}, r"palette_port='a b': .*one word with no whitespace"),
    ("gfx_blits", {"draw_command": ""}, r"draw_command='': .*one word with no whitespace"),
    ("read_block", {"tag": "a b"}, r"tag='a b': .*one word with no whitespace"),
])
def test_a_count_a_vocabulary_and_a_name_are_each_refused_in_one_sentence(
    tool: str, args: dict[str, object], said: str,
) -> None:
    out = refused(said, getattr(s, tool)(**args))
    assert out["code"] == "bad_argument", out
