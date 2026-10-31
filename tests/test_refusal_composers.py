from __future__ import annotations

import pytest

from scry_mame import (
    block,  # noqa: E402
    inputs,  # noqa: E402
)
from scry_mame import clear as mclear  # noqa: E402


def test_a_ref_that_is_neither_a_symbol_nor_an_address_names_the_call_that_settles_it() -> None:
    """The lookup named is the one that was made."""
    assert inputs.not_a_ref("the trigger", "fram", ":subcpu") == (
        "the trigger 'fram' is neither a symbol of :subcpu's table nor a `0x` address: "
        '`symbols_find(name=..., cpu=":subcpu")` says whether the table has one')
    assert inputs.not_a_ref("the ref", "x", loaded=3, then=", so nothing was read") == (
        "the ref 'x' is neither a symbol of this build's table (3 symbols loaded) nor a `0x` "
        "address, so nothing was read: `symbols_find(name=...)` says whether the table has one")


@pytest.mark.parametrize(("kind", "cpu", "tail"), [
    ("watch", ":maincpu",
     ', so `declaration_clear(kind="watch", ref=\'x\', cpu=":maincpu")` frees it, or use that ref'),
    ("breakpoint", None,
     ", so `declaration_clear(kind=\"breakpoint\", ref='x')` frees it, or use that ref"),
    ("regpoint", ":subcpu",
     ', so `declaration_clear(kind="regpoint", ref=\'x\', cpu=":subcpu")` frees it, '
     'or use that ref'),
    (None, ":maincpu", ""),
])
def test_a_second_declaration_of_one_place_names_the_clear_on_its_cpu(
    kind: mclear.ClearKind | None, cpu: str | None, tail: str,
) -> None:
    """The clear names the holder's own cpu; a report no call answers ends at the rule."""
    assert mclear.one_declaration("tally", "x", kind, cpu) == "one tally is one declaration" + tail


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
    """Without a thread patch the refusal names `focus`, the console way."""
    from scry_mame import cpus
    from scry_mame import state as mstate

    class NoThreads:
        threads: dict[int, str] = {}

    with pytest.raises(mstate.Invalid) as e:
        cpus.make_visible(NoThreads(), ":subcpu", "reading it needs it visible")  # type: ignore[arg-type]
    assert e.value.code == "bad_argument"
    assert str(e.value).endswith("`cpu_focus(cpu=\":subcpu\")` makes it visible through the "
                                 "console, which runs the machine and ignores every other cpu "
                                 "until it is observed"), str(e.value)


def test_the_table_a_refusal_names_is_the_one_the_lookup_read() -> None:
    """The build's table when one serves every cpu, else the named or first cpu's."""
    from scry_mame import state as mstate

    one = mstate.State()
    one.tables = {None: object()}  # type: ignore[dict-item]
    assert one.table_owner(":subcpu") is None
    many = mstate.State()
    many.tables, many.first_cpu = {":maincpu": object()}, ":maincpu"  # type: ignore[dict-item]
    assert (many.table_owner(None), many.table_owner(":subcpu")) == (":maincpu", ":subcpu")

