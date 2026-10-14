"""The `gfx_layout` language `gfx_view` and `gfx_locate` take, and the decoder under it.

The layouts here are TRANSCRIBED from MAME's drivers, character for character where a driver writes
a string: `circus.cpp`'s `charlayout`, `exidy.cpp`'s `spritelayout` (hardhat's), `goldnpkr.cpp`'s
`tilelayout` (witchgme's) and `carpolo.cpp`'s `spritelayout`. What each resolves to is what MAME's
own macros expand to (`digfx.h`), worked by hand from their definitions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_gfx as gfx  # noqa: E402
import mame_layout as ml  # noqa: E402
import mame_region as region  # noqa: E402
import mame_state as mstate  # noqa: E402

CIRCUS_CHARLAYOUT = {"width": 8, "height": 8, "planes": 1, "planeoffset": "{ 0 }",
                     "xoffset": "{ 0, 1, 2, 3, 4, 5, 6, 7 }",
                     "yoffset": "{ 0*8, 1*8, 2*8, 3*8, 4*8, 5*8, 6*8, 7*8 }",
                     "charincrement": "8*8"}
HARDHAT_SPRITELAYOUT = {"width": 16, "height": 16, "planes": 1, "planeoffset": "{ 0 }",
                        "xoffset": "{ STEP8(0,1), STEP8(16*8,1), }",
                        "yoffset": "{ STEP16(0,8) }", "charincrement": "8*32"}
WITCHGME_TILELAYOUT = {"width": 8, "height": 8, "planes": 3,
                       "planeoffset": "{ 0, RGN_FRAC(1,3), RGN_FRAC(2,3) }",
                       "xoffset": "{ 0, 1, 2, 3, 4, 5, 6, 7 }",
                       "yoffset": "{ 0*8, 1*8, 2*8, 3*8, 4*8, 5*8, 6*8, 7*8 }",
                       "charincrement": "8*8"}
CARPOLO_SPRITELAYOUT = {"width": 16, "height": 16, "planes": 1, "planeoffset": "{ 0 }",
                        "xoffset": "{ STEP4(3*0x100*8+4,1), STEP4(2*0x100*8+4,1), "
                                   "STEP4(1*0x100*8+4,1), STEP4(0*0x100*8+4,1) }",
                        "yoffset": "{ STEP16(0,8) }", "charincrement": "16*8"}


def test_a_driver_layout_transcribes_by_copy_and_resolves_as_mame_expands_it() -> None:
    res = ml.resolve(ml.parse_layout(CIRCUS_CHARLAYOUT), 2048 * 8)
    assert res.xoffset == tuple(range(8)) and res.yoffset == tuple(range(0, 64, 8))
    assert res.planeoffset == (0,) and res.charincrement == 64
    hard = ml.resolve(ml.parse_layout(HARDHAT_SPRITELAYOUT), 0x800 * 8)
    assert hard.xoffset == (*range(8), *range(128, 136)), "STEP8 twice, trailing comma and all"
    assert hard.yoffset == tuple(range(0, 128, 8)) and hard.charincrement == 256


def test_rgn_frac_is_a_fraction_of_the_whole_block() -> None:
    """`RGN_FRAC(n,d)` is `n/d` of the block's length in bits, whatever the entry's offset:
    witchgme's gfx2 is 0x3000 bytes, so its planes sit 0x1000 bytes apart."""
    res = ml.resolve(ml.parse_layout(WITCHGME_TILELAYOUT), 0x3000 * 8)
    assert res.planeoffset == (0, 0x1000 * 8, 0x2000 * 8)


def test_arithmetic_and_hex_as_drivers_write_them() -> None:
    res = ml.resolve(ml.parse_layout(CARPOLO_SPRITELAYOUT), 0x400 * 8)
    assert res.xoffset[:4] == (3 * 0x100 * 8 + 4, 3 * 0x100 * 8 + 5, 3 * 0x100 * 8 + 6,
                               3 * 0x100 * 8 + 7)
    assert res.xoffset[-1] == 4 + 3, "the last STEP4 starts at 0*0x100*8+4"
    lay = ml.parse_layout({**CIRCUS_CHARLAYOUT, "planeoffset": ["RGN_FRAC(1,2)+4"],
                            "charincrement": "(2+2)*-(-16)"})
    res = ml.resolve(lay, 1000)
    assert res.planeoffset == (504,) and res.charincrement == 64
    assert ml.parse_layout({**CIRCUS_CHARLAYOUT, "xoffset": list(range(8))}).xoffset[7].const == 7


@pytest.mark.parametrize("change, said", [
    ({"total": 256}, "unknown ['total']"),
    ({"name": "x"}, "unknown ['name']"),
    ({"xoffset": "{ 0, 1 }"}, "xoffset has 2 entries and needs 8"),
    ({"planeoffset": "{ 0, 1 }"}, "planeoffset has 2 entries and needs 1"),
    ({"planes": 9}, "planes=9 is outside"),
    ({"width": 0}, "outside 1.."),
    ({"width": "RGN_FRAC(1,2)"}, "a count, not a fraction"),
    ({"xoffset": "{ STEP3(0,1) }"}, "STEP3 is not one of"),
    ({"xoffset": "{ STEP8(0) }"}, "takes two arguments"),
    ({"yoffset": "{ EXTENDED_YOFFS }"}, "not an expression"),
    ({"charincrement": "8*"}, "not a whole expression"),
    ({"charincrement": "8 8"}, "something after"),
    ({"charincrement": "RGN_FRAC(1,0)"}, "divides by zero"),
    ({"charincrement": "RGN_FRAC(1,2)*RGN_FRAC(1,2)"}, "multiplies two"),
    ({"charincrement": True}, "is not a number"),
    ({"xoffset": 8}, "neither a list"),
])
def test_a_layout_that_is_not_one_is_refused_naming_the_field(change: dict[str, object],
                                                              said: str) -> None:
    with pytest.raises(ml.LayoutError, match=said.replace("[", r"\[").replace("]", r"\]")
                       .replace("(", r"\(").replace(")", r"\)").replace("*", r"\*")):
        ml.parse_layout({**CIRCUS_CHARLAYOUT, **change})


def test_a_missing_field_is_named_and_the_refusal_is_the_contracts() -> None:
    raw = dict(CIRCUS_CHARLAYOUT)
    del raw["yoffset"]
    with pytest.raises(mstate.Invalid, match=r"missing \['yoffset'\]"):
        ml.check_layout(raw)
    assert ml.parse_layout({**CIRCUS_CHARLAYOUT, "name": "chars"}, allow_name=True).name == "chars"


def test_rgn_frac_needs_a_block() -> None:
    with pytest.raises(ValueError, match="needs a block"):
        ml.resolve(ml.parse_layout(WITCHGME_TILELAYOUT), None)
    with pytest.raises(ml.LayoutError, match="resolves below zero"):
        ml.resolve(ml.parse_layout({**CIRCUS_CHARLAYOUT, "planeoffset": ["-1"]}), 64)


def test_the_decoder_reads_plane_zero_as_the_most_significant_bit() -> None:
    """MAME's `gfx_element::decode`: plane 0 sets the pixel's TOP bit, bits are read MSB first.
    Two planes, byte 0 is plane 0 and byte 1 plane 1, one 8x1 row."""
    lay = ml.parse_layout({"width": 8, "height": 1, "planes": 2, "planeoffset": [0, 8],
                            "xoffset": "{ STEP8(0,1) }", "yoffset": [0], "charincrement": 16})
    res = ml.resolve(lay, 32)
    assert ml.decode(res, bytes([0b10000001, 0b11000000]), 0, 0) == [3, 1, 0, 0, 0, 0, 0, 2]
    assert ml.decode(res, bytes([0, 0, 0b01000000, 0]), 0, 1) == [0, 2, 0, 0, 0, 0, 0, 0]
    assert ml.decode(res, bytes([0, 0, 0b01000000, 0]), 2, 0) == [0, 2, 0, 0, 0, 0, 0, 0], (
        "offset is in bytes, before the tile's own increment")


def test_how_many_whole_tiles_a_block_holds() -> None:
    res = ml.resolve(ml.parse_layout(CIRCUS_CHARLAYOUT), 2048 * 8)
    assert ml.available(res, 2048 * 8, 0) == 256
    assert ml.available(res, 2048 * 8, 1) == 255, "a tile whose last byte is past the end"
    assert ml.available(res, 8 * 8, 8) == 0


def test_a_big_endian_word_block_is_put_in_its_own_order() -> None:
    """A 16-bit big-endian region comes out of `region:read` in the host's order; MAME's decoder
    undoes it with an `xormask` of 8, which is swapping each word's bytes."""
    other = "big" if region.HOST_ENDIAN == "little" else "little"
    assert region.logical(b"\x01\x02\x03\x04", 2, other) == b"\x02\x01\x04\x03"
    assert region.logical(b"\x01\x02\x03\x04", 4, other) == b"\x04\x03\x02\x01"
    assert region.logical(b"\x01\x02\x03\x04", 2, region.HOST_ENDIAN) == b"\x01\x02\x03\x04"
    assert region.logical(b"\x01\x02", 1, "big") == b"\x01\x02"
    eight = bytes(range(16))
    assert region.logical(eight, 8, "big" if region.HOST_ENDIAN == "little" else "little") == (
        bytes(range(7, -1, -1)) + bytes(range(15, 7, -1)))
    assert region.logical(b"\x01\x02\x03", 2,
                          "big" if region.HOST_ENDIAN == "little" else "little") \
        == b"\x02\x01\x03", "a block that is not whole words still swaps the words it has"


def test_the_grey_ramp_runs_black_to_white() -> None:
    assert gfx.grey_ramp(1) == [(0, 0, 0), (255, 255, 255)]
    assert gfx.grey_ramp(2) == [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)]


def test_a_tiles_extreme_bits_are_the_sums_of_each_lists_extremes() -> None:
    """`tile_bits` answers without building every pixel's bits: a bit is a plane's offset plus a
    row's plus a column's, chosen independently, so the enumeration and the closed form agree on
    every layout, including ones whose offsets run backwards."""
    import random
    for seed in range(200):
        r = random.Random(seed)
        w, h, p = r.randint(1, 9), r.randint(1, 9), r.randint(1, 4)
        res = ml.Resolved("t", w, h, p, tuple(r.randint(0, 99) for _ in range(p)),
                          tuple(r.randint(0, 99) for _ in range(w)),
                          tuple(r.randint(0, 99) for _ in range(h)), 8)
        spots = [rel for pixel in res.pixel_bits for rel, _ in pixel]
        assert res.tile_bits() == (min(spots), max(spots)), seed


@pytest.mark.parametrize("text", ["-" * 5000 + "64", "(" * 5000 + "64" + ")" * 5000])
def test_an_expression_nested_past_any_layout_is_refused_as_a_layout(text: str) -> None:
    with pytest.raises(ml.LayoutError, match="nested"):
        ml.parse_layout({"width": 8, "height": 8, "planes": 1, "planeoffset": [0],
                         "xoffset": list(range(8)), "yoffset": list(range(0, 64, 8)),
                         "charincrement": text})


@pytest.mark.parametrize(("text", "bits"), [("RGN_FRAC(1,3)*2", 2 * (32768 // 3)),
                                            ("RGN_FRAC(2,3)-RGN_FRAC(1,3)",
                                             65536 // 3 - 32768 // 3),
                                            ("RGN_FRAC(1,3)+RGN_FRAC(1,3)", 2 * (32768 // 3))])
def test_a_fraction_resolves_before_it_is_scaled(text: str, bits: int) -> None:
    """MAME resolves `RGN_FRAC(n,d)` to a whole number of bits first; an expression over it
    scales that number, never the fraction."""
    lay = ml.parse_layout({"width": 8, "height": 8, "planes": 1, "planeoffset": [text],
                           "xoffset": list(range(8)), "yoffset": list(range(0, 64, 8)),
                           "charincrement": 64})
    assert ml.resolve(lay, 32768).planeoffset == (bits,)


# ------------------------------------------------------------------ every refusal names its field

@pytest.mark.parametrize(("field", "value", "said"), [
    ("charincrement", "8*", r"^layout\.charincrement: '8\*' is not a whole expression"),
    ("charincrement", "08", r"^layout\.charincrement: '08' is not an integer"),
    ("charincrement", "", r"^layout\.charincrement: an empty expression$"),
    ("xoffset", ["not an expr!"], r"^layout\.xoffset:"),
    ("xoffset", "{ STEP8(bad!, 1) }", r"^layout\.xoffset:"),
    ("planeoffset", ["RGN_FRAC(08,2)"], r"^layout\.planeoffset:"),
    ("planeoffset", ["RGN_FRAC(1,08)"], r"^layout\.planeoffset:"),
    ("width", [1, 2], r"^layout\.width: \[1, 2\] is neither an integer nor an expression$"),
    ("height", [1, 2], r"^layout\.height:"),
    ("planes", [1, 2], r"^layout\.planes:"),
    ("yoffset", "{ 0, (1 }", r"^layout\.yoffset:"),
    ("charincrement", "(8+8,", r"^layout\.charincrement:"),
    ("charincrement", "(8+8", r"^layout\.charincrement:"),
    ("planeoffset", ["RGN_FRAC(1 2)"], r"^layout\.planeoffset:"),
    ("planeoffset", ["RGN_FRAC 1,2)"], r"^layout\.planeoffset:"),
    ("xoffset", "{ STEP8(0, bad!) }", r"^layout\.xoffset:"),
    ("planeoffset", ["RGN_FRAC-1,2)"], r"^layout\.planeoffset: .*\(expected \( at token 1\)$"),
    ("planeoffset", ["RGN_FRAC(1-2)"], r"^layout\.planeoffset: .*\(expected , at token 3\)$"),
    ("planeoffset", ["RGN_FRAC(1,2*"], r"^layout\.planeoffset: .*\(expected \) at token 5\)$"),
])
def test_every_refusal_names_the_field_it_read(field: str, value: object, said: str) -> None:
    with pytest.raises(ml.LayoutError, match=said):
        ml.parse_layout({**CIRCUS_CHARLAYOUT, field: value})


def test_a_layout_that_is_no_object_is_refused_by_what_it_should_be() -> None:
    with pytest.raises(ml.LayoutError, match=r"^layout is an object with the fields \["):
        ml.parse_layout([1, 2, 3])


@pytest.mark.parametrize("n", [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048])
def test_every_step_macro_mame_defines_expands(n: int) -> None:
    items = ml._items(f"{{ STEP{n}(0,1) }}", "f")
    assert [v.const for v in items] == list(range(n))


def test_a_constant_times_a_fraction_scales_the_fraction() -> None:
    lay = ml.parse_layout({**CIRCUS_CHARLAYOUT, "planeoffset": ["2*RGN_FRAC(1,3)"]})
    assert ml.resolve(lay, 32768).planeoffset == (2 * (32768 // 3),)
    assert ml.Value(0, ((3, 2, 1),)).resolve(0) == 0, "a fraction of no bits is none"


def test_an_open_brace_with_no_close_is_not_a_list() -> None:
    with pytest.raises(ml.LayoutError):
        ml._items("{ 0, 1", "f")


def test_how_many_tiles_a_block_holds_counts_the_last_one_flush_with_its_end() -> None:
    res = ml.resolve(ml.parse_layout(CIRCUS_CHARLAYOUT), None)          # 64 bits a tile
    assert [ml.available(res, bits, 0) for bits in (63, 64, 127, 128)] == [0, 1, 1, 2]
    assert ml.available(res, 136, 1) == 2, "an offset of a byte leaves 128 bits"
    one = ml.resolve(ml.parse_layout({**CIRCUS_CHARLAYOUT, "charincrement": 0}), None)
    assert one.charincrement == 0 and ml.available(one, 64, 0) == 1, "every tile is tile 0"


def test_a_tile_of_one_pixel_and_one_of_the_widest_side_are_layouts() -> None:
    ml.parse_layout({**CIRCUS_CHARLAYOUT, "width": 1, "xoffset": [0]})
    ml.parse_layout({**CIRCUS_CHARLAYOUT, "width": 1024, "xoffset": list(range(1024))})
    ml.parse_layout({**CIRCUS_CHARLAYOUT, "height": 1, "yoffset": [0]})
    ml.parse_layout({**CIRCUS_CHARLAYOUT, "height": 1024,
                     "yoffset": [8 * y for y in range(1024)]})


def test_a_charincrement_below_zero_is_refused_as_such() -> None:
    with pytest.raises(ml.LayoutError, match=r"charincrement resolves below zero$"):
        ml.resolve(ml.parse_layout({**CIRCUS_CHARLAYOUT, "charincrement": "0-1"}), 64)


def test_check_layout_refuses_a_name_unless_asked_and_names_its_place() -> None:
    with pytest.raises(mstate.Invalid, match=r"unknown \['name'\]"):
        ml.check_layout({**CIRCUS_CHARLAYOUT, "name": "x"})
    with pytest.raises(mstate.Invalid, match=r"unknown \['name'\]"):
        ml.check_layout({**CIRCUS_CHARLAYOUT, "name": "x"}, allow_name=False, where="w")
    with pytest.raises(mstate.Invalid, match=r"^custom: 0x8 is outside"):
        ml.check_layout({**CIRCUS_CHARLAYOUT, "width": 0}, where="custom")
