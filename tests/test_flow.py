"""Flow classes off captured listings (`fixtures/console/provenance.txt`), checked by hand."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scry_mame import flow

FIXTURES = Path(__file__).parent / "fixtures" / "console"


def _pair(name: str) -> tuple[list[str], list[str]]:
    lines = [x for x in (FIXTURES / f"{name}.txt").read_text().splitlines() if x.strip()]
    bare = [x for x in (FIXTURES / f"{name}-bare.txt").read_text().splitlines() if x.strip()]
    return bare, [re.match(r"^([0-9A-Fa-f]+):", x).group(1) for x in lines]  # type: ignore[union-attr]


def test_a_68000_listing_names_its_call_its_branch_and_its_return() -> None:
    """Only the branch, the call and the return are marked; the rest is sequential."""
    bare, addresses = _pair("dasm-m68k-560")
    classes = flow.classify_listing(bare, addresses, "m68000")
    assert classes is not None
    marked = {a: c for a, c in zip(addresses, classes, strict=True) if c != flow.SEQUENTIAL}
    assert marked == {"000578": "branch", "00058C": "call", "00059A": "return"}, marked


def test_a_v30_listing_names_every_flow_word_and_reads_past_a_prefix() -> None:
    """Every V30 flow word is classed, and `rep stmw` is the store it repeats."""
    bare, addresses = _pair("dasm-v30-30000")
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
    ("dc.w    $000f; ILLEGAL", "m68000"),
    ("rtd     #$4", "m68000"),
    ("???", "v30"),
    ("brkn    5h", "v30"),
    ("fimul   word ptr [bw]", "v30"),
    ("rep", "v30"),
])
def test_a_word_the_table_does_not_list_is_unknown_never_sequential(text: str,
                                                                     cpu_type: str) -> None:
    assert flow.classify(text, cpu_type) == flow.UNKNOWN


@pytest.mark.parametrize(("text", "cpu_type", "expected"), [
    # the addressing mode never moves the class: the mnemonic alone decides
    ("jsr     (A0)", "m68000", "call"),
    ("jmp     ($4,PC,D0.w)", "m68000", "branch"),
    ("call    far ptr [bw]", "v30", "call"),
    ("br      word ptr [bw]", "v30", "branch"),
    ("move.w  D0, D1", "m68000", "sequential"),
    ("chk.w   D1, D0", "m68000", "call"),
    ("trap    #$0", "m68000", "call"),      # unflagged by MAME, a call here
    ("dbra    D0, $100", "m68000", "branch"),
    ("st      D0", "m68000", "sequential"),
    ("cnz  $1234", "v30", "call"),
    ("rnz", "v30", "return"),
    ("pchl", "v30", "branch"),
    ("retem", "v30", "return"),
])
def test_the_class_is_read_off_the_mnemonic(text: str, cpu_type: str, expected: str) -> None:
    assert flow.classify(text, cpu_type) == expected


def test_a_type_without_a_table_has_no_source_rather_than_the_nearest_family() -> None:
    """A 68010 executes words a 68000 table lacks, so an unchecked type has no table."""
    assert flow.source("m68000") == "mnemonic_table:m68000"
    assert flow.source("v30") == "mnemonic_table:v30"
    assert flow.source("m68010") is None and flow.source(None) is None


def test_two_listings_that_disagree_about_the_addresses_classify_nothing() -> None:
    """A class landing on a neighbouring line looks right, so a misaligned listing yields none."""
    bare, addresses = _pair("dasm-m68k-560")
    assert flow.classify_listing(bare[1:], addresses[1:], "m68000") is not None
    assert flow.classify_listing(bare[1:], addresses[:-1], "m68000") is None, "shifted"
    assert flow.classify_listing(bare[:-1], addresses, "m68000") is None, "one line short"
    assert flow.classify_listing(["not a listing line"], addresses[:1], "m68000") is None
