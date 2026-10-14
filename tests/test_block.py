"""`read_block`: a memory SHARE or REGION read by MAME's tag, or by the address whose map
entry names it, through the Lua console, altering nothing.

The console double answers what the real one was measured printing (a 68000 board: the
blitter's write-only block as a share of 32 bytes, keyed `:blitram`; a ROM region keyed
`:maincpu`), and each refusal the script can print is exercised by its own line, because
the parser has one branch per prefix and a branch no test reaches is one that can rot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import refused, use_table  # noqa: E402
from test_lua import _channel  # noqa: E402

import mame_block as block  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

_LINE = (b"MAME_MCP_BLOCK kind=share tag=:blitram size=32 bytewidth=2 endian=big start=- "
         b"offset=4 hex=00120034\n")


def test_a_share_is_read_by_its_tag_through_one_step_and_alters_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: _LINE + ses.sentinel(1)}
    out = s.read_block(tag="blitram", offset=4, length=4)
    assert out["status"] == "ok", out
    assert out["kind"] == "share" and out["tag"] == ":blitram" and out["size"] == 32
    assert out["bytewidth"] == 2 and out["endianness"] == "big"
    assert out["offset"] == 4 and out["length"] == 4 and out["hex"] == "00120034"
    assert "addr" not in out and "start" not in out, "no address was asked"
    assert out["evaluated_by"] == "one step" and ses.stepped == 1
    assert out["session"]["altered"] is False and "read_only_claims" not in out["session"]
    assert out["call"] == "MAME_MCP_LUA_END#1" and out["pc"] == "0x00000404"
    assert out["lines_ahead"] == 0 and isinstance(out["reader_steps"], int), out
    assert out["resent"] == 0, "the console's own mishaps are always looked at"
    assert mstate.STATE.last_stop["how"] == "read_block: one step", "the stop is recorded"
    assert out["summary"] == "read_block share :blitram: 4 bytes at offset 0x4 of 0x20: 00120034"
    # The chunk travels inside `load("...")`, so the script's own quotes arrive escaped.
    sent = ses.stdin.getvalue().decode()
    assert 'block(\\"blitram\\")' in sent and "local addr = nil" in sent
    assert "read_u8(i)" in sent and "local length = 4" in sent and "local offset = 4" in sent


def test_a_block_is_found_from_an_address_through_the_map_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"BLIT": 0x00700000})
    ses.answers = {1: (b"MAME_MCP_BLOCK kind=share tag=:blitram size=32 bytewidth=2 endian=big "
                       b"start=700000 offset=8 hex=abcd\n") + ses.sentinel(1)}
    out = s.read_block(ref="0x700008", length=2)
    assert out["status"] == "ok", out
    assert out["addr"] == "0x00700008" and out["start"] == "0x00700000" and out["offset"] == 8
    assert out["hex"] == "abcd" and out["tag"] == ":blitram"
    assert out["summary"] == ("read_block 0x700008 in share :blitram: 2 bytes at offset 0x8 "
                              "of 0x20: abcd")
    sent = ses.stdin.getvalue().decode()
    assert f"local addr = {0x00700008}" in sent
    assert "visible_cpu" in sent, "the map walked is the debugger's own cpu's"
    # BY SYMBOL: the ref is resolved against the table before the script is composed.
    ses.answers[2] = (b"MAME_MCP_BLOCK kind=share tag=:blitram size=32 bytewidth=2 endian=big "
                      b"start=700000 offset=0 hex=0000\n") + ses.sentinel(2)
    out = s.read_block(ref="blit", length=2)
    assert out["status"] == "ok" and out["addr"] == "0x00700000", out
    assert f"local addr = {0x00700000}" in ses.stdin.getvalue().decode()


def test_the_arguments_are_judged_before_the_machine() -> None:
    """One block per call, an offset only with a tag, a length the reply can hold, a bound:
    every one a verdict about the call, given with no machine."""
    refused("not both, not neither", s.read_block())
    refused("not both, not neither", s.read_block(tag="a", ref="0x0"))
    refused("`offset` goes with `tag`", s.read_block(ref="0x0", offset=4))
    refused("not a byte offset", s.read_block(tag="a", offset=-1))
    refused("an integer or a `0x` hex string", s.read_block(tag="a", offset=True))
    # A tag with a space would reach the script's own print line and come back as the wrong
    # refusal (`unexpected_answer`, the instrument's) instead of `unknown_ref`, the caller's.
    refused("one word with no whitespace", s.read_block(tag="blitram "))
    refused("one word with no whitespace", s.read_block(tag="no such block"))
    refused("outside 1..1024", s.read_block(tag="a", length=0))
    refused("outside 1..1024", s.read_block(tag="a", length=1025))
    refused("not a bound", s.read_block(tag="a", seconds=0))
    refused("carries a segment", s.read_block(ref="1000:0"))
    for reply in (s.read_block(), s.read_block(tag="a", length=0)):
        assert reply["code"] == "bad_argument", reply
    # The step's check is the tool's, so a batch refuses the same call in the same words.
    out = s.perform(steps=[{"op": "read_block", "tag": "a", "ref": "0x0"}])
    assert out["status"] == "INVALID" and "not both" in out["message"], out


def test_each_refusal_the_script_prints_is_read_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {
        1: b"MAME_MCP_BLOCK_NONE name=nope tags=:blitram=share,:gfx1=region,:maincpu=region\n"
           + ses.sentinel(1),
        2: b"MAME_MCP_BLOCK_OUTSIDE kind=share tag=:blitram size=32 offset=30 length=4\n"
           + ses.sentinel(2),
        3: b"MAME_MCP_BLOCK_NOENTRY addr=900000\n" + ses.sentinel(3),
        4: b"MAME_MCP_BLOCK_NOBLOCK start=720000 end=720003\n" + ses.sentinel(4),
        5: ses.sentinel(5, ok=False, error="mcp:3: attempt to index a nil value"),
        6: b"something else entirely\n" + ses.sentinel(6),
    }
    out = refused(r"no share or region named 'nope' in this machine; it has .*: `machine_map` "
                  "lists each one", s.read_block(tag="nope"))
    assert out["code"] == "unknown_ref" and out["evaluated_by"] == "one step"
    assert out["tags"] == {":blitram": "share", ":gfx1": "region", ":maincpu": "region"}
    assert ":blitram" in out["message"] and out["session"]["altered"] is False
    out = refused("past the end of share :blitram",
                  s.read_block(tag="blitram", offset=30, length=4))
    assert out["code"] == "bad_argument" and out["size"] == 32 and "zeros" in out["message"]
    assert out["tag"] == ":blitram" and out["kind"] == "share" and out["evaluated_by"]
    assert "offset 0x1e + length 4" in out["message"] and "0x20 bytes long" in out["message"]
    out = refused("inside no entry", s.read_block(ref="0x900000"))
    assert out["code"] == "unknown_ref" and out["addr"] == "0x00900000"
    assert "0x900000 is inside no entry" in out["message"] and out["evaluated_by"]
    out = refused("names no share and no region", s.read_block(ref="0x720001"))
    assert out["code"] == "unknown_ref"
    assert out["map_entry"] == {"start": "0x00720000", "end": "0x00720003"} and "entry" not in out
    assert "count" in out["message"]
    assert "0x720000..0x720003" in out["message"] and out["evaluated_by"]
    out = refused("the console raised in the block chunk", s.read_block(tag="blitram"))
    assert out["code"] == "unexpected_answer" and "nil value" in out["message"]
    assert out["evaluated_by"] == "one step", "a raised script still says what it cost"
    out = refused("no block line", s.read_block(tag="blitram"))
    assert out["code"] == "unexpected_answer"
    assert "something else entirely" in out["message"], "the tail of what the console printed"
    # Every refusal that reached the console says what the evaluation cost, like `lua`'s.
    assert out["evaluated_by"] == "one step" and out["pc_before"] == "0x00000414"
    assert ses.stepped == 6


def test_the_script_is_one_chunk_with_the_shapes_the_parser_knows() -> None:
    """The four prefixes the parser reads are the four the script prints, held by name: a
    branch added to one side and not the other is silent in every other test."""
    for prefix in ("MAME_MCP_BLOCK ", "MAME_MCP_BLOCK_NONE ", "MAME_MCP_BLOCK_OUTSIDE ",
                   "MAME_MCP_BLOCK_NOENTRY ", "MAME_MCP_BLOCK_NOBLOCK "):
        assert prefix in block.BLOCK_LUA, prefix
    filled = block.BLOCK_LUA % {"tag": '"x"', "addr": "nil", "offset": 0, "length": 1,
                                "space": "manager.machine.debugger.visible_cpu"}
    assert "%(" not in filled and "%%" not in filled, "a placeholder or a doubled per cent leaked"
    # Both spellings of a tag are tried, in the order measured: as given, then with the colon.
    assert 'ipairs({name, ":" .. name})' in filled
    # A region entry's own offset counts; a share's does not (a share has none).
    assert "hit.region_offset or 0" in filled
