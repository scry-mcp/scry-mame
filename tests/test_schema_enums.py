"""Every closed vocabulary a tool argument is judged against is published as its schema `enum`."""

from __future__ import annotations

import ast
import asyncio
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import test_envelope_seam  # noqa: E402
from scry_core import media_tools, screen_map
from scry_core import pens as scry_pens  # noqa: E402
from scry_core import scan_vocabulary as words
from scry_core import vocabulary as vocab
from scry_core.host_program import absolute as _abs

from scry_mame import (
    advance,  # noqa: E402
    arming,  # noqa: E402
    breakpoints,  # noqa: E402
    folds,  # noqa: E402
    launch,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import files as mfiles  # noqa: E402
from scry_mame import film as mfilm  # noqa: E402
from scry_mame import layout as ml  # noqa: E402
from scry_mame import locate as mlocate  # noqa: E402
from scry_mame import machine as mmachine  # noqa: E402
from scry_mame import scan as mscan  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import space as mspace  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import state as st  # noqa: E402
from scry_mame import sweep as msweep  # noqa: E402

PACKAGE = Path(msweep.__file__).resolve().parent

from scry_core.vocabulary import Words  # noqa: E402

CLOSED: list[tuple[str, str, Callable[[], Words]]] = [
    ("step", "mode", lambda: advance.STEP_MODES),
    ("breakpoint_at", "by", lambda: breakpoints.BREAKPOINT_BY),
    ("breakpoint_at", "role", lambda: dec.ROLES),
    ("watch_add", "mode", lambda: dec.WATCH_MODES),
    ("watch_add", "by", lambda: watches.WATCH_BY),
    ("watch_add", "space", lambda: mspace.SPACES),
    ("declaration_clear", "space", lambda: mspace.SPACES),
    ("declaration_clear", "kind", lambda: folds.KINDS),
    ("declaration_list", "kind", lambda: ("", *folds.KINDS)),
    ("watch_add", "trigger_type", lambda: dec.COUNT_ACCESSES),
    ("scan", "cell_bytes", lambda: mscan.CELL_BYTES),
    ("scan", "operator", lambda: mscan.OPERATORS),
    ("screen_view", "mode", lambda: scry_pens.MODES),
    ("gfx_film", "space", lambda: mspace.SPACES),
    ("gfx_film", "length", lambda: mfilm.LENGTHS),
    ("log", "channel", lambda: mfiles.LOG_CHANNELS),
    ("log_wait", "channel", lambda: mfiles.LOG_CHANNELS),
    ("comment_write", "method", lambda: tuple(folds.COMMENT)),
    ("screen_map_write", "method", lambda: tuple(folds.MAP)),
    ("screen_map_write", "cells", lambda: screen_map.CELLS_WORDS),
    ("scan", "method", lambda: tuple(folds.SCAN)),
    ("state_write", "method", lambda: tuple(folds.STATE_METHODS)),
    ("image_compare", "method", lambda: tuple(media_tools.IMAGE_METHODS)),
    ("audio_compare", "method", lambda: tuple(media_tools.AUDIO_METHODS)),
    ("screen_wait", "palette", lambda: ("", *advance.PALETTES)),
]

#: Depth of the items (a list of lists is 2) and what each item publishes.
ITEMS: list[tuple[str, str, int, Callable[[], dict[str, Any]]]] = [
    ("gfx_locate", "flips", 1, lambda: {"enum": list(mlocate.FLIPS)}),
    ("gfx_sweep", "sizes", 2, lambda: {"enum": list(msweep.SIDES)}),
    ("gfx_sweep", "planes", 1, lambda: {"minimum": 1, "maximum": ml.PLANES_MAX}),
    ("machine_map", "sections", 1, lambda: {"enum": list(mmachine.MAP_SECTIONS)}),
]


def _schemas() -> dict[str, dict[str, Any]]:
    return {t.name: t.input_schema for t in asyncio.run(s.mcp.list_tools())}


def _json_type(words: Words) -> str:
    return "integer" if all(isinstance(w, int) for w in words) else "string"


def _items(prop: dict[str, Any], depth: int) -> dict[str, Any]:
    """The schema of one item `depth` lists down."""
    schema = next(b for b in prop.get("anyOf", [prop]) if b.get("type") == "array")
    for _ in range(depth - 1):
        schema = schema["items"]
    items: dict[str, Any] = schema["items"]
    return items


def _enums(schema: Any) -> bool:
    """Whether an `enum` sits anywhere inside `schema`."""
    if isinstance(schema, dict):
        return "enum" in schema or any(_enums(v) for v in schema.values())
    return isinstance(schema, list) and any(_enums(v) for v in schema)


@pytest.mark.parametrize(("tool", "arg", "judged"), CLOSED, ids=[f"{t}.{a}" for t, a, _ in CLOSED])
def test_a_closed_argument_publishes_its_judges_words_as_its_enum(
    tool: str, arg: str, judged: Callable[[], Words],
) -> None:
    prop = _scalar(_schemas()[tool]["properties"][arg])
    assert prop.get("enum") == list(judged()), prop
    assert prop.get("type") == _json_type(judged()), "the type stays the scalar one_of judges"


@pytest.mark.parametrize(("tool", "arg", "depth", "published"), ITEMS,
                         ids=[f"{t}.{a}" for t, a, _, _ in ITEMS])
def test_a_closed_lists_items_publish_the_judges_words_or_range(
    tool: str, arg: str, depth: int, published: Callable[[], dict[str, Any]],
) -> None:
    items = _items(_schemas()[tool]["properties"][arg], depth)
    assert items.items() >= published().items(), items


#: Published by a tool scry-core registers, whose own judge words its refusal and whose own tests
#: hold the pair: `scry_core.knowledge_tool.judge`.
SHARED_JUDGE = {("knowledge_find", "kind")}


def test_the_shared_judge_refuses_a_kind_outside_the_enum_it_publishes() -> None:
    reply = test_envelope_seam._call("knowledge_find", {"kind": "zz"})[1]
    assert reply.get("code") == "bad_argument" and "kind='zz'" in reply["message"], reply


def test_no_argument_publishes_an_enum_no_judge_holds() -> None:
    """An `enum` in a schema with no row above would be a list nobody checks."""
    published = {(tool, arg) for tool, schema in _schemas().items()
                 for arg, prop in schema["properties"].items() if _enums(prop)}
    rows = ({(t, a) for t, a, _ in CLOSED} | {(t, a) for t, a, _, row in ITEMS if "enum" in row()}
            | SHARED_JUDGE)
    assert published == rows, published ^ rows


def _judged(path: Path) -> list[tuple[int, str, Words]]:
    """Every `vocab.one_of("name", value, options)` in `path`: line, argument name, options."""
    tree = ast.parse(path.read_text())
    module = sys.modules.get(f"scry_mame.{path.stem}")
    namespace = vars(module) if module else {}
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "one_of" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "vocab" and len(node.args) == 3):
            name = node.args[0].value if isinstance(node.args[0], ast.Constant) else ""
            found.append((node.lineno, str(name),
                          tuple(eval(ast.unparse(node.args[2]), dict(namespace)))))
    return found


def test_every_closed_vocabulary_the_server_judges_is_published(tmp_path: Path) -> None:
    """Each `vocab.one_of` argument is published with those words, and each row has its judge."""
    planted = tmp_path / "planted.py"
    planted.write_text('vocab.one_of("x", x, ("a", "b"))\nchunk.one_of("y", y, "ys", "", [])\n')
    assert _judged(planted) == [(1, "x", ("a", "b"))], "the control did not fire"
    sources = sorted(p for p in PACKAGE.glob("*.py")
                     if p.name not in {"__init__.py", "server.py", "gdb_session.py"})
    found = {(name, words) for src in sources for _, name, words in _judged(src)}
    published = {(arg, judged()) for _tool, arg, judged in CLOSED if arg != "method"}
    assert found == published, f"judged and not published: {found - published}; " \
                               f"published and judged by nothing: {published - found}"
    # a keyword or aliased call would be a judge the scan cannot see
    calls = sum(len(re.findall(r"(?<![\w.])vocab\.one_of\(", src.read_text())) for src in sources)
    assert calls == sum(len(_judged(src)) for src in sources), "a judge the scan cannot read"


@pytest.mark.parametrize("by", arming.BY_OPTIONS)
def test_breakpoint_at_accepts_exactly_the_words_its_enum_publishes(by: str) -> None:
    """`breakpoint_at` refuses every `by` outside the `BREAKPOINT_BY` it publishes."""
    ref = {"pointer": "[base]", "expr": "d0==1", "symbol": "Start"}.get(by, "0x400")
    try:
        breakpoints.check_breakpoint_at(ref, by=by)
        accepted = True
    except st.Invalid as e:
        assert e.code == "bad_argument", e
        accepted = False
    assert accepted is (by in breakpoints.BREAKPOINT_BY), by


#: What a call needs besides the argument under test to reach its judge.
NEEDS: dict[str, dict[str, Any]] = {
    "watch_add": {"ref": "0x400", "mode": "show"},
    "scan": {"method": "start", "ref": "0x400", "length": 16},
    "declaration_clear": {"kind": "watch", "ref": "0x400"}, "state_write": {"name": "a"},
    "breakpoint_at": {"ref": "0x400"}, "gfx_film": {"trigger": "0x400"},
    "log": {"pattern": "."}, "log_wait": {"pattern": "."},
    "start": {"binary": _abs("nowhere", "mame"), "system": "x", "rompath": _abs("nowhere"),
              "reference_rom": _abs("nowhere", "x.bin")},
    "gfx_locate": {"layouts": ["8x8"], "patch": [0, 0, 8, 8], "tag": "gfx"},
    "gfx_sweep": {"tag": "gfx"},
    "screen_map_write": {"method": "add", "screen": "a", "match": [[0, 0, 1, 1]]}}

NEEDS_BY_ARG: dict[tuple[str, str], dict[str, Any]] = {("scan", "operator"): {"method": "filter"}}

OUTSIDE: dict[str, Any] = {"string": "zz", "integer": 3}

TAILS: dict[tuple[str, str], str] = {
    ("log", "channel"): mfiles.NO_GUEST, ("log_wait", "channel"): mfiles.NO_GUEST,
    ("gfx_film", "length"): mfilm.LENGTH_WHY}


@pytest.mark.parametrize(("tool", "arg", "judged"), CLOSED, ids=[f"{t}.{a}" for t, a, _ in CLOSED])
def test_a_word_outside_the_enum_is_still_the_servers_refusal_through_the_protocol(
    tool: str, arg: str, judged: Callable[[], Words],
) -> None:
    """A word outside the enum still gets `one_of`'s sentence, never an SDK schema error."""
    outside = OUTSIDE[_json_type(judged())]
    needs = NEEDS_BY_ARG.get((tool, arg), NEEDS.get(tool, {}))
    reply = test_envelope_seam._call(tool, {**needs, arg: outside})[1]
    words = judged()
    assert reply.get("code") == "bad_argument", reply
    tail = TAILS.get((tool, arg), "")
    assert reply.get("message") == f"{arg} is one of {words}; got {outside!r}{tail}", reply


BAD_ITEM: dict[tuple[str, str], Any] = {("gfx_locate", "flips"): ["zz"],
                                        ("gfx_sweep", "sizes"): [[8, 9]],
                                        ("gfx_sweep", "planes"): [ml.PLANES_MAX + 1]}


PUBLISHED_ITEMS: dict[tuple[str, str], Any] = {
    ("gfx_locate", "flips"): list(mlocate.FLIPS),
    ("gfx_sweep", "sizes"): [[side, side] for side in msweep.SIDES],
    ("gfx_sweep", "planes"): [1, ml.PLANES_MAX]}


@pytest.mark.parametrize(("tool", "arg"), list(PUBLISHED_ITEMS),
                         ids=[f"{t}.{a}" for t, a in PUBLISHED_ITEMS])
def test_a_list_judge_accepts_every_item_its_schema_publishes(tool: str, arg: str) -> None:
    """A list of only the published items is never refused."""
    from scry_mame import args as margs
    beside = {"planes": [1]} if arg == "sizes" else {}
    margs.check(tool, **NEEDS.get(tool, {}), **beside, **{arg: PUBLISHED_ITEMS[(tool, arg)]})


@pytest.mark.parametrize(("tool", "arg"), list(BAD_ITEM), ids=[f"{t}.{a}" for t, a in BAD_ITEM])
def test_an_item_outside_the_list_schema_is_still_the_servers_refusal(tool: str, arg: str) -> None:
    """The list's own judge still answers, naming the argument and the list."""
    bad = BAD_ITEM[(tool, arg)]
    reply = test_envelope_seam._call(tool, {**NEEDS.get(tool, {}), arg: bad})[1]
    assert reply.get("code") == "bad_argument", reply
    assert str(reply.get("message")).startswith(f"{arg}={bad!r}: "), reply


@pytest.mark.parametrize(("tool", "arg", "judged"),
                         [row for row in CLOSED if row[0] in s._step_ops()],
                         ids=[f"{t}.{a}" for t, a, _ in CLOSED if t in s._step_ops()])
def test_a_sequence_step_still_judges_a_closed_arguments_type(
    tool: str, arg: str, judged: Callable[[], Words],
) -> None:
    """A `perform` step judges a closed argument's scalar type before it runs."""
    integer = _json_type(judged()) == "integer"
    wrong, said = ("5", "an integer") if integer else (5, "a string")
    needs = NEEDS_BY_ARG.get((tool, arg), NEEDS.get(tool, {}))
    out = s.perform(steps=[{"op": tool, **needs, arg: wrong}])
    assert f"{arg} is {said}; got {wrong!r}" in out.get("message", ""), out


from scry_mame import blits as mblits  # noqa: E402
from scry_mame import gfx as mgfx  # noqa: E402
from scry_mame import ramdac as mramdac  # noqa: E402
from scry_mame import read as mread  # noqa: E402

RANGES: list[tuple[str, str, int, int]] = [
    ("read_memory", "length", 1, mread.READ_MAX),
    ("read_block", "length", 1, mread.READ_MAX),
    ("disassemble", "length", 1, mread.READ_MAX),
    ("symbols_find", "limit", 1, mread.SYMBOLS_LIMIT_MAX),
    ("history", "limit", 1, mread.HISTORY_MAX),
    ("log", "limit", 1, mread.LOG_LIMIT_MAX),
    ("drive", "limit", 1, mread.LOG_LIMIT_MAX),
    ("gfx_sweep", "count", 1, msweep.COUNT_MAX),
    ("gfx_blit_source", "margin", 0, mblits.MARGIN_MAX),
    ("palette_log", "limit", 0, mramdac.LIMIT_MAX),
    ("scan", "limit", 1, words.HITS_MAX),
    ("gfx_view", "columns", 1, mgfx.COLUMNS_MAX),
    ("start", "stub_port", 0, launch.PORT_MAX),
    ("step", "count", 1, advance.step_max()),
    ("screen_wait", "every", 0, advance.SAMPLED_EVERY_MAX),
]
WAITS = ("seconds", "settle_seconds", "boot_seconds")


def _scalar(prop: dict[str, Any]) -> dict[str, Any]:
    """The non-null branch of an optional argument."""
    return next((b for b in prop.get("anyOf", []) if b.get("type") != "null"), prop)


@pytest.mark.parametrize(("tool", "arg", "lo", "hi"), RANGES,
                         ids=[f"{t}.{a}" for t, a, _, _ in RANGES])
def test_a_ranged_argument_publishes_its_judges_bounds(tool: str, arg: str, lo: int,
                                                       hi: int) -> None:
    prop = _scalar(_schemas()[tool]["properties"][arg])
    assert (prop.get("minimum"), prop.get("maximum")) == (lo, hi), prop


def test_every_wait_publishes_the_one_wait_bound_and_every_published_range_has_a_row() -> None:
    with pytest.raises(mstate.Invalid):
        vocab.check_wait(0)
    published, waits = set(), 0
    for tool, schema in _schemas().items():
        for arg, prop in schema["properties"].items():
            scalar = _scalar(prop)
            if "maximum" not in scalar or scalar.get("type") == "array":
                continue
            published.add((tool, arg))
            if arg in WAITS:
                waits += 1
                # 0 is a wait of its own only where a judge gives it a meaning
                low = ("minimum" if arg == "settle_seconds" or tool == "resume"
                       else "exclusiveMinimum")
                assert (scalar.get(low), scalar["maximum"]) == (0, vocab.WAIT_MAX_S), (tool, arg)
    rows = {(t, a) for t, a, _, _ in RANGES}
    assert waits >= 20, "the waits were not found: the schema read examined nothing"
    assert {p for p in published if p[1] not in WAITS} == rows
    every_wait = {(t, a) for t, schema in _schemas().items() for a in schema["properties"]
                  if a in WAITS}
    assert every_wait <= published, every_wait - published
