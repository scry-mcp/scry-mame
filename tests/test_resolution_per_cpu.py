"""A ref resolves against the table of the call's cpu: the cpu the call names, else
the visible one. A name only one cpu's program has is that cpu's; the same name in both tables is
not ambiguous, because the cpu decides; a condition takes its symbols from the table of the cpu
its row is armed on.
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import refused  # noqa: E402
from test_server import _running, _RunningSession  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_conditions as conditions  # noqa: E402
import mame_inputs as inputs  # noqa: E402
import mame_machine as machine  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_tally as tally  # noqa: E402
import server as s  # noqa: E402

MAIN, SUB = ":maincpu", ":subcpu"


def _two_programs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _RunningSession:
    """The running double on m68k-dual's two cpus with the thread patch, one table per cpu:
    `irq_vblank` in both at two addresses, and a name in each that the other lacks."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: MAIN, 2: SUB}
    monkeypatch.setattr(mstate.STATE, "tables", {
        MAIN: g.SymbolTable({"IRQ_VBLANK": 0x400, "MAIN_ONLY": 0x500}, {}, "yaml"),
        SUB: g.SymbolTable({"IRQ_VBLANK": 0x542, "SUB_ONLY": 0x600}, {}, "yaml",
                           types={"SUB_ONLY": "u16"})})
    return ses


def test_a_reader_resolves_on_the_named_cpu_else_the_visible_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    assert s.read_memory(ref="irq_vblank", length=2)["addr"] == "0x00000400"
    sub = s.read_memory(ref="irq_vblank", length=2, cpu="subcpu")
    assert sub["addr"] == "0x00000542" and sub["cpu"] == SUB, sub
    ses.visible_cpu = SUB
    assert s.read_memory(ref="irq_vblank", length=2)["addr"] == "0x00000542", "the visible one's"
    refused(re.escape(inputs.not_a_ref("the ref", "sub_only", ":maincpu", loaded=2)),
            s.read_memory(ref="sub_only", length=2, cpu="maincpu"))
    assert s.write(ref="sub_only", data_hex="0102", cpu="subcpu")["addr"] == "0x00000600"
    assert s.disassemble(ref="sub_only", length=4)["addr"] == "0x00000600"


def test_the_same_name_in_both_tables_arms_on_the_cpu_the_call_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    main = s.breakpoint_at(ref="irq_vblank")
    sub = s.breakpoint_at(ref="irq_vblank", cpu="subcpu")
    assert (main["addr"], main["cpu"]) == ("0x00000400", MAIN), main
    assert (sub["addr"], sub["cpu"]) == ("0x00000542", SUB), sub
    assert "bp 0x400::maincpu" in ses.commands and "bp 0x542::subcpu" in ses.commands
    listed = {(b["cpu"], b["addr"]) for b in s.breakpoint_list()["breakpoints"]}
    assert listed == {(MAIN, "0x00000400"), (SUB, "0x00000542")}


def test_a_name_only_the_other_cpu_has_is_unresolved_on_this_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _two_programs(monkeypatch, tmp_path)
    here = s.breakpoint_at(ref="sub_only")
    assert here["state"] == "unresolved" and here["cpu"] == MAIN, here
    there = s.breakpoint_at(ref="sub_only", cpu="subcpu")
    assert there["addr"] == "0x00000600" and there["cpu"] == SUB, there
    watched = s.watch_add(ref="sub_only", mode="show", cpu="subcpu")
    assert watched["fmt"] == "u16", "typed by the sub cpu's own types"


def test_a_condition_takes_its_symbols_from_the_table_of_the_cpu_it_arms_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    ses.exprs["{w@0x600==1}"] = 1
    out = s.breakpoint_at(ref="0x4a0", condition="w@sub_only==1", cpu="subcpu")
    assert out["condition"] == "w@0x600==1", out
    assert any(c.startswith("bp 0x4a0::subcpu,w@0x600==1") for c in ses.commands), ses.commands
    # EVALUATED ON THE CPU IT ARMS ON: `print` reads the visible cpu's symbols, so the sub cpu
    # is shown for the evaluation and the main one put back, and nothing ran.
    judged = ses.commands.index("print {w@0x600==1}")
    assert ses.commands[judged - 1] == "Hc2" and ses.commands[judged + 1] == "Hc1", ses.commands
    assert ses.visible_cpu == MAIN


def test_a_condition_on_a_cpu_the_stub_cannot_show_is_refused_naming_focus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    ses.threads = {}                                   # a build without the thread patch
    out = s.breakpoint_at(ref="0x4a0", condition="d0==1", cpu="subcpu")
    assert out["status"] == "INVALID" and "`focus(cpu=" in out["message"], out
    assert not any(c.startswith("bp ") for c in ses.commands), "nothing armed"


def test_run_to_takes_its_target_from_the_named_cpus_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    s.breakpoint_at(ref="sub_only", role="control", cpu="subcpu")
    ses.stops_after_polls = 1
    s.run_to(ref="irq_vblank", cpu="subcpu", seconds=1.0)
    assert "bp 0x542::subcpu" in ses.commands, ses.commands


def test_symbols_find_looks_in_the_named_cpus_table_and_says_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    main = s.symbols_find(name="irq_vblank")
    assert main["cpu"] == MAIN and main["symbols"][0]["addr"] == "0x00000400", main
    sub = s.symbols_find(name="irq_vblank", cpu="subcpu")
    assert sub["cpu"] == SUB and sub["symbols"][0]["addr"] == "0x00000542", sub
    assert "map 0x542::subcpu" in ses.commands, "what the address IS, to that cpu"
    placed = s.symbols_find(linear="0x610", cpu="subcpu")
    assert (placed["name"], placed["delta"]) == ("SUB_ONLY", 0x10), placed
    refused("no cpu 'audiocpu'", s.symbols_find(name="x", cpu="audiocpu"))
    ses.visible_cpu = SUB
    assert s.symbols_find(name="sub_only")["cpu"] == SUB, "no cpu named: the visible one's"


def test_a_symbol_spelled_like_a_register_is_judged_against_its_own_cpus_registers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no names gathered for a cpu, its registers are its own thread's description, never
    the first cpu's."""
    ses = _two_programs(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "layout", lambda thread: SimpleNamespace(
        register_names=["D0"] if thread == 1 else ["SR2"]))
    mstate.STATE.tables[SUB] = g.SymbolTable({"SR2": 0x700}, {}, "yaml")
    mstate.STATE.tables[MAIN] = g.SymbolTable({"SR2": 0x700}, {}, "yaml")
    with pytest.raises(mstate.Invalid, match="both a symbol of the table and a name"):
        conditions.console_condition("sr2==1", SUB)
    assert conditions.console_condition("sr2==1", MAIN) == "0x700==1"


def test_the_symbol_coverage_names_each_tables_cpu_and_narrows_to_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _two_programs(monkeypatch, tmp_path)
    mstate.STATE.tables[MAIN] = g.SymbolTable({"A": 0x400}, {}, "tsv",
                                              class_span={"DATA": (0x400, 0x4FF)},
                                              classes={"A": "DATA"})
    mstate.STATE.tables[SUB] = g.SymbolTable({"B": 0x800}, {}, "tsv",
                                             class_span={"DATA": (0x800, 0x8FF)},
                                             classes={"B": "DATA"})
    monkeypatch.setattr(mstate.STATE, "machine_map", {
        **{name: [] for name in machine.SECTIONS}, "cpus": [{"tag": MAIN}, {"tag": SUB}],
        "sources": {}, "note": ""})
    rows = machine.machine_map()["symbol_coverage"]
    assert [(r["cpu"], r["span"]["from"]) for r in rows] == [(MAIN, "0x00000400"),
                                                            (SUB, "0x00000800")]
    sub = machine.machine_map(cpu="subcpu")["symbol_coverage"]
    assert [(r["cpu"], r["class"]) for r in sub] == [(SUB, "DATA")]


def test_a_tallys_writers_are_placed_in_the_table_of_the_cpu_it_counts_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _two_programs(monkeypatch, tmp_path)
    dump: dict[str, Any] = {"pcs": [(0x604, 3)], "cpu": SUB}
    assert tally._writer_rows(dump, 5) == [
        {"pc": "0x00000604", "count": 3, "symbol": "SUB_ONLY+0x4"}]


def test_auto_decides_a_hex_shaped_name_by_the_table_of_its_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`beef` is a name where that cpu's table has it, and refused where it does not, with the
    `0x` spelling that would make it an address there."""
    _two_programs(monkeypatch, tmp_path)
    mstate.STATE.tables[SUB] = g.SymbolTable({"BEEF": 0x640}, {}, "yaml")
    sub = s.breakpoint_at(ref="beef", cpu="subcpu")
    assert (sub["by"], sub["addr"]) == ("symbol", "0x00000640"), sub
    main = s.breakpoint_at(ref="beef")
    assert main["code"] == "unknown_ref" and "written 0xbeef" in main["message"], main
    main = s.breakpoint_at(ref="0xbeef")
    assert (main["by"], main["addr"]) == ("address", "0x0000beef"), main


def test_find_and_memdump_take_their_place_from_the_named_cpus_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    mstate.STATE.tables[SUB] = g.SymbolTable({"SUB_ONLY": 0x600}, {}, "tsv",
                                             class_span={"DATA": (0x600, 0x6FF)},
                                             classes={"SUB_ONLY": "DATA"})
    refused("no symbol class 'DATA'", s.find(symbol_class="DATA", data_hex="4e71"))
    s.find(symbol_class="DATA", data_hex="4e71", cpu="subcpu")
    assert "find 0x600::subcpu,0x100,0x4e,0x71" in ses.commands, ses.commands
    s.memdump(ref="sub_only", length=16, dest=str(tmp_path / "d.bin"), cpu="subcpu")
    assert any(c.startswith("save ") and ",0x600::subcpu," in c for c in ses.commands), \
        ses.commands
