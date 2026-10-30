"""`read.placer`: one sort per table, then a bisection per address, answering exactly what
the old rule did (the highest symbol at or below, ties to the first row of the file), because a
trace places every executed address and a table scan per address is the cost that would
dominate."""

from __future__ import annotations

import gzip
import random
import re
from pathlib import Path

import pytest

from scry_mame import gdb_session as gs
from scry_mame import read
from scry_mame.state import STATE

FIXTURES = Path(__file__).parent / "fixtures" / "trace"
TRACES = ("m68k-dual-maincpu-2f.trace.gz", "m68k-dual-subcpu-2f.trace", "v30-alt-2f.trace.gz",
          "circus-2f.trace")


def old_rule(table: dict[str, int], addr: int) -> tuple[int, str] | None:
    below = [(a, n) for n, a in table.items() if a <= addr]
    if not below:
        return None
    top = max(a for a, _ in below)
    return top, next(n for a, n in below if a == top)


def install(monkeypatch: pytest.MonkeyPatch, table: dict[str, int]) -> gs.SymbolTable:
    t = gs.SymbolTable(table=table, by_class={}, format="yaml")
    monkeypatch.setattr(STATE, "tables", {":maincpu": t})
    monkeypatch.setattr(STATE, "first_cpu", ":maincpu")
    return t


def seeded_table(seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    table: dict[str, int] = {}
    addrs = [rng.randrange(0x100, 0x4000) for _ in range(300)]
    for i, a in enumerate(addrs):
        table[f"SYM{i:03d}"] = a
    # deliberate duplicates: several names at one address, so the tie rule is exercised
    for i in range(40):
        table[f"DUP{i:02d}"] = addrs[rng.randrange(len(addrs))]
    return table


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_placer_answers_the_old_rule_over_a_range_past_both_ends(
        monkeypatch: pytest.MonkeyPatch, seed: int) -> None:
    table = seeded_table(seed)
    install(monkeypatch, table)
    lo, hi = min(table.values()), max(table.values())
    place = read.placer(":maincpu")
    for addr in range(lo - 0x40, hi + 0x40):
        assert place(addr) == old_rule(table, addr), hex(addr)
        assert read.nearest_symbol(addr, ":maincpu") == old_rule(table, addr), hex(addr)


def test_a_tie_goes_to_the_first_row_of_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"OMEGA": 0x100, "ALPHA": 0x100, "BETA": 0x100, "NEXT": 0x200})
    assert read.placer(":maincpu")(0x100) == (0x100, "OMEGA")
    assert read.placer(":maincpu")(0x1FF) == (0x100, "OMEGA")
    assert read.symbol_label(0x104, ":maincpu") == "OMEGA+0x4"


def test_the_second_row_of_a_repeated_name_still_places_its_own_address(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    y = tmp_path / "s.yaml"
    y.write_text("- addr: 256\n  name: count\n- addr: 512\n  name: count\n", encoding="utf-8")
    t = gs.symbols(str(y))
    monkeypatch.setattr(STATE, "tables", {":maincpu": t})
    monkeypatch.setattr(STATE, "first_cpu", ":maincpu")
    assert read.placer(":maincpu")(0x204) == (0x200, "count")


def test_an_address_below_every_symbol_is_not_placed(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"LOW": 0x100})
    assert read.placer(":maincpu")(0xFF) is None
    assert read.symbol_label(0xFF, ":maincpu") is None
    assert read.placer(":maincpu")(0x100) == (0x100, "LOW")


def test_an_empty_table_places_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {})
    assert read.placer(":maincpu")(0x1234) is None


def test_a_table_replaced_whole_is_placed_afresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """`start` replaces the tables whole: the placer is memoized on the table object, so the
    next table is never answered from the last one's sort."""
    install(monkeypatch, {"OLD": 0x100})
    assert read.placer(":maincpu")(0x180) == (0x100, "OLD")
    install(monkeypatch, {"NEW": 0x140})
    assert read.placer(":maincpu")(0x180) == (0x140, "NEW")


def trace_pcs(name: str) -> list[int]:
    raw = (FIXTURES / name).read_bytes()
    text = (gzip.decompress(raw) if name.endswith(".gz") else raw).decode()
    return sorted({int(m.group(1), 16) for m in re.finditer(r"^([0-9A-F]+): ", text, re.M)})


@pytest.mark.parametrize("name", TRACES)
def test_the_placer_answers_the_old_rule_over_a_captured_trace(
        monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    pcs = trace_pcs(name)
    assert pcs, f"{name}: no instruction line, the case would examine nothing"
    rng = random.Random(name)
    # a table built from the trace itself: every few pcs a symbol, some sharing one address
    table = {f"R{i:04d}": pc for i, pc in enumerate(pcs[1::5])}
    table.update({f"T{i:02d}": rng.choice(pcs) for i in range(8)})
    install(monkeypatch, table)
    place = read.placer(":maincpu")
    for pc in pcs:
        assert place(pc) == old_rule(table, pc), hex(pc)
