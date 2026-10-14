"""A project's `gfx.yaml`: the strict YAML subset it is read in, the schema it is judged against,
`gfx_load`, and a format named by the manifest wherever a layout is taken.

The manifest under `tests/fixtures/gfx/manifest-blitter.yaml` is a project's declaration, not a
double of anything MAME prints, so it is written by hand: m68k-dual's blitter command
transcribed from its driver, and circus's char layout transcribed from `circus.cpp`. Every
refusal below is a one-place edit of that file, made with a substitution that must match
exactly once.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import blank_session, refused  # noqa: E402
from test_gfx import _png, _serve  # noqa: E402
from test_lua import _channel  # noqa: E402

import mame_manifest as mm  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_yaml  # noqa: E402
import server as s  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "live"))
from gfx_layouts import CIRCUS_CHAR  # noqa: E402

MANIFEST = Path(__file__).parent / "fixtures" / "gfx" / "manifest-blitter.yaml"


def _edited(tmp_path: Path, old: str, new: str) -> str:
    """The fixture with `old` replaced by `new` exactly once, written to `tmp_path`: a
    substitution that matched nothing would test the untouched file under the edit's name."""
    text, n = re.subn(re.escape(old), lambda _: new, MANIFEST.read_text(), count=1)
    assert n == 1, f"the edit {old!r} matched nothing in the fixture"
    path = tmp_path / "gfx.yaml"
    path.write_text(text)
    return str(path)


# ------------------------------------------------------------------ the YAML subset

def test_the_subset_reads_what_a_manifest_is_written_in() -> None:
    doc = mame_yaml.loads(
        "# a comment\n"
        "a: 'it''s'   # after a quoted scalar\n"
        'b: "x \\"y\\" \\\\ z"\n'
        "c: the game's own # after an apostrophe, which is a letter\n"
        "d:\n- 1\n- 0x10\n- [1, [2, 3], {e: f}]\n- {g: 'h, i', j: \"k: l\"}\n"
        "m:\n  - k: 1\n    o:\n      - p\n      - q: r\n        s: t\n"
        "u: 512*512*8\nv: m68k-dual.cpp:208 do_blit\nw: true\nx: false\n")
    assert doc == {
        "a": "it's", "b": 'x "y" \\ z', "c": "the game's own",
        "d": [1, 16, [1, [2, 3], {"e": "f"}], {"g": "h, i", "j": "k: l"}],
        "m": [{"k": 1, "o": ["p", {"q": "r", "s": "t"}]}],
        "u": "512*512*8", "v": "m68k-dual.cpp:208 do_blit", "w": True, "x": False}


@pytest.mark.parametrize("text, said", [
    # plain scalars another reader would type, each one YAML 1.1 or 1.2 reads as non-string
    ("a: no", r"line 1: 'no' is a plain scalar"),
    ("a: True", r"'True' is a plain scalar"),
    ("a: 012", r"'012' is a plain scalar"),
    ("a: 0o7", r"'0o7' is a plain scalar"),
    ("a: 1e3", r"'1e3' is a plain scalar"),
    ("a: 1_000", r"'1_000' is a plain scalar"),
    ("a: 2026-09-28", r"'2026-09-28' is a plain scalar"),
    ("a: 1:20", r"'1:20' is a plain scalar"),
    ("a: ~", r"'~' is a plain scalar"),
    ("a: b: c", r"'b: c' is a plain scalar"),
    ("a: -x", r"'-x' is a plain scalar"),
    # outside the subset
    ("a: &x 1", r"anchors, aliases, tags and block scalars"),
    ("a: |\n  text", r"anchors, aliases, tags and block scalars"),
    ("a:\n  b: 1\na: 2", r"line 3: the key 'a' is given twice"),
    ("a:\tb", r"line 1: a tab"),
    ("a:", r"a key with no value"),
    ("---\na: 1", r"a document marker"),
    ("a: 'x", r"does not close on its line"),
    ('a: "x\\n"', r"the only escapes read"),
    ("a: [1, 2", r"expected `,` or `\]`"),
    ("a: [1,, 2]", r"an empty item"),
    ("a: {b:x}", r"the colon followed by a space"),
    ("a: [1] x", r"has something after its flow collection"),
    ("  a: 1", r"the document's first line is indented"),
    ("a: 1\n  b: 2", r"is not a key here|a line outside|deeper"),
    ("", r"the document is empty"),
    ("a: 'it's'", r"has a lone quote inside"),
    ('a: "x', r"does not close on its line"),
    ('a: "x"y"', r"has a bare quote inside"),
    ("a b: 1", r"'a b' is not a key here"),
    ("'a': 1", r"keys are plain words here"),
    ("a:b", r"is not `key: value`"),
    ("a:\n  b: 1\n  - c", r"a sequence item where the mapping expected a key"),
    ("- a\n  - b", r"indented deeper than the sequence it is in"),
    ("- a\nb: 1", r"a line outside the document's top level"),
    # a key is typed as a value is: PyYAML reads `on:` as the key true
    ("on: 1", r"the key 'on' is one a YAML reader would read as another type"),
    ("a:\n  null: 1", r"the key 'null' is one a YAML reader would read as another type"),
])
def test_the_subset_refuses_what_it_might_misread(text: str, said: str) -> None:
    with pytest.raises(mame_yaml.YamlError, match=said) as err:
        mame_yaml.loads(text)
    if "is empty" not in str(err.value):
        assert re.match(r"line \d+: ", str(err.value)), "every refusal names its line"


@pytest.mark.parametrize(("text", "said"), [
    ("a: {b: 1, b: 1}", r"^line 1: the key 'b' is given twice"),
    ("a: [True]", r"^line 1: 'True' is a plain scalar"),
    ("a:\n  b: 1\n  c: [1, True]", r"^line 3: 'True' is a plain scalar"),
    ('a: "x\\n"', r"^line 1: .*the only escapes"),
    ("a:\nb: 1", r"^line 1: "),
])
def test_a_refusal_inside_a_flow_or_a_quote_names_its_line(text: str, said: str) -> None:
    with pytest.raises(mame_yaml.YamlError, match=said):
        mame_yaml.loads(text)


@pytest.mark.parametrize(("text", "doc"), [
    ("a: 'x # y'\n", {"a": "x # y"}),
    ("- 'x # y'\n", ["x # y"]),
    ("a: 'it''s # not a comment'\n", {"a": "it's # not a comment"}),
    ('a: "x\\\\" # a comment\n', {"a": "x\\"}),
    ('a: "\\\\\\\\x"\n', {"a": "\\\\x"}),
    ("a: [1, 'x, y', 2]\n", {"a": [1, "x, y", 2]}),
    ('a: {b: "x}y", c: 1}\n', {"a": {"b": "x}y", "c": 1}}),
    ("- \n  - a\n", [["a"]]),
    ("-\n  - a\n  - b\n", [["a", "b"]]),
    ("m:\n  - k: 1\n    o: 2\n  - k: 3\n    o: 4\n", {"m": [{"k": 1, "o": 2}, {"k": 3, "o": 4}]}),
])
def test_quotes_dashes_and_nested_items_read_as_any_reader_reads_them(text: str,
                                                                      doc: object) -> None:
    assert mame_yaml.loads(text) == doc


def test_a_key_with_nothing_under_it_is_refused() -> None:
    for text in ("a:\nb: 1\n", "- \n- a\n"):
        with pytest.raises(mame_yaml.YamlError, match="no value"):
            mame_yaml.loads(text)


def test_the_writer_writes_what_its_contract_says() -> None:
    """Block style, a mapping of scalars flat from depth two, lists on one line, strings
    quoted, hex keys in hex through their lists, a top-level mapping after a blank line."""
    doc = {"s": 1, "a": {"b": {"x": 1}, "c": {"d": {"e": 2, "t": True}}}, "f": [10, 11],
           "g": 0, "q": 'say "hi"'}
    text = mame_yaml.dumps(doc, ["h"], hex_keys=("f", "g"))
    assert text == ('# h\ns: 1\n\na:\n  b:\n    x: 1\n  c:\n    d: {e: 2, t: true}\n'
                    'f: [0xa, 0xb]\ng: 0x0\nq: "say \\"hi\\""\n')
    assert mame_yaml.loads(text) == doc
    assert (mame_yaml._scalar_out(True, False), mame_yaml._scalar_out(False, False)) == (
        "true", "false")
    assert (mame_yaml._scalar_out(5, False), mame_yaml._scalar_out(-1, True)) == ("5", "-1")
    assert (mame_yaml.key(":sub:gfx1"), mame_yaml.key("1abc"), mame_yaml.key(":")) == (
        "sub_gfx1", "_1abc", "_")


def test_escapes_inside_quotes_are_read_as_any_reader_reads_them() -> None:
    assert mame_yaml.loads("a: ['x '' y', \"p \\\" q\"]\nb: 'it''s' # c\n") == {
        "a": ["x ' y", 'p " q'], "b": "it's"}


def test_a_bom_is_the_streams_and_not_the_first_keys() -> None:
    """A UTF-8 BOM, which some editors write and every YAML reader skips, is not part of the
    first key."""
    assert mame_yaml.loads("\ufeffschema: 1\n") == {"schema": 1}


# ------------------------------------------------------------------ the schema

def test_the_fixture_loads_whole_and_says_what_it_holds() -> None:
    man = mm.read(str(MANIFEST))
    out = man.summary()
    assert out["systems"] == ["m68k", "m68k-dual"]
    assert out["formats"] == {"page_512x512x8": "declared", "charlayout": "declared"}
    assert out["assets"] == {"pages": {"format": "page_512x512x8", "tag": "gfx1",
                                       "palette": "palette"}}
    blit = out["commands"]["blit"]
    assert (blit["block"], blit["length"], blit["trigger_addr"], blit["fires_with"]) == (
        "0x00700000", 32, "0x0070001e", "0xffff")
    assert blit["planes"] == ["fg", "bg"] and blit["asset"] == "pages"
    assert blit["roles"] == ["dest_dir_x", "dest_dir_y", "dest_x", "dest_x_end", "dest_y",
                             "dest_y_end", "plane", "reads_source", "source_dir_x",
                             "source_dir_y", "source_tile", "source_x", "source_y"]
    assert blit["flags"] == ["drawing_low_half", "scroll_x",
                                                           "scroll_y", "writes_index_0"]
    assert out["palette_ports"] == {"ramdac": {"palette": "palette", "space": "program",
                                         "protocol": "ramdac", "index_port": "0x00720001",
                                         "data_port": "0x00720003",
                                         "index_flag_mask": {
                                             "available": False,
                                             "why": "only a latch's index word carries a flag"},
                                         "order": "rgb", "component_bits": 8,
                                         "components_bit_reversed": False, "pen_range": [0, 255]}}
    assert out["status_counts"] == {"proved": 1, "declared": 23, "human": 1}
    assert man.formats["charlayout"].layout.name == "charlayout"


def test_a_field_is_composed_from_its_parts_across_words() -> None:
    """A row of m68k-dual's blitter block: every coordinate splits across words, and each part lands
    at its `at`; `add` is applied after (the one-row seam on `source_y`)."""
    cmd = mm.read(str(MANIFEST)).commands["blit"]
    words = [0x2530, 0x003F, 0x0A2E, 0x014D, 0, 0, 0x2700, 0x0047, 0xC0E0, 0x000C,
             0x00FF, 0x0012, 0x00FF, 0x00FF, 0xFFFF, 0x0000]
    got = {n: f.value(words) for n, f in {**cmd.fields, **cmd.flags}.items()}
    assert got["dest_x"] == 0x30 + 256 and got["dest_y"] == 0x2E
    assert got["dest_x_end"] == 0x3F + 256 and got["dest_y_end"] == 0x4D + 256
    assert got["source_x"] == 0x25 + 256 and got["source_y"] == 0x0A + 256 + 1
    assert got["source_tile"] == 9 and got["plane"] == 0 and got["reads_source"] == 1
    assert got["scroll_x"] == 0xFF + 256 and got["scroll_y"] == 0x12 + 256
    assert got["drawing_low_half"] == 1
    assert cmd.fields["dest_dir_x"].holds(words) and not cmd.fields["reads_source"].holds(
        [0] * 16)


@pytest.mark.parametrize("old, new, said", [
    ("schema: 1", "schema: 2", r"this server reads schema 1"),
    ("schema: 1", "schema: true", r"schema is an integer; got True"),
    ("    tag: gfx1\n", "", r"assets\.pages: 'tag' is missing"),
    ("    wrap: true\n", "    wrap: 1\n", r"assets\.pages\.wrap is true or false; got 1"),
    ("assets:\n  pages:", "assets:\n  pages: 3\n  others:", r"assets\.pages is a mapping with"),
    ("        parts:\n          - {word: 6, mask: 0xfc00}\n",
     "        parts: []\n", r"source_tile\.parts is a list of one or more"),

    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 0, mask: 0x00ff, at: 30}", r"up to bit 37 of the value, past the 32"),
    ("        when: 1\n", "        when: 5\n", r"when=5: the `plane` role holds 0\.\.1"),
    ("origin_x: {field: scroll_x}", "origin_x: {field: dest_dir_x}",
     r"origin_x\.field='dest_dir_x' names no field or flag of this command that holds a number"),
    ("    planes:\n      - name: fg\n        when: 0\n", "    planes:\n      - name: fg\n",
     r"`when` is the value of the `plane` role"),
    ("{word: 7, mask: 0x0001}], asserted: 1,", "{word: 7, mask: 0x0001}], asserted: 1, add: 1,",
     r"dest_dir_x\.add: a one-bit role is matched to `asserted`, not added to"),
    ("systems: [m68k, m68k-dual]", "systems: []", r"systems is a list"),
    ("    fire: {word: 15,", "    fires: {word: 15,", r"commands\.blit\.fires: an unknown key"),
    ("        - {word: 7, mask: 0x0040, at: 8}", "        - {word: 7, maks: 0x0040, at: 8}",
     r"commands\.blit\.fields\.dest_x\.parts\[1\]\.maks: an unknown key"),
    ("      dest_dir_x:", "      dest_dir_xx:", r"commands\.blit\.fields\.dest_dir_xx: not a role"),
    ("    status: declared\n    source: circus.cpp charlayout", "    status: guessed\n"
     "    source: circus.cpp charlayout", r"formats\.charlayout\.status='guessed'"),
    ("    source: circus.cpp charlayout\n", "    source: ''\n",
     r"formats\.charlayout\.source is a non-empty string"),
    ("    format: page_512x512x8", "    format: page_1024", r"names no format"),
    ("    asset: pages", "    asset: tiles", r"commands\.blit\.asset='tiles' names no asset"),
    ("{field: scroll_x}", "{field: scrollx}", r"origin_x\.field='scrollx' names no field"),
    ("          - {word: 7, mask: 0x0040, at: 8}", "          - {word: 7, mask: 0x0040}",
     r"places bits of the value another part already holds"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 0, mask: 0x00ff}\n          - {word: 0, mask: 0x0040, at: 8}",
     r"reads a bit of word 0 another part reads"),
    ("{word: 7, mask: 0x0001}], asserted: 1", "{word: 7, mask: 0x10001}], asserted: 1",
     r"mask=65537 is outside 1\.\.65535"),
    ("{word: 7, mask: 0x0001}], asserted: 1", "{word: 7, mask: 0x0003}], asserted: 1",
     r"dest_dir_x is a one-bit role, and its parts hold 2 bits"),
    ("{word: 7, mask: 0x0001}], asserted: 1,", "{word: 7, mask: 0x0001}],",
     r"dest_dir_x: 'asserted' is missing"),
    ("{parts: [{word: 7, mask: 0x0010}], status", "{parts: [{word: 7, mask: 0x0010}], "
     "asserted: 1, status", r"fields\.plane\.asserted: an unknown key"),
    ("      writes_index_0:", "      dest_x:", r"the key 'dest_x' is given twice|a flag may not"),
    ("    flags:\n      writes_index_0:", "    flags:\n      plane:",
     r"flags\.plane: a flag may not take a role's name"),
    ("      dest_y_end:", "      height:", r"one pair and not both"),
    ("        when: 1\n", "        when: 0\n", r"two planes share a `when` or a `name`"),
    ("        when: 1\n", "", r"`when` is the value of the `plane` role"),
    ("        page: drawing_low_half", "        page: half", r"page='half' names no field"),
    ("words: 16, word_bytes: 2", "words: 65, word_bytes: 2", r"is 130 bytes, past the 128"),
    ("words: 16, word_bytes: 2", "words: 16, word_bytes: 3", r"word_bytes=3: one of"),
    ("fire: {word: 15,", "fire: {word: 16,", r"fire\.word=16 is outside 0\.\.15"),
    ("      width: 512\n      height: 512\n      planes: 8",
     "      width: 512\n      height: 512\n      planes: 9",
     r"formats\.page_512x512x8\.layout\.planes=9 is outside"),
    # the RAMDAC: its ports, the order its data port takes, the width of a component
    ("    data_port: 0x720003", "    data_port: 0x720001",
     r"palette_ports\.ramdac: the index port and the data port are one address"),
    ("    order: [r, g, b]", "    order: [r, g, g]",
     r"palette_ports\.ramdac\.order=\['r', 'g', 'g'\]"),
    ("    order: [r, g, b]", "    order: [r, g]", r"each of \['r', 'g', 'b'\] once"),
    ("    order: [r, g, b]", "    order: rgb", r"palette_ports\.ramdac\.order='rgb'"),
    ("    component_bits: 8", "    component_bits: 9", r"component_bits=9 is outside 1\.\.8"),
    ("    component_bits: 8", "    component_bits: 0", r"component_bits=0 is outside 1\.\.8"),
    ("    auto_increment: true", "    auto_increment: 1", r"auto_increment is true or false"),
    ("    auto_increment: true\n", "", r"palette_ports\.ramdac: 'auto_increment' is missing"),
    ("    index_port: 0x720001", "    index_port: 0x720001\n    mask_port: 0x720005",
     r"palette_ports\.ramdac\.mask_port: an unknown key"),
    ("    index_port: 0x720001", "    index_port: 0x720001\n    pen_base: -1",
     r"pen_base=-1 is outside 0\.\."),
    ("palette_ports:\n  ramdac:", "palette_ports:\n  ramdac: 1\n  other:",
     r"palette_ports\.ramdac is a mapping"),
])
def test_a_manifest_is_refused_whole_naming_where(tmp_path: Path, old: str, new: str,
                                                   said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said) as err:
        mm.read(_edited(tmp_path, old, new))
    assert err.value.code == "bad_argument" and "nothing was loaded" in str(err.value)


def test_two_ramdacs_may_not_set_the_same_pens_of_one_palette(tmp_path: Path) -> None:
    """A pen with two logs would have two answers to who set it; the boundary is exact: a second
    RAMDAC from pen 256 shares no pen with the first, from 255 it shares one."""
    entry = MANIFEST.read_text().split("palette_ports:\n", 1)[1]
    second = entry.replace("  ramdac:", "  second:").replace("0x720001", "0x730001").replace(
        "0x720003", "0x730003")
    for base, said in ((256, None), (255, r"palette_ports\.second: its pens 255\.\.510 of palette "
                                          r"'palette' overlap those of palette_ports\.ramdac")):
        path = tmp_path / f"two-{base}.yaml"
        path.write_text(MANIFEST.read_text() + second.replace(
            "    order:", f"    pen_base: {base}\n    order:"))
        if said is None:
            assert sorted(mm.read(str(path)).palette_ports) == ["ramdac", "second"]
        else:
            with pytest.raises(mstate.Invalid, match=said):
                mm.read(str(path))
    other = tmp_path / "other-palette.yaml"
    other.write_text(MANIFEST.read_text() + second.replace("palette: palette", "palette: pal2"))
    assert mm.read(str(other)).palette_ports["second"].pens() == range(0, 256), (
        "another palette's pens are other pens")


# the two packed protocols, as v30-alt's and v30's drivers take their palettes
_LATCH = """  pal:
    palette: palette
    cpu: maincpu
    space: io
    protocol: latch
    data_port: 0x8
    index_port: 0xa
    index_flag_mask: 0x8000
    pen_count: 1024
    order: [r, g, b]
    component_bits: 5
    auto_increment: true
    status: declared
    source: v30-alt paldat_w and paloff_w
"""
_SEQUENCE = """  pal:
    palette: palette
    space: io
    protocol: sequence
    data_port: 0x6
    index_port: 0xe
    pen_count: 256
    components_bit_reversed: true
    order: [r, g, b]
    component_bits: 5
    auto_increment: true
    status: declared
    source: twins.cpp twins_pal_w and porte_paloff0_w
"""


def _with_ramdac(tmp_path: Path, entry: str) -> str:
    """The fixture with its one RAMDAC entry replaced by `entry`, written to `tmp_path`."""
    text = MANIFEST.read_text()
    head, sep, _ = text.partition("palette_ports:\n")
    assert sep and text.rstrip().endswith("ramdac_rgb888_w)"), "the entry is the file's tail"
    path = tmp_path / "gfx.yaml"
    path.write_text(head + sep + entry)
    return str(path)


def test_a_ramdac_entry_defaults_to_the_devices_protocol_in_the_program_space() -> None:
    r = mm.read(str(MANIFEST)).palette_ports["ramdac"]
    assert (r.space, r.protocol, r.pen_count, r.components_bit_reversed, r.index_flag_mask) == (
        "program", "ramdac", 256, False, None)
    assert r.pens() == range(0, 256)


def test_a_latch_and_a_sequence_entry_are_read_with_their_keys(tmp_path: Path) -> None:
    latch = mm.read(_with_ramdac(tmp_path, _LATCH)).palette_ports["pal"]
    assert (latch.space, latch.protocol, latch.data_port, latch.index_port,
            latch.index_flag_mask, latch.pen_count, latch.component_bits) == (
        "io", "latch", 0x8, 0xA, 0x8000, 1024, 5)
    assert latch.pens() == range(0, 1024) and latch.components_bit_reversed is False
    seq = mm.read(_with_ramdac(tmp_path, _SEQUENCE)).palette_ports["pal"]
    assert (seq.protocol, seq.index_port, seq.pen_count, seq.components_bit_reversed) == (
        "sequence", 0xE, 256, True)
    alone = mm.read(_with_ramdac(tmp_path, _LATCH.replace("    index_port: 0xa\n", "")))
    assert alone.palette_ports["pal"].index_port is None, "a latch takes its index on the data port"


def test_the_summary_shows_a_ramdacs_protocol_and_its_pens(tmp_path: Path) -> None:
    out = mm.read(_with_ramdac(tmp_path, _LATCH.replace("    index_port: 0xa\n", ""))).summary()
    assert out["palette_ports"]["pal"] == {
        "palette": "palette", "space": "io", "protocol": "latch",
        "index_port": {"available": False, "why": mm.NO_INDEX_PORT_WHY},
        "data_port": "0x00000008", "index_flag_mask": "0x8000", "order": "rgb", "component_bits": 5,
        "components_bit_reversed": False, "pen_range": [0, 1023]}


@pytest.mark.parametrize("entry, old, new, said", [
    (_LATCH, "    index_flag_mask: 0x8000\n", "",
     r"palette_ports\.pal: a latch needs `index_flag_mask`"),
    (_SEQUENCE, "    pen_count: 256\n", "    pen_count: 256\n    index_flag_mask: 0x8000\n",
     r"palette_ports\.pal\.index_flag_mask: the flag of a latch's index word; protocol 'sequence'"),
    (_LATCH, "index_flag_mask: 0x8000", "index_flag_mask: 0",
     r"palette_ports\.pal\.index_flag_mask=0 is outside 1\.\."),
    (_SEQUENCE, "    index_port: 0xe\n", "",
     r"palette_ports\.pal: protocol 'sequence' needs `index_port`"),
    (_LATCH, "pen_count: 1024", "pen_count: 1000", r"pen_count=1000: a power of two"),
    (_LATCH, "pen_count: 1024", "pen_count: 2048", r"pen_count=2048 is outside 1\.\.1024"),
    (_LATCH, "pen_count: 1024", "pen_count: 0", r"pen_count=0 is outside 1\.\.1024"),
    (_LATCH, "protocol: latch", "protocol: dac", r"palette_ports\.pal\.protocol='dac': one of"),
    (_LATCH, "space: io", "space: data", r"palette_ports\.pal\.space='data': one of"),
    (_LATCH, "    auto_increment: true\n",
     "    auto_increment: true\n    components_bit_reversed: 1\n",
     r"components_bit_reversed is true or false"),
    (_LATCH, "index_port: 0xa", "index_port: 0x8",
     r"palette_ports\.pal: the index port and the data port are one address"),
    (_SEQUENCE, "index_port: 0xe", "index_port: 0x6",
     r"palette_ports\.pal: the index port and the data port are one address"),
    (_LATCH, "index_flag_mask: 0x8000", "index_flag_mask: 0xc001",
     r"index_flag_mask=0xc001 shares bits 0x4001 with the colour's 0x7fff"),
], ids=["latch_without_flag", "flag_off_a_latch", "flag_zero", "sequence_without_index",
        "pen_count_not_power", "pen_count_past_max", "pen_count_zero", "protocol_unknown",
        "space_unknown", "reversed_not_bool", "latch_one_port", "sequence_one_port",
        "flag_in_the_colour"])
def test_a_packed_entry_is_refused_naming_where(tmp_path: Path, entry: str, old: str, new: str,
                                                said: str) -> None:
    assert entry.count(old) == 1, f"the edit {old!r} does not match exactly once"
    with pytest.raises(mstate.Invalid, match=said):
        mm.read(_with_ramdac(tmp_path, entry.replace(old, new)))


@pytest.mark.parametrize("old, new, said", [
    ("    order: [r, g, b]", "    pen_count: 512\n    order: [r, g, b]",
     r"palette_ports\.ramdac\.pen_count=512: a RAMDAC's index is a byte, so it names 256 pens"),
    ("    order: [r, g, b]", "    pen_count: 16\n    order: [r, g, b]",
     r"palette_ports\.ramdac\.pen_count=16: a RAMDAC's index is a byte, so it names 256 pens"),
    ("    order: [r, g, b]", "    components_bit_reversed: true\n    order: [r, g, b]",
     r"palette_ports\.ramdac\.components_bit_reversed: only a packed colour"),
    ("    index_port: 0x720001\n", "",
     r"palette_ports\.ramdac: protocol 'ramdac' needs `index_port`"),
], ids=["pen_count_past_a_byte", "pen_count_below_a_byte", "reversed_on_bytes",
        "no_index_port"])
def test_a_ramdac_entry_keeps_its_byte_index_and_its_two_ports(tmp_path: Path, old: str,
                                                               new: str, said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        mm.read(_edited(tmp_path, old, new))
    whole = mm.read(_edited(tmp_path, "    order: [r, g, b]",
                            "    pen_count: 256\n    order: [r, g, b]"))
    assert whole.palette_ports["ramdac"].pens() == range(0, 256)


def test_a_manifest_needs_a_box_start_and_the_plane_role_needs_planes(tmp_path: Path) -> None:
    text = MANIFEST.read_text()
    no_start = re.subn(r"      dest_x:\n(?:        .*\n)+?        source: the known-answer.*\n",
                       "", text, count=1)
    assert no_start[1] == 1
    path = tmp_path / "a.yaml"
    path.write_text(no_start[0])
    with pytest.raises(mstate.Invalid, match=r"the role 'dest_x' is missing"):
        mm.read(str(path))
    no_planes = re.subn(r"    planes:\n(?:      .*\n|        .*\n)+", "", text, count=1)
    assert no_planes[1] == 1
    path.write_text(no_planes[0])
    with pytest.raises(mstate.Invalid, match=r"the `plane` role picks among `planes`"):
        mm.read(str(path))


@pytest.mark.parametrize(("path", "said"), [("", "path is empty"),
                                            ("gfx.yaml", "ABSOLUTE path")])
def test_a_path_that_is_not_absolute_is_refused_by_its_shape(path: str, said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        mm.check_gfx_load(path)


def test_a_file_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    with pytest.raises(mstate.Invalid, match=r"no such manifest"):
        mm.read("/nonexistent/gfx.yaml")
    with pytest.raises(mstate.Invalid, match=r"no such manifest"):
        mm.read(str(tmp_path))
    locked = tmp_path / "locked.yaml"
    locked.write_text("systems: []\n")
    locked.chmod(0)
    with pytest.raises(mstate.Invalid, match=r"cannot read the manifest"):
        mm.read(str(locked))


def test_a_file_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "gfx.yaml"
    bad.write_bytes(b"schema: 1\nsystems: [\xff]\n")
    with pytest.raises(mstate.Invalid, match=r"is not UTF-8"):
        mm.read(str(bad))


# ------------------------------------------------------------------ gfx_load

def test_gfx_load_holds_the_manifest_for_this_board(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    out = s.gfx_load(path=str(MANIFEST))
    assert out["status"] == "ok", out
    assert (out["loaded"] is True and out["replaced_path"]["available"] is False
            and out["path"] == str(MANIFEST))
    assert out["summary"] == ("gfx_load " + str(MANIFEST) + ": 2 formats, 1 asset, "
                              "1 command, 1 palette port; 1 proved, 23 declared, 1 human")
    assert mstate.STATE.manifest is not None
    again = s.gfx_load(path=str(MANIFEST))
    assert again["replaced_path"] == str(MANIFEST)


def test_the_old_section_name_is_read_as_palette_ports_and_the_reply_names_the_new_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`ramdacs`, the section's name before a latch and a sequence joined the family, still
    loads, entry for entry what the same file under `palette_ports` gives, and `gfx_load` says
    the name to move to; under the new name it says nothing of the kind; a file that spells both
    is refused, since two sections would be two answers to one question."""
    old_text = MANIFEST.read_text().replace("\npalette_ports:\n", "\nramdacs:\n")
    assert "\nramdacs:\n" in old_text, "the case is built: the fixture under the old name"
    old = tmp_path / "old.yaml"
    old.write_text(old_text)
    as_old, as_new = mm.read(str(old)), mm.read(str(MANIFEST))
    assert as_old.palette_ports == as_new.palette_ports and as_old.palette_ports, as_old
    assert (as_old.old_section, as_new.old_section) == ("ramdacs", None)
    _channel(monkeypatch, tmp_path)
    loaded = s.gfx_load(path=str(old))
    assert loaded["status"] == "ok" and "palette_ports" in loaded, loaded
    assert "`ramdacs`" in loaded["note"] and "`palette_ports`" in loaded["note"], loaded
    assert "note" not in s.gfx_load(path=str(MANIFEST)), "the new name carries no note"
    bad = tmp_path / "bad.yaml"
    bad.write_text(old_text.replace("    order: [r, g, b]", "    order: [r, g, g]"))
    refused(r"^.*ramdacs\.ramdac\.order=", s.gfx_load(path=str(bad)))
    both = tmp_path / "both.yaml"
    both.write_text(MANIFEST.read_text() + "ramdacs: {}\n")
    out = refused(r"`palette_ports` and `ramdacs` are one section under two names",
                  s.gfx_load(path=str(both)))
    assert out["code"] == "bad_argument", out


def test_line_ups_fixture_keeps_the_old_name_and_loads(tmp_path: Path) -> None:
    """The one fixture left on `ramdacs` on purpose: a manifest written before the rename loads
    with no edit."""
    path = Path(__file__).parent / "fixtures" / "ramdac" / "v30-palette.yaml"
    assert "\nramdacs:\n" in path.read_text()
    man = mm.read(str(path))
    assert man.old_section == "ramdacs" and list(man.palette_ports), man


def test_a_refused_load_keeps_the_manifest_loaded_before(monkeypatch: pytest.MonkeyPatch,
                                                          tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    out = refused(r"an unknown key", s.gfx_load(path=_edited(tmp_path, "schema: 1",
                                                             "schema: 1\nextra: 1")))
    assert out["still_loaded"] == str(MANIFEST) and mstate.STATE.manifest is not None
    assert mstate.STATE.manifest.path == str(MANIFEST)


def test_a_manifest_for_another_board_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    out = refused(r"describes \['m68k', 'm68k-dual'\], and this session runs 'circus'",
                  s.gfx_load(path=str(MANIFEST)))
    assert out["still_loaded"]["available"] is False and mstate.STATE.manifest is None


def test_gfx_load_with_no_machine_is_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    blank_session(monkeypatch)
    assert s.gfx_load(path=str(MANIFEST))["code"] == "no_session"


def test_a_bad_file_is_refused_before_the_machine_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The file is the caller's to fix whatever the machine: with no session the refusal is still
    about the file, not `no_session`."""
    blank_session(monkeypatch)
    refused(r"ABSOLUTE path", s.gfx_load(path="gfx.yaml"))


# ------------------------------------------------------------------ a format by name

def test_gfx_view_takes_a_format_by_its_name_and_decodes_what_the_layout_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _serve(ses, "gfx-circus", block="circus-gfx1")
    named = s.gfx_view(layout="charlayout", palette="palette", tag="gfx1", scale=1)
    assert named["status"] == "ok", named
    _serve(ses, "gfx-circus", block="circus-gfx1")
    given = s.gfx_view(layout=CIRCUS_CHAR, palette="palette", tag="gfx1", scale=1)
    assert named["layout"] == given["layout"] and named["layout"]["name"] == "charlayout"
    assert _png(named).pixels == _png(given).pixels


def test_gfx_locate_takes_formats_by_name(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=["charlayout"], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    assert out["status"] == "ok", out
    assert out["matches"][0]["layout"] == "charlayout" and out["matches"][0]["tile"] == 0x47


@pytest.mark.parametrize("call, said", [
    (lambda: s.gfx_view(layout="charlayout", palette="none", tag="gfx1"),
     r"no manifest is loaded: `gfx_load`"),
    (lambda: s.gfx_locate(layouts=["charlayout"], patch=[0, 0, 8, 8], tag="gfx1"),
     r"no manifest is loaded: `gfx_load`"),
])
def test_a_named_format_with_no_manifest_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path, call: Any, said: str) -> None:
    _channel(monkeypatch, tmp_path)
    refused(said, call())


def test_a_format_the_manifest_lacks_is_refused_naming_its_formats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    out = refused(r"layout='tiles' names no format", s.gfx_view(layout="tiles", palette="none",
                                                                tag="gfx1"))
    assert out["formats"] == ["charlayout", "page_512x512x8"]


def test_a_command_lookup_names_what_the_manifest_has(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    with pytest.raises(mstate.Invalid, match=r"no manifest is loaded"):
        mm.command("blit")
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    assert mm.command("blit").trigger == 0x70001E
    with pytest.raises(mstate.Invalid,
                       match=r"draw command 'sprite' is not in .*; it has \['blit'\]") as e:
        mm.command("sprite")
    assert e.value.code == "unknown_ref", "a name that resolves to nothing, as every tool says it"
    with pytest.raises(mstate.Invalid, match=r"palette_port='nope' is not in") as e:
        mm.palette_port("nope")
    assert e.value.code == "unknown_ref"
    with pytest.raises(mstate.Invalid, match=r"choose\.layout='nope' names no format of") as e:
        mm.format_layout("nope", "choose.layout")
    assert e.value.code == "unknown_ref", "and it names the argument it came in"


def test_a_one_bit_role_holds_on_the_value_it_declares(tmp_path: Path) -> None:
    """`asserted: 0` means the role holds when the bit is CLEAR: a board whose direction bit is
    set for decreasing walks is declared as such, not inverted by hand."""
    cmd = mm.read(_edited(tmp_path, "{word: 7, mask: 0x0001}], asserted: 1",
                          "{word: 7, mask: 0x0001}], asserted: 0")).commands["blit"]
    walks_up = cmd.fields["dest_dir_x"]
    assert not walks_up.holds([0] * 7 + [0x0001] + [0] * 8)
    assert walks_up.holds([0] * 16)


def test_a_name_is_judged_by_its_shape_before_the_gate_and_resolved_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which formats exist is the loaded manifest's, which is the session's: before the gate a
    name passes on its shape alone (the batch's preflight and the probe ask exactly this), and a
    name that shares another candidate's is still two candidates with one name."""
    import mame_gfx as gfx
    import mame_locate as mlocate
    blank_session(monkeypatch)
    assert gfx.check_gfx_view(layout="page8", palette="none", tag="gfx1") == (None, None)
    assert mlocate.check_gfx_locate(layouts=["page8"], patch=[0, 0, 8, 8], tag="gfx1") == []
    with pytest.raises(mstate.Invalid, match=r"two candidate layouts share a name"):
        mlocate.check_gfx_locate(layouts=["charlayout", CIRCUS_CHAR], patch=[0, 0, 8, 8],
                                 tag="gfx1")
    with pytest.raises(mstate.Invalid, match=r"layout='page 8': a layout object, or the name"):
        gfx.check_gfx_view(layout="page 8", palette="none", tag="gfx1")


def test_a_section_of_the_wrong_shape_is_refused_by_its_shape() -> None:
    """Shapes a hand edit makes that the fixture cannot carry beside its own sections."""
    with pytest.raises(mm.ManifestError, match=r"formats is a mapping of names"):
        mm.parse({"schema": 1, "systems": ["x"], "formats": [1]}, "p", "h")
    with pytest.raises(mm.ManifestError, match=r"p is a list of one or more planes"):
        mm._planes([], "p", {}, set())


def _reversed_plane(tmp_path: Path, fg: int, bg: int) -> str:
    """The fixture with its `plane` role stored reversed (`sign: -1`, so it holds -1..0) and
    the planes picked by `fg` and `bg`."""
    text = MANIFEST.read_text()
    for old, new in (("plane: {parts: [{word: 7, mask: 0x0010}], status",
                      "plane: {parts: [{word: 7, mask: 0x0010}], sign: -1, status"),
                     ("        when: 0\n", f"        when: {fg}\n"),
                     ("        when: 1\n", f"        when: {bg}\n")):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path = tmp_path / "gfx.yaml"
    path.write_text(text)
    return str(path)


def test_a_reversed_plane_role_picks_the_planes_it_can_hold(tmp_path: Path) -> None:
    """A role stored reversed holds `add - (2^width - 1)..add`: the bound a plane's `when` is
    judged by is that range, the sign included."""
    man = mm.read(_reversed_plane(tmp_path, 0, -1))
    assert sorted(p.when for p in man.commands["blit"].planes if p.when is not None) == [-1, 0]
    with pytest.raises(mstate.Invalid, match=r"when=1: the `plane` role holds -1\.\.0"):
        mm.read(_reversed_plane(tmp_path, 0, 1))


def test_a_flow_nested_past_any_manifest_is_refused_as_yaml() -> None:
    with pytest.raises(mame_yaml.YamlError, match="nested"):
        mame_yaml.loads("schema: " + "[" * 5000 + "]" * 5000 + "\n")


# ------------------------------------------------------------------ every refusal names its path

_BLOCK = "block: {address: 0x700000, words: 16, word_bytes: 2,"
_FIRE = "fire: {word: 15, value: 0xffff,"
_ASSET_STATUS = "    status: declared\n    source: m68k-dual.cpp do_blit, the source wraps"
_FLAG = "      writes_index_0: {parts: [{word: 7, mask: 0x0008}],"
_PLANE0 = "      - name: fg\n        when: 0\n        order: 1\n"
_RAMDAC = "    index_port: 0x720001\n"
_SIZE = ("        width: 512\n        height: 512\n        status: declared\n"
         "        source: m68k-dual.cpp flip")
_ORIGIN_Y = "        origin_y: {field: drawing_low_half, scale: -256, add: 256}"
_RAMDAC_PROV = "    status: declared\n    source: m68k-dual.cpp main_map"


@pytest.mark.parametrize("old, new, said", [
    ("    wrap: true\n", "    wrap: true\n    offset: -1\n",
     r"^assets\.pages\.offset=-1 is outside 0\.\.;"),
    ("    wrap: true\n", "    wrap: true\n    pen_base: -1\n",
     r"^assets\.pages\.pen_base=-1 is outside 0\.\.;"),
    ("    format: page_512x512x8", "    format: 5",
     r"^assets\.pages\.format is a non-empty string"),
    ("    tag: gfx1", "    tag: ''", r"^assets\.pages\.tag is a non-empty string"),
    ("    palette: palette\n    wrap", "    palette: 5\n    wrap",
     r"^assets\.pages\.palette is a non-empty"),
    (_ASSET_STATUS, _ASSET_STATUS.replace("declared", "guessed"),
     r"^assets\.pages\.status='guessed'"),
    (_FLAG, "      writes_index_0: {mask: 1,",
     r"^commands\.blit\.flags\.writes_index_0\.mask: an unknown key"),
    ("    flags:\n      writes_index_0:", "    flags: [1]\n    flogs:\n      writes_index_0:",
     r"^commands\.blit\.flogs: an unknown key"),
    ("    asset: pages", "    asset: 5", r"^commands\.blit\.asset is a non-empty string"),
    ("    planes:\n", "    planes: [1]\n    plones:\n", r"^commands\.blit\.plones: an unknown key"),
    (_BLOCK, _BLOCK.replace("address: 0x700000,", "address: 0x700000, bank: 1,"),
     r"^commands\.blit\.block\.bank: an unknown key"),
    (_BLOCK, _BLOCK.replace("0x700000", "-1"),
     r"^commands\.blit\.block\.address=-1 is outside 0\.\.;"),
    (_BLOCK, _BLOCK.replace("word_bytes: 2", "word_bytes: true"),
     r"^commands\.blit\.block\.word_bytes is an integer; got True"),
    (_BLOCK, _BLOCK.replace("words: 16", "words: 0"),
     r"^commands\.blit\.block\.words=0 is outside 1\.\.;"),
    (_FIRE, _FIRE.replace("0xffff", "0x10000"),
     r"^commands\.blit\.fire\.value=65536 is outside 0\.\.65535"),
    (_FIRE, _FIRE.replace("0xffff", "-1"),
     r"^commands\.blit\.fire\.value=-1 is outside 0\.\.65535"),
    (_FIRE, _FIRE + " cpu: 1,", r"^commands\.blit\.fire\.cpu: an unknown key"),
    (_FIRE, "fire: {address: -1, value: 0xffff,",
     r"^commands\.blit\.fire\.address=-1 is outside 0\.\.;"),
    (_BLOCK + " status: declared", _BLOCK + " status: guessed",
     r"^commands\.blit\.block\.status='guessed'"),
    (_FIRE + " status: declared", _FIRE + " status: guessed",
     r"^commands\.blit\.fire\.status='guessed'"),
    ("    fields:\n      dest_x:", "    fields: [1]\n    feelds:\n      dest_x:",
     r"^commands\.blit\.feelds: an unknown key"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 16, mask: 0x00ff}",
     r"^commands\.blit\.fields\.dest_x\.parts\[0\]\.word=16 is outside 0\.\.15;"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: -1, mask: 0x00ff}", r"parts\[0\]\.word=-1 is outside 0\.\.15;"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 0, mask: 0x00ff, at: 32}", r"parts\[0\]\.at=32 is outside 0\.\.31;"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 0, mask: 0x00ff, at: -1}", r"parts\[0\]\.at=-1 is outside 0\.\.31;"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}\n"
     "          - {word: 1, mask: 0x0001}",
     r"^commands\.blit\.fields\.dest_x\.parts\[2\] places bits of the value another part"),
    (_PLANE0, _PLANE0 + "        colour: 1\n",
     r"^commands\.blit\.planes\[0\]\.colour: an unknown key"),
    ("        add: 1\n", "        add: x\n",
     r"^commands\.blit\.fields\.source_y\.add is an integer"),
    ("        add: 1\n", "        add: 1\n        sign: x\n",
     r"^commands\.blit\.fields\.source_y\.sign is an integer"),
    ("        add: 1\n        status: declared", "        add: 1\n        status: guessed",
     r"^commands\.blit\.fields\.source_y\.status='guessed'"),
    ("{word: 7, mask: 0x0001}], asserted: 1", "{word: 7, mask: 0x0001}], asserted: 2",
     r"^commands\.blit\.fields\.dest_dir_x\.asserted=2 is outside 0\.\.1;"),
    ("        order: 1\n", "        order: x\n",
     r"^commands\.blit\.planes\[0\]\.order is an integer"),
    (_PLANE0, "      - name: 5\n        when: 0\n        order: 1\n",
     r"^commands\.blit\.planes\[0\]\.name is a non"),
    ("        page: drawing_low_half", "        page: 5",
     r"^commands\.blit\.planes\[0\]\.page is a non"),
    (_ORIGIN_Y, "        origin_y: {}",
     r"^commands\.blit\.planes\[0\]\.origin_y: 'field' is missing"),
    (_ORIGIN_Y, "        origin_y: {field: 5}",
     r"^commands\.blit\.planes\[0\]\.origin_y\.field is a non-empty"),
    (_ORIGIN_Y,
     "        origin_y: {field: drawing_low_half, scale: x}",
     r"planes\[0\]\.origin_y\.scale is an integer"),
    (_ORIGIN_Y,
     "        origin_y: {field: drawing_low_half, add: x}",
     r"planes\[0\]\.origin_y\.add is an integer"),
    ("        when: 0\n", "        when: x\n", r"^commands\.blit\.planes\[0\]\.when is an integer"),
    (_SIZE, _SIZE.replace("width: 512", "width: 0"),
     r"^commands\.blit\.planes\[0\]\.width=0 is outside 1\.\.65536;"),
    (_SIZE, _SIZE.replace("height: 512", "height: 65537"),
     r"^commands\.blit\.planes\[0\]\.height=65537 is outside 1\.\.65536;"),
    ("        status: declared\n        source: m68k-dual.cpp flip",
     "        status: guessed\n        source: m68k-dual.cpp flip",
     r"^commands\.blit\.planes\[0\]\.status="),
    (_RAMDAC, "    index_port: -1\n", r"^palette_ports\.ramdac\.index_port=-1 is outside 0\.\.;"),
    ("    data_port: 0x720003", "    data_port: -1",
     r"^palette_ports\.ramdac\.data_port=-1 is outside 0\.\.;"),
    ("    palette: palette\n    index_port", "    palette: 5\n    index_port",
     r"^palette_ports\.ramdac\.palette is a non"),
    (_RAMDAC, _RAMDAC + "    cpu: 5\n", r"^palette_ports\.ramdac\.cpu is a non-empty string"),
    (_RAMDAC_PROV, _RAMDAC_PROV.replace("declared", "guessed"),
     r"^palette_ports\.ramdac\.status='guessed'"),
    ("palette_ports:\n  ramdac:", "palette_ports: [1]\nramdocs:\n  ramdac:",
     r"^gfx\.yaml\.ramdocs: an unknown key"),
    ("systems: [m68k, m68k-dual]", "systems: [1]", r"^systems\[0\] is a non-empty string"),
    ("assets:\n  pages:", "assets: [1]\nassots:\n  pages:", r"^gfx\.yaml\.assots: an unknown key"),
    ("formats:\n  page_512x512x8:", "formats:\n  page_512x512x8:\n    shape: 1",
     r"^formats\.page_512x512x8\.shape: an unknown"),
])
def test_every_refusal_names_the_path_of_what_it_refuses(tmp_path: Path, old: str, new: str,
                                                         said: str) -> None:
    with pytest.raises(mstate.Invalid) as err:
        mm.read(_edited(tmp_path, old, new))
    reason = str(err.value).split(": ", 1)[1] if str(err.value).startswith("/") else str(err.value)
    assert re.search(said, reason, re.M), reason


# ------------------------------------------------------------------ what each bound lets through

@pytest.mark.parametrize("old, new", [
    ("    wrap: true\n", "    wrap: true\n    offset: 7\n    pen_base: 9\n"),
    (_BLOCK, _BLOCK.replace("words: 16", "words: 64")),              # 128 bytes, the cap exactly
    (_FIRE, _FIRE.replace("0xffff", "0")),
    (_FIRE, "fire: {address: 0x70001e, value: 0xffff,"),
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 0, mask: 0x00ff, at: 24}"),                 # bits 24..31, the last ones
    ("          - {word: 0, mask: 0x00ff}\n          - {word: 7, mask: 0x0040, at: 8}",
     "          - {word: 15, mask: 0x000f}\n          - {word: 15, mask: 0x00f0, at: 4}"),
    (_SIZE, _SIZE.replace("width: 512", "width: 1").replace("height: 512", "height: 65536")),
    ("        order: 1\n", ""),
    (_RAMDAC, "    index_port: 0\n"),
    ("    wrap: true\n", ""),
])
def test_what_each_bound_lets_through_loads(tmp_path: Path, old: str, new: str) -> None:
    man = mm.read(_edited(tmp_path, old, new))
    cmd, asset = man.commands["blit"], man.assets["pages"]
    if "offset: 7" in new:
        assert (asset.offset, asset.pen_base) == (7, 9)
    if new == "":
        assert asset.wrap is False or cmd.planes[0].order == 0
    if "address: 0x70001e" in new:
        assert (cmd.trigger, cmd.fire_value) == (0x70001E, 0xFFFF)
    if "value: 0," in new:
        assert cmd.fire_value == 0


def test_a_read_manifest_carries_its_files_hash() -> None:
    import hashlib
    assert mm.read(str(MANIFEST)).sha256 == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()


def test_the_box_needs_one_whole_pair(tmp_path: Path) -> None:
    """dest_x_end alone, with no dest_y_end and no size, is half a pair: refused."""
    text = MANIFEST.read_text()
    start = text.index("      dest_y_end:\n")
    end = text.index("      dest_dir_x:")
    path = tmp_path / "gfx.yaml"
    path.write_text(text[:start] + text[end:])
    with pytest.raises(mstate.Invalid, match="one pair and not both"):
        mm.read(str(path))


@pytest.mark.parametrize(("parts", "said"), [
    ([{"word": 0, "mask": 0x01}, {"word": 0, "mask": 0x03, "at": 1}], "reads a bit of word 0"),
    ([{"word": 0, "mask": 0x0F}, {"word": 1, "mask": 0x0F, "at": 4},
      {"word": 2, "mask": 0x0F, "at": 2}], "places bits of the value another part"),
    ([{"word": 0, "mask": 0x0F}, {"word": 1, "mask": 0x0F, "at": 4},
      {"word": 0, "mask": 0x08, "at": 8}], "reads a bit of word 0"),
])
def test_a_fields_parts_are_judged_against_every_part_before_them(parts: list[Any],
                                                                  said: str) -> None:
    raw = {"parts": parts, "status": "declared", "source": "s"}
    with pytest.raises(mm.ManifestError, match=said):
        mm._field("x", raw, "p", 16, 16, False)


def test_a_const_size_is_bounded_and_needs_no_parts() -> None:
    def const(v: Any, status: str = "declared") -> Any:
        return mm._field("width", {"const": v, "status": status, "source": "s"}, "p", 16, 16, True)
    assert (const(1).add, const(1 << 16).add) == (1, 1 << 16)
    for bad, said in ((0, r"^p\.const=0 is outside 1\.\.65536$"),
                      (65537, r"^p\.const=65537 is outside 1\.\.65536$")):
        with pytest.raises(mm.ManifestError, match=said):
            const(bad)
    with pytest.raises(mm.ManifestError, match=r"^p\.status='guessed'"):
        const(4, "guessed")
    with pytest.raises(mm.ManifestError, match=r"a size the hardware fixes is a `const`"):
        mm._field("width", {"status": "declared", "source": "s"}, "p", 16, 16, True)
    with pytest.raises(mm.ManifestError) as err:
        mm._field("dest_x", {"status": "declared", "source": "s"}, "p", 16, 16, True)
    assert "const" not in str(err.value)


def test_a_plane_with_when_on_a_command_with_no_plane_role_says_so(tmp_path: Path) -> None:
    text = MANIFEST.read_text()
    text = text.replace("      plane: {parts: [{word: 7, mask: 0x0010}], status: declared, "
                        "source: m68k-dual.cpp do_blit}\n", "")
    start = text.index("      - name: bg\n")
    end = text.index("\npalette_ports:")
    path = tmp_path / "gfx.yaml"
    path.write_text(text[:start].rstrip("\n") + "\n" + text[end:])
    with pytest.raises(mstate.Invalid, match=r"planes\[0\]: `when` picks a plane by the `plane` "
                                             r"role, which this command does not declare"):
        mm.read(str(path))


def test_a_one_bit_roles_name_is_a_plain_flag_when_no_field_takes_it(tmp_path: Path) -> None:
    """A flag named like a one-bit role is a flag, read as bits: no `asserted` asked of it."""
    text = MANIFEST.read_text()
    field = ("      reads_source: {parts: [{word: 7, mask: 0x0004}], asserted: 1, status: human, "
             "source: the family's register notes}\n")
    assert text.count(field) == 1 and text.count(_FLAG) == 1
    flag = "      reads_source: {parts: [{word: 7, mask: 0x0008}],"
    text = text.replace(field, "").replace(_FLAG, flag)
    path = tmp_path / "gfx.yaml"
    path.write_text(text)
    assert mm.read(str(path)).commands["blit"].flags["reads_source"].asserted is None


def test_every_refusal_about_a_manifest_says_which_one_is_still_loaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With a manifest held, a refusal of another one names the one still in force: a path of the
    wrong shape, a file that cannot be read, a file that is not UTF-8, another board's manifest."""
    _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    held = str(MANIFEST)
    with pytest.raises(mstate.Invalid) as err:
        mm.check_gfx_load("relative.yaml")
    assert err.value.fields["still_loaded"] == held
    for path in ("/nonexistent/gfx.yaml",):
        with pytest.raises(mstate.Invalid) as err:
            mm.read(path)
        assert err.value.fields["still_loaded"] == held
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"schema: 1\nsystems: [\xff]\n")
    with pytest.raises(mstate.Invalid) as err:
        mm.read(str(bad))
    assert err.value.fields["still_loaded"] == held
    other = tmp_path / "circus.yaml"
    text = MANIFEST.read_text()
    other.write_text(text.replace("systems: [m68k, m68k-dual]", "systems: [circus]"))
    out = refused("describes", s.gfx_load(path=str(other)))
    assert (out["systems"], out["system"], out["still_loaded"]) == (["circus"], "m68k", held)


def test_a_command_the_manifest_lacks_is_refused_with_the_ones_it_has(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    with pytest.raises(mstate.Invalid) as err:
        mm.command("sprite")
    assert err.value.fields["commands"] == ["blit"]


def test_a_manifests_own_format_wins_over_a_sweep_id_of_the_same_spelling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A format a project named `s1c3` is the project's: the name resolves to it, not to a
    sweep candidate this session never drew."""
    _channel(monkeypatch, tmp_path)
    path = _edited(tmp_path, "  charlayout:\n", "  s1c3:\n")
    assert s.gfx_load(path=path)["status"] == "ok"
    lay = mm.named_layout("s1c3")
    assert (lay.width.const, lay.height.const, lay.planes.const) == (8, 8, 1)


def test_a_malformed_candidate_is_refused_naming_its_place() -> None:
    import mame_locate as mlocate
    with pytest.raises(mstate.Invalid, match=r"layouts\[1\]"):
        mlocate.candidates([CIRCUS_CHAR, {"width": 8}], resolve=False)


@pytest.mark.parametrize("where", [("commands", "blit", "flags"), ("commands", "blit", "fields"),
                                   ("palette_ports",), ("assets",), ("commands",)])
def test_a_section_of_names_that_is_no_mapping_is_refused_by_its_path(
    where: tuple[str, ...],
) -> None:
    doc = mame_yaml.loads(MANIFEST.read_text())
    at = doc
    for k in where[:-1]:
        at = at[k]
    at[where[-1]] = [1]
    with pytest.raises(mm.ManifestError, match="^" + re.escape(".".join(where))
                       + " is a mapping of names$"):
        mm.parse(doc, "gfx.yaml", "")


def test_an_asset_with_no_pen_base_starts_at_pen_zero() -> None:
    assert mm.read(str(MANIFEST)).assets["pages"].pen_base == 0


# ------------------------------------------------------------------ the YAML subset, at its edges

@pytest.mark.parametrize(("text", "doc"), [
    ("a: x 'y # z'\n", {"a": "x 'y"}),
    ('a: ""\n', {"a": ""}),
    ("a: 'x''' # c\n", {"a": "x'"}),
    ('a: "\\" # not a comment"\n', {"a": '" # not a comment'}),
    ('a: "x # y"\n', {"a": "x # y"}),
    ("a: x #y\n", {"a": "x"}),
    ("a: x# y\n", {"a": "x# y"}),
    ("a:\n  b: 1 # c\n", {"a": {"b": 1}}),
    ("a:\n-\n  - b\n", {"a": [["b"]]}),
    ('a: ["\\\\", 1]\n', {"a": ["\\", 1]}),
    ("a: ['x''', 1]\n", {"a": ["x'", 1]}),
    ("a: [Xy, 1]\n", {"a": ["Xy", 1]}),
    ("a: ['', 1]\n", {"a": ["", 1]}),
    ("a: {Xb: 1}\n", {"a": {"Xb": 1}}),
    ("a: [{}, 1]\n", {"a": [{}, 1]}),
    ("a: [[], 1]\n", {"a": [[], 1]}),
])
def test_the_subsets_edges_read_as_any_reader_reads_them(text: str, doc: object) -> None:
    assert mame_yaml.loads(text) == doc


@pytest.mark.parametrize(("text", "said"), [
    ("a: ['x]\n", r"^line 1: \"'x]\" is a single-quoted string that does not close"),
    ("a: [1,\n", r"^line 1: an empty item in a flow collection$"),
    ("- \n- a\n", r"^line 1: a key with no value"),
    ('a: "x\\n"\n', r"^line 1: '\"x\\\\n\"': the only escapes read are"),
])
def test_a_refusal_at_the_subsets_edges_names_its_line_and_its_text(text: str,
                                                                    said: str) -> None:
    with pytest.raises(mame_yaml.YamlError, match=said):
        mame_yaml.loads(text)


def test_a_mapping_nested_past_the_flat_depth_is_written_in_blocks() -> None:
    doc = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    text = mame_yaml.dumps(doc, [])
    assert text == "\na:\n  b:\n    c:\n      d: {e: 1}\n", text
    assert mame_yaml.loads(text) == doc
