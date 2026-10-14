"""One composer per refusal sentence the package says in several places: a ref that is neither a
symbol nor an address, a ref that matches no declaration, a second declaration of what one already
holds, a block the machine does not have. Each is pinned once here as the exact sentence; the
callers are pinned by their own tests to go through it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_block as block  # noqa: E402
import mame_clear as mclear  # noqa: E402
import mame_inputs as inputs  # noqa: E402


def test_a_ref_that_is_neither_a_symbol_nor_an_address_names_the_call_that_settles_it() -> None:
    """The lookup named is the one that was made: on a cpu's table, `symbols_find` on that cpu."""
    assert inputs.not_a_ref("the trigger", "fram", ":subcpu") == (
        "the trigger 'fram' is neither a symbol of :subcpu's table nor a `0x` address: "
        '`symbols_find(name=..., cpu=":subcpu")` says whether the table has one')
    assert inputs.not_a_ref("the ref", "x", loaded=3, then=", so nothing was read") == (
        "the ref 'x' is neither a symbol of this build's table (3 symbols loaded) nor a `0x` "
        "address, so nothing was read: `symbols_find(name=...)` says whether the table has one")


@pytest.mark.parametrize(("tool", "cpu", "tail"), [
    ("watch_clear", ":maincpu",
     ', so `watch_clear(ref=\'x\', cpu=":maincpu")` frees it, or use that ref'),
    ("breakpoint_clear", None, ", so `breakpoint_clear(ref='x')` frees it, or use that ref"),
    ("regpoint_clear", ":subcpu",
     ', so `regpoint_clear(ref=\'x\', cpu=":subcpu")` frees it, or use that ref'),
    (None, ":maincpu", ""),
])
def test_a_second_declaration_of_one_place_names_the_clear_on_its_cpu(
    tool: mclear.ClearTool | None, cpu: str | None, tail: str,
) -> None:
    """The clear reaches the holder on its own cpu alone; a report no call answers ends at the
    rule."""
    assert mclear.one_declaration("tally", "x", tool, cpu) == "one tally is one declaration" + tail


def test_a_block_the_machine_lacks_lists_what_it_has() -> None:
    assert block.no_block("gfx2", {"maincpu": 1, "gfx1": 2}) == (
        "no share or region named 'gfx2' in this machine; it has ['gfx1', 'maincpu']: "
        "`machine_map` lists each one")
    assert block.no_block("gfx2", {}).endswith("it has none: `machine_map` lists each one")


def test_a_ref_that_matches_nothing_says_what_is_held_there() -> None:
    assert mclear.nothing_matched("x", "io tap", "", [], "cleared") == (
        "'x' matches no io tap, so nothing was cleared. The io taps held: none at all.")
    assert mclear.nothing_matched("x", "comment", " on :maincpu", ["'a'", "'b'"], "deleted") == (
        "'x' matches no comment on :maincpu, so nothing was deleted. The comments held on "
        ":maincpu: 'a', 'b'.")


def test_a_cpu_a_stub_without_threads_cannot_show_names_the_console_way() -> None:
    """With no thread patch the stub shows no other cpu without running: the refusal names
    `focus`, which shows it through the console and runs the machine."""
    import mame_cpus as cpus
    import mame_state as mstate

    class NoThreads:
        threads: dict[int, str] = {}

    with pytest.raises(mstate.Invalid) as e:
        cpus.make_visible(NoThreads(), ":subcpu", "reading it needs it visible")  # type: ignore[arg-type]
    assert e.value.code == "bad_argument"
    assert str(e.value).endswith("`focus(cpu=\":subcpu\")` makes it visible through the console, "
                                 "which runs the machine and ignores every other cpu until it is "
                                 "observed"), str(e.value)


def test_the_table_a_refusal_names_is_the_one_the_lookup_read() -> None:
    """One table loaded for every cpu is the build's; else the named cpu's, the first cpu's when
    none is named."""
    import mame_state as mstate

    one = mstate.State()
    one.tables = {None: object()}  # type: ignore[dict-item]
    assert one.table_owner(":subcpu") is None
    many = mstate.State()
    many.tables, many.first_cpu = {":maincpu": object()}, ":maincpu"  # type: ignore[dict-item]
    assert (many.table_owner(None), many.table_owner(":subcpu")) == (":maincpu", ":subcpu")

