"""Taps in a cpu's io space: count and capture watches whose write is an `out` to a port.

The console answers a port's handlers with `mapi` (`mapi.v30-6.txt`, a port written through
its handler; `mapi.v30-20-unmapped.txt`, one nothing handles). An io tap is for the session
only, so everything here also holds that the declaration store never sees one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import io_board, refused, use_table  # noqa: E402
from test_tally import _sent, _tallying  # noqa: E402
from test_watches import _WatchSession  # noqa: E402

import mame_arming as arming  # noqa: E402
import mame_capture as capture  # noqa: E402
import mame_cpus as mcpus  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_tally as tally  # noqa: E402
import server as s  # noqa: E402

BLOCK_MAP = {"cpus": [{"tag": ":maincpu", "spaces": ["io", "program"]}],
             "address_map": [{"cpu": ":maincpu", "space": "program", "start": "0x2031f0",
                              "end": "0x2032ff", "share": ":mainram"}]}


def _io_board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
              spaces: tuple[str, ...] = ("io", "program")) -> _WatchSession:
    ses = _tallying(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", dict(BLOCK_MAP))
    io_board(monkeypatch, ses, spaces)
    return ses


def _script() -> str:
    return _sent().decode().splitlines()[-1].replace('\\"', '"')


# ------------------------------------------------------------------ a count watch on a port

def test_a_count_watch_on_a_port_taps_the_io_space_and_asks_the_io_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _io_board(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x6", mode="count", length=2, space="io")
    assert out["status"] == "ok", out
    assert out["space"] == "io" and out["ref"] == "0x6", out
    assert out["write_maps_to"] == "twinsed1_state::twins_pal_w", out
    assert "mapi 0x6" in " ".join(ses.commands) and not any(
        c.startswith("map ") for c in ses.commands), "the port is asked of the io map only"
    assert 'cpu.spaces["io"]' in _script()
    assert out["tally_id"] == "6_2@io", out["tally_id"]


def test_a_port_and_the_same_number_in_ram_are_two_taps(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    ses = _io_board(monkeypatch, tmp_path)
    ses.memory[0x6] = b"\0\0"
    port = s.watch_add(ref="0x6", mode="count", length=2, space="io")
    ram = s.watch_add(ref="0x6", mode="count", length=2)
    assert port["status"] == ram["status"] == "ok", (port, ram)
    assert port["tally_id"] != ram["tally_id"] and port["space"] == "io" and "space" not in ram
    assert len(mstate.STATE.tallies) == 2
    cleared = s.watch_clear(ref="0x6")
    assert [t["tally_id"] for t in cleared["tallies_removed"]] == [ram["tally_id"]], (
        "a program ref clears the RAM tap and leaves the port's")
    assert [o for o, _ in mstate.STATE.tallies.items()] == [("0x6@io", ":maincpu")]


def test_an_io_tap_is_not_stored_and_says_why(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    _io_board(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x6", mode="count", length=2, space="io")
    assert out["stored"] is False and "program address" in out["note"], out
    assert arming.store().declarations() == [], "nothing a server would re-arm as RAM"


def test_an_io_tap_is_listed_surveyed_and_cleared_by_any_spelling_of_its_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    ref = s.watch_add(ref="0x6", mode="count", length=2, space="io")["ref"]
    rows = [w for w in s.watch_list()["watches"] if w["ref"] == ref]
    assert len(rows) == 1 and rows[0]["space"] == "io" and rows[0]["stored"] is False, rows
    assert [w for w in s.watch_list(cpu="maincpu")["watches"] if w["ref"] == ref]
    surveyed = [w for w in s.step()["watches"] if w["ref"] == ref]
    assert len(surveyed) == 1 and surveyed[0]["space"] == "io", "a stop's survey names it"
    cleared = s.watch_clear(ref="0x06", space="io")
    assert cleared["status"] == "ok" and len(cleared["tallies_removed"]) == 1, cleared
    assert "1 tap removed" in cleared["summary"], cleared["summary"]
    assert not mstate.STATE.tallies


def test_clearing_every_watch_takes_the_io_taps_too(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    _io_board(monkeypatch, tmp_path)
    s.watch_add(ref="0x6", mode="count", length=2, space="io")
    assert s.watch_clear(all=True)["tallies_removed"], "the port's tap went with the rest"
    assert not mstate.STATE.tallies


def test_an_io_ref_nothing_holds_is_refused_naming_the_ones_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    s.watch_add(ref="0x6", mode="count", length=2, space="io")
    out = refused("0x6", s.watch_clear(ref="0x8", space="io"))
    assert out["code"] == "unknown_ref" and len(mstate.STATE.tallies) == 1, out
    text = " ".join(out["message"].split())
    named = {f for f in ("breakpoint", "watch", "regpoint") if f"`{f}_list`" in text}
    assert named == {"watch"} and text.endswith(f"Matching: {dec.REF_MATCH['watch']}."), text


def test_the_watch_rule_states_the_io_spellings_a_clear_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The io clause is what `held_key` does: with `space="io"`, a port or a captured block in
    any `0x` spelling, or a block's symbol in any case."""
    assert 'with `space="io"`, an io tap\'s port as an address or its block as a symbol' in (
        dec.REF_MATCH["watch"])
    _io_board(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"PALBUF": 0x2031FC}, types={"PALBUF": "u16[2]"})
    s.watch_add(ref="0x6", mode="count", length=2, space="io")
    s.watch_add(ref="PalBuf", mode="capture", trigger="0x6", space="io")
    assert s.watch_clear(ref="0x06", space="io")["status"] == "ok", "a port in any spelling"
    assert s.watch_clear(ref="palbuf", space="io")["status"] == "ok", "the block in another case"
    assert not mstate.STATE.tallies
    s.watch_add(ref="0x6", mode="count", length=2, space="io")
    assert refused("'06' matches no io tap in the io space, so nothing was cleared. The io taps "
                   "held in the io space: '0x6'", s.watch_clear(ref="06", space="io"))["code"] == (
        "unknown_ref"), (
        "with no `0x` the ref is a symbol, as the clause says")


def test_one_io_ref_holds_one_tap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A second install under a ref holding another tap would leave the first counting where no
    list or clear reaches it: another length, trigger or kind under a held ref is refused until
    it is cleared, while the same tap declared again, in any spelling, is adopted."""
    _io_board(monkeypatch, tmp_path)
    assert s.watch_add(ref="0x6", mode="count", length=2, space="io")["status"] == "ok"
    assert s.watch_add(ref="0x06", mode="count", length=2, space="io")["status"] == "ok"
    refused("0x6 in the io space already holds the tap 6_2@io",
            s.watch_add(ref="0x6", mode="count", length=1, space="io"))
    refused("0x6 in the io space already holds the tap 6_2@io",
            s.watch_add(ref="0x6", mode="capture", length=4, trigger="0x6", space="io"))
    assert list(mstate.STATE.tallies) == [("0x6@io", ":maincpu")]
    assert _sent().count(b"install_write_tap") == 2, "the refusals installed nothing"


@pytest.mark.parametrize(("kw", "said"), [
    ({"mode": "change", "length": 2}, "program space"),
    ({"mode": "show", "length": 2}, "program space"),
    ({"ref": "PORT", "mode": "count", "length": 2}, "written `0x`"),
    ({"mode": "count", "length": 2, "by": "symbol"}, "written `0x`"),
    ({"mode": "count", "length": 2, "space": "data"}, "space"),
    ({"ref": "2031fc", "mode": "capture", "length": 4, "trigger": "6", "by": "pointer"},
     "by symbol or by address"),
    ({"ref": "0x2031fc", "mode": "capture", "length": 4}, "needs `trigger`"),
])
def test_what_the_io_space_cannot_take_is_refused_before_the_machine(
    kw: dict[str, Any], said: str,
) -> None:
    out = refused(said, s.watch_add(**{"ref": "0x6", "space": "io", **kw}))
    assert out["code"] == "bad_argument", out


@pytest.mark.parametrize(("spaces", "have"), [(("program",), []),
                                              (("io", "program"), [":maincpu"])])
def test_a_cpu_with_no_io_space_is_refused_naming_the_ones_that_have_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, spaces: tuple[str, ...], have: list[str],
) -> None:
    _io_board(monkeypatch, tmp_path, spaces=spaces)
    mstate.STATE.machine_map["cpus"].append({"tag": ":subcpu", "spaces": ["program"]})
    out = refused("no io space", s.watch_add(ref="0x6", mode="count", length=2, space="io",
                                             cpu="subcpu"))
    assert out["code"] == "bad_argument" and out["cpus_with_io"] == have, out


def test_a_count_on_an_unmapped_port_is_armed_and_says_the_write_goes_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A write tap on a port nothing handles still sees the cpu's `out` there, so the
    count arms, reports the fact as `write_maps_to`, and says what it means."""
    _io_board(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x20", mode="count", length=2, space="io")
    assert out["status"] == "ok" and out["write_maps_to"] == "unmapped", out
    mapped = s.watch_add(ref="0x6", mode="count", length=2, space="io")
    assert "nothing in the machine" not in mapped["note"], "a handled port says nothing of it"
    assert "nothing in the machine handles an `out` at port 0x20" in out["note"], out
    assert "still sees every one the cpu makes" in out["note"] and mstate.STATE.tallies, out


@pytest.mark.parametrize(("space", "bus_bits", "addr", "length"), [
    ("program", 16, 0x2031FD, 2), ("program", 32, 0x2031FE, 4), ("program", 16, 0x2031FD, 6),
    ("io", 16, 0x21, 2), ("io", 32, 0xE2, 4), ("io", 32, 0xE1, 8),
])
def test_every_count_a_split_refusal_suggests_is_accepted_on_an_unmapped_write_side(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, space: str, bus_bits: int, addr: int,
    length: int,
) -> None:
    """A refusal whose remedy is refused is a dead end: every count a bus-word split names is
    declared back, each on a write side nothing handles, and each is accepted."""
    ses = _io_board(monkeypatch, tmp_path)
    monkeypatch.setattr(mcpus, "bus_width", lambda cpu, sp="program": bus_bits)
    io = {"space": "io"} if space == "io" else {}
    out = refused("split a", s.watch_add(ref=f"{addr:#x}", mode="count", length=length, **io))
    text = " ".join(out["message"].split())
    first = re.search(r'watch_add\(ref="(0x[0-9a-f]+)", mode="count", length=(\d+)', text)
    assert first is not None, text
    suggested = [(int(first[1], 16), int(first[2]))] + [
        (int(a, 16), int(n)) for a, n in re.findall(r"(0x[0-9a-f]+) \(length=(\d+)\)", text)]
    assert sum(n for _a, n in suggested) == length, ("the remedy covers the range", text)
    for at, n in suggested:
        if space == "program":
            ses.rom_write_unmapped.add(at)     # every port but 6 and 7 is unmapped already
        got = s.watch_add(ref=f"{at:#x}", mode="count", length=n, **io)
        assert got["status"] == "ok" and got["write_maps_to"] == "unmapped", (at, n, got)


NO_WRITE_SIDE = "   Read: 0020 logical io == 0020 physical io -> unmapped\n"


@pytest.mark.parametrize(("kw", "says"), [
    ({"ref": "0x20", "mode": "count", "length": 2, "space": "io"}, "the console's `mapi"),
    ({"ref": "0x2031fc", "mode": "capture", "length": 4, "trigger": "0x20", "space": "io"},
     "the trigger: the console's `mapi"),
    ({"ref": "0x2031fc", "mode": "count", "length": 4}, "the console's `map"),
    ({"ref": "0x2031fc", "mode": "capture", "length": 4, "trigger": "0x2031f0"},
     "the trigger: the console's `map"),
])
def test_a_tap_whose_write_side_the_console_does_not_name_is_refused_and_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kw: dict[str, Any], says: str,
) -> None:
    """`unmapped` is a write side; NO `Write:` line is not knowing one, and a tap armed on that
    would read as a fact nobody established."""
    ses = _io_board(monkeypatch, tmp_path)
    plain = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: NO_WRITE_SIDE
                        if c.startswith(("map ", "mapi ")) else plain(c, timeout))
    out = refused("named no `Write:` side", s.watch_add(**kw))
    assert out["message"].startswith(says) and _sent() == b"" and not mstate.STATE.tallies, out


# ------------------------------------------------------------------ a capture on a port

def test_a_capture_on_an_unmapped_port_is_armed_and_its_note_says_the_out_goes_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install's own note and the trigger's: the second is appended, never put in place
    of the first."""
    _io_board(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fc", mode="capture", length=4, trigger="0x20", space="io")
    assert out["status"] == "ok" and out["trigger_maps_to"] == "unmapped", out
    assert out["note"].startswith("the tap is installed"), "the install's note kept"
    assert "; the trigger: nothing in the machine handles an `out` at port 0x20" in out["note"]
    mapped = s.watch_add(ref="0x203200", mode="capture", length=4, trigger="0x6", space="io")
    assert mapped["status"] == "ok" and "nothing in the machine" not in mapped["note"], mapped


def test_a_capture_triggered_by_a_port_reads_its_block_in_program_space(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _io_board(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fc", mode="capture", length=4, trigger="0x6", space="io")
    assert out["status"] == "ok", out
    assert out["space"] == "io" and out["trigger_maps_to"] == "twinsed1_state::twins_pal_w"
    assert (out["trigger"], out["trigger_addr"]) == ("0x6", "0x00000006"), (
        "the trigger as given and where it resolved, as a program capture's reply has", out)
    assert out["ref"] == "0x2031fc" and out["space"] == "io" and out["stored"] is False, out
    script = _script()
    assert 'local tsp = cpu.spaces["io"]' in script and 'local sp = cpu.spaces["program"]' in script
    assert "tsp:install_write_tap(" in script, "the tap sits on the port"
    assert any(c.startswith("mapi 0x6") for c in ses.commands)
    (owner, rec), = mstate.STATE.tallies.items()
    assert rec["space"] == "io" and owner[0] == "0x2031fc@io"
    listed = [w for w in s.watch_list()["watches"]
              if (w["ref"], w.get("space")) == ("0x2031fc", "io")]
    assert listed and listed[0]["mode"] == "capture", listed
    assert listed[0]["trigger_addr"] == "0x00000006" and "trigger" not in listed[0], listed


def test_a_captured_block_under_two_spellings_is_one_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"PALBUF": 0x2031FC}, types={"PALBUF": "u16[2]"})
    first = s.watch_add(ref="PalBuf", mode="capture", trigger="0x6", space="io")
    assert first["status"] == "ok" and first["ref"] == "PALBUF" and first["space"] == "io", first
    assert first["length"] == 4 and first["fmt"] == "u16[2]", "the table types the block"
    assert s.watch_add(ref="PALBUF", mode="capture", trigger="0x6", space="io")["status"] == "ok"
    refused(re.escape("that tap is already declared under 'PALBUF': one tap is one "
                      "declaration, so `watch_clear(ref='PALBUF', cpu=\":maincpu\", "
                      "space=\"io\")` frees it, or use that ref"),
            s.watch_add(ref="0x2031fc", mode="capture", length=4, trigger="0x6", space="io"))
    assert len(mstate.STATE.tallies) == 1


def test_a_port_triggered_capture_is_never_a_manifest_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest's fire word is a program address: a capture whose trigger is port 6 must not
    answer a command firing at RAM 6."""
    monkeypatch.setattr(mstate.STATE, "tallies", {
        ("0x10@io", ":maincpu"): {"trigger": 0x6, "space": "io"},
        ("0x10", ":maincpu"): {"trigger": 0x6},
    })
    assert [o for o, _ in capture.block_captures()] == [("0x10", ":maincpu")]
    assert len(capture.block_captures(space="")) == 2, "every capture, for a reader of blocks"


def test_the_ids_of_a_port_carry_the_space() -> None:
    assert tally.id_for(None, 6, 2, "io") == "6_2@io" and tally.id_for(None, 6, 2) == "6_2"
    assert capture.id_for(None, 0x10, 4, 6, "io").endswith("_t6@io")


# --------------------------------------------- a count on a port, judged by the io bus width

def _io_bus(monkeypatch: pytest.MonkeyPatch, data_width: int | None) -> None:
    """`start`'s inventory with the double's io space `data_width` bits wide (v30-alt's V30
    declares 16), or with no io space row at all."""
    rows = [] if data_width is None else [
        {"cpu": ":maincpu", "space": "io", "data_width_bits": data_width, "endianness": "little",
         "entries": 18, "address_mask": "0x0000ffff"}]
    monkeypatch.setattr(mstate.STATE, "machine_map", {**mstate.STATE.machine_map,
                                                      "spaces": rows})


def test_a_count_on_an_odd_port_of_a_16_bit_io_bus_is_refused_with_nothing_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """On v30-alt a V30 `out dx, ax` at an odd port reaches a tap as two bus-word fragments, each
    under its lane mask, as a program write does, so a two-byte count at an odd port would hold
    two `partial` rows and no value. It is refused as the program space's split is,
    naming the counts that work, each in the io space."""
    _io_board(monkeypatch, tmp_path)
    _io_bus(monkeypatch, 16)
    out = s.watch_add(ref="0x7", mode="count", length=2, space="io")
    refused(r"split a 16-bit bus word", out)
    assert out["code"] == "bad_argument", out
    assert 'watch_add(ref="0x7", mode="count", length=1, space="io")' in out["message"], out
    assert b"install_write_tap" not in _sent()
    assert not mstate.STATE.tallies


@pytest.mark.parametrize(("port", "length", "data_width"), [
    (0x6, 2, 16), (0x7, 1, 16), (0x7, 2, 8)])
def test_a_count_inside_an_io_bus_word_or_of_whole_ones_is_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int, length: int, data_width: int,
) -> None:
    _io_board(monkeypatch, tmp_path)
    _io_bus(monkeypatch, data_width)
    out = s.watch_add(ref=f"{port:#x}", mode="count", length=length, space="io")
    assert out["status"] == "ok", out
    assert "bus word" not in out["note"], out["note"]


def test_a_count_on_a_port_with_no_io_space_row_is_installed_and_says_unchecked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    _io_bus(monkeypatch, None)
    out = s.watch_add(ref="0x7", mode="count", length=2, space="io")
    assert out["status"] == "ok", out
    assert "; " + tally.bus_unchecked_note("io") + "; " in out["note"], out["note"]


def test_an_io_tap_lists_its_stamp_and_age_from_the_declarations_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every listed declaration carries `created_at` and `age_s`; an io tap is a session record
    and not a stored row, and its row carries the same two keys from the same clock."""
    from datetime import UTC, datetime, timedelta
    _io_board(monkeypatch, tmp_path)
    then = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(mstate, "utc_now", lambda: then)
    assert s.watch_add(ref="0x6", mode="count", length=2, space="io")["status"] == "ok"
    monkeypatch.setattr(mstate, "utc_now", lambda: then + timedelta(seconds=90))
    (row,) = [w for w in s.watch_list()["watches"] if w["ref"] == "0x6" and w.get("space") == "io"]
    assert (row["created_at"], row["age_s"]) == ("2026-10-04T12:00:00+00:00", 90), row


def test_a_cpu_s_two_spaces_answer_each_its_own_bus_width(monkeypatch: pytest.MonkeyPatch) -> None:
    import mame_cpus as cpus
    monkeypatch.setattr(mstate.STATE, "machine_map", {"spaces": [
        {"cpu": ":maincpu", "space": "program", "data_width_bits": 8},
        {"cpu": ":maincpu", "space": "io", "data_width_bits": 16}]})
    assert (cpus.bus_width(":maincpu"), cpus.bus_width(":maincpu", "io")) == (8, 16)


@pytest.mark.parametrize(("port", "length", "splits"), [(0x4, 4, False), (0x6, 2, False),
                                                         (0x7, 2, True), (0x6, 4, True)])
def test_a_32_bit_io_bus_is_judged_by_its_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int, length: int, splits: bool,
) -> None:
    """The same arithmetic as the program space's, over an io bus four bytes wide: a range inside
    one word or of whole words is taken, one that covers a word in part is refused."""
    import mame_watches as watches
    _io_board(monkeypatch, tmp_path)
    _io_bus(monkeypatch, 32)
    why, _note = watches.bus_word_split(port, length, ":maincpu", "io")
    assert (why is not None) is splits, why
    if splits:
        assert "split a 32-bit bus word" in str(why) and 'space="io"' in str(why), why


@pytest.mark.parametrize(("program_width", "io_width", "port", "length", "splits"), [
    (8, 32, 0x6, 4, True), (32, 8, 0x7, 2, False)])
def test_a_port_is_judged_by_the_io_bus_and_never_by_the_program_buss_width(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, program_width: int, io_width: int,
    port: int, length: int, splits: bool,
) -> None:
    """A cpu carrying both spaces at different widths: the io row decides, so a range that splits
    an io word is refused where the program bus would take it, and the other way round."""
    _io_board(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", {**mstate.STATE.machine_map, "spaces": [
        {"cpu": ":maincpu", "space": "program", "data_width_bits": program_width},
        {"cpu": ":maincpu", "space": "io", "data_width_bits": io_width}]})
    out = s.watch_add(ref=f"{port:#x}", mode="count", length=length, space="io")
    assert (out["status"] == "INVALID") is splits, out


def test_an_io_tap_on_no_named_cpu_lists_its_cpu_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A tap armed while `cpulist` marked no cpu has no cpu to name: its row says so, as every
    row of a watch does, never a null."""
    _io_board(monkeypatch, tmp_path)
    s.watch_add(ref="0x6", mode="count", length=2, space="io")
    ((_owner, rec),) = mstate.STATE.tallies.items()
    monkeypatch.setattr(mstate.STATE, "tallies", {("0x6@io", None): rec})
    (row,) = [w for w in s.watch_list()["watches"] if w.get("space") == "io"]
    assert row["cpu"]["available"] is False, row
