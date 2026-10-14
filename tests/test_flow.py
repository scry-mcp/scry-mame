"""The flow class of a listing's lines, off the mnemonic table of each cpu type.

The listings are CAPTURED, never authored: the same range written by the console's `dasm` with
its opcode bytes and without them, on the 68000 board of tch-blitter and the V30 board of lineup
(`fixtures/console/PROVENANCE.txt`). Each expected class was checked by hand against what the
instruction does, not against what the table says.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import mame_flow as flow

FIXTURES = Path(__file__).parent / "fixtures" / "console"


def _pair(name: str) -> tuple[list[str], list[str]]:
    """The two listings of one range, and the address of every line of the first."""
    lines = [x for x in (FIXTURES / f"{name}.txt").read_text().splitlines() if x.strip()]
    bare = [x for x in (FIXTURES / f"{name}.bare.txt").read_text().splitlines() if x.strip()]
    return bare, [re.match(r"^([0-9A-Fa-f]+):", x).group(1) for x in lines]  # type: ignore[union-attr]


def test_a_68000_listing_names_its_call_its_branch_and_its_return() -> None:
    """`beq $588` branches on a condition, `jsr $f2984.l` calls and comes back, `rte` returns
    from the interrupt; every other line of the stretch falls through to the next."""
    bare, addresses = _pair("dasm.m68k.560")
    classes = flow.classify_listing(bare, addresses, "m68000")
    assert classes is not None
    marked = {a: c for a, c in zip(addresses, classes, strict=True) if c != flow.SEQUENTIAL}
    assert marked == {"000578": "branch", "00058C": "call", "00059A": "return"}, marked


def test_a_v30_listing_names_every_flow_word_and_reads_past_a_prefix() -> None:
    """`br` jumps, `call` calls, `bc`, `be` and `dbnz` branch on a condition, `reti` returns
    from the interrupt, and `rep stmw` is the store it repeats, not a word of its own."""
    bare, addresses = _pair("dasm.v30.30000")
    classes = flow.classify_listing(bare, addresses, "v30")
    assert classes is not None
    by_addr = dict(zip(addresses, classes, strict=True))
    assert {a for a, c in by_addr.items() if c == "call"} == {
        "30005", "3000B", "3000E", "30011", "30014", "3001A", "30020", "30023", "30026"}
    assert {a for a, c in by_addr.items() if c == "branch"} == {
        "30002", "30029", "3002B", "3002F", "3005E", "300A9"}
    assert {a for a, c in by_addr.items() if c == "return"} == {"300AC"}
    assert by_addr["3006C"] == by_addr["3007F"] == "sequential", "rep stmw, rep movbkw"
    assert flow.UNKNOWN not in classes, "every word of a V30's own stretch is in its table"


@pytest.mark.parametrize(("text", "cpu_type"), [
    ("dc.w    $000f; ILLEGAL", "m68000"),   # the 68000's illegal word
    ("rtd     #$4", "m68000"),              # a 68010 word, which a 68000 does not execute
    ("???", "v30"),                         # what `necdasm` prints for a byte it cannot decode
    ("brkn    5h", "v30"),                  # a V25S word `necdasm` prints for a V30 too
    ("fimul   word ptr [bw]", "v30"),       # an x87 word, for a coprocessor these boards lack
    ("rep", "v30"),                         # a prefix with nothing after it
])
def test_a_word_the_table_does_not_list_is_unknown_never_sequential(text: str,
                                                                     cpu_type: str) -> None:
    assert flow.classify(text, cpu_type) == flow.UNKNOWN


@pytest.mark.parametrize(("text", "cpu_type", "expected"), [
    # THE ADDRESSING MODE DOES NOT MOVE THE CLASS on either table: every form of `jsr`/`call`
    # carries MAME's STEP_OVER and every form of `jmp`/`br` carries no flag, register-indirect
    # and far ones included, so the mnemonic alone decides without guessing.
    ("jsr     (A0)", "m68000", "call"),
    ("jmp     ($4,PC,D0.w)", "m68000", "branch"),
    ("call    far ptr [bw]", "v30", "call"),
    ("br      word ptr [bw]", "v30", "branch"),
    # A SIZE SUFFIX is the 68000's and is not part of the word.
    ("move.w  D0, D1", "m68000", "sequential"),
    ("chk.w   D1, D0", "m68000", "call"),
    ("trap    #$0", "m68000", "call"),      # unflagged by MAME, a call here (the module says why)
    ("dbra    D0, $100", "m68000", "branch"),
    ("st      D0", "m68000", "sequential"),
    # THE V30'S 8080 MODE, whose conditional calls and returns are MAME's STEP_OVER and STEP_OUT.
    ("cnz  $1234", "v30", "call"),
    ("rnz", "v30", "return"),
    ("pchl", "v30", "branch"),
    ("retem", "v30", "return"),
])
def test_the_class_is_read_off_the_mnemonic(text: str, cpu_type: str, expected: str) -> None:
    assert flow.classify(text, cpu_type) == expected


def test_a_type_without_a_table_has_no_source_rather_than_the_nearest_family() -> None:
    """A 68010 prints through the same disassembler as a 68000 and executes words a 68000 does
    not; borrowing the 68000's table for it would classify those as `unknown` on a cpu where
    they are real, so a type nobody checked has no table at all."""
    assert flow.source("m68000") == "mnemonic_table:m68000"
    assert flow.source("v30") == "mnemonic_table:v30"
    assert flow.source("m68010") is None and flow.source(None) is None


def test_two_listings_that_disagree_about_the_addresses_classify_nothing() -> None:
    """A class landing on the line next to its own is a wrong answer that looks right, so the
    bare listing has to carry, line for line, the addresses of the listing it classifies."""
    bare, addresses = _pair("dasm.m68k.560")
    assert flow.classify_listing(bare[1:], addresses[1:], "m68000") is not None
    assert flow.classify_listing(bare[1:], addresses[:-1], "m68000") is None, "shifted"
    assert flow.classify_listing(bare[:-1], addresses, "m68000") is None, "one line short"
    assert flow.classify_listing(["not a listing line"], addresses[:1], "m68000") is None
