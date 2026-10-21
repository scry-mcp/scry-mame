"""Each closed vocabulary a tool argument is judged against is published as that argument's
JSON-schema `enum`, generated from the judge's own tuple: the client sees the words where it
builds the call, and the two cannot drift because there is one tuple. `breakpoint_at`'s `by`
publishes the words a breakpoint takes, which its declaration narrows from the judge's. A list
whose items are held the same way publishes them on its items, an `enum` or a range.

The judge stays the argument's own (`vocab.one_of`, or the list's), so a word outside the list
is still the server's `bad_argument` sentence and never a schema error of the SDK's. A
vocabulary that depends on the machine (its cpus, its screens, its palettes) has no static list
and gets no enum.
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_envelope_seam  # noqa: E402

import mame_advance as advance  # noqa: E402
import mame_arming as arming  # noqa: E402
import mame_breakpoints as breakpoints  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_files as mfiles  # noqa: E402
import mame_film as mfilm  # noqa: E402
import mame_launch as launch  # noqa: E402
import mame_layout as ml  # noqa: E402
import mame_locate as mlocate  # noqa: E402
import mame_machine as mmachine  # noqa: E402
import mame_scan as mscan  # noqa: E402
import mame_screen as mscreen  # noqa: E402
import mame_space as mspace  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_state as st  # noqa: E402
import mame_sweep as msweep  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402

PACKAGE = Path(__file__).resolve().parent.parent

from scry_core.vocabulary import Words  # noqa: E402

#: Every argument held to a fixed vocabulary, and the words it publishes.
CLOSED: list[tuple[str, str, Callable[[], Words]]] = [
    ("step", "mode", lambda: advance.STEP_MODES),
    ("breakpoint_at", "by", lambda: breakpoints.BREAKPOINT_BY),
    ("breakpoint_at", "role", lambda: dec.ROLES),
    ("watch_add", "mode", lambda: dec.WATCH_MODES),
    ("watch_add", "by", lambda: watches.WATCH_BY),
    ("watch_add", "space", lambda: mspace.SPACES),
    ("watch_clear", "space", lambda: mspace.SPACES),
    ("watch_add", "trigger_type", lambda: dec.TRIGGER_TYPES),
    ("scan_start", "cell_bytes", lambda: mscan.CELL_BYTES),
    ("scan_filter", "operator", lambda: mscan.OPERATORS),
    ("screen_view", "mode", lambda: mscreen.MODES),
    ("gfx_film", "space", lambda: mspace.SPACES),
    ("gfx_film", "length", lambda: mfilm.LENGTHS),
    ("log", "channel", lambda: mfiles.LOG_CHANNELS),
    ("log_wait", "channel", lambda: mfiles.LOG_CHANNELS),
    ("start", "display", lambda: launch.DISPLAY_OPTIONS),
]

#: Every list argument whose ITEMS are held to a fixed vocabulary or range: how deep the items
#: sit (a list of lists is 2) and what each item publishes. The list's own judge stays the
#: argument's, which also refuses an empty list and a repeated item.
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
    """The schema of one item `depth` lists down, through the list branch of `list[...] | None`."""
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
    prop = _schemas()[tool]["properties"][arg]
    assert prop.get("enum") == list(judged()), prop
    assert prop.get("type") == _json_type(judged()), "the type stays the scalar one_of judges"


@pytest.mark.parametrize(("tool", "arg", "depth", "published"), ITEMS,
                         ids=[f"{t}.{a}" for t, a, _, _ in ITEMS])
def test_a_closed_lists_items_publish_the_judges_words_or_range(
    tool: str, arg: str, depth: int, published: Callable[[], dict[str, Any]],
) -> None:
    items = _items(_schemas()[tool]["properties"][arg], depth)
    assert items.items() >= published().items(), items


def test_no_argument_publishes_an_enum_no_judge_holds() -> None:
    """The other direction: an `enum` in a schema with no row above would be a list nobody
    checks the server against."""
    published = {(tool, arg) for tool, schema in _schemas().items()
                 for arg, prop in schema["properties"].items() if _enums(prop)}
    rows = {(t, a) for t, a, _ in CLOSED} | {(t, a) for t, a, _, row in ITEMS if "enum" in row()}
    assert published == rows, published ^ rows


def _judged(path: Path) -> list[tuple[int, str, Words]]:
    """Every `vocab.one_of("name", value, options)` in `path`: its line, the argument it names
    and its options, evaluated in the module's own namespace (every `mame_*.py` is imported by
    the server)."""
    tree = ast.parse(path.read_text())
    namespace = vars(sys.modules[path.stem]) if path.stem in sys.modules else {}
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
    """Each argument a module holds to a tuple with `vocab.one_of` is one the table above
    publishes under that name with those words, and each row has its judge, so a closed
    argument cannot arrive without its enum. Checked against a planted module first, so an
    empty scan is a finding and not a scan that read nothing."""
    planted = tmp_path / "planted.py"
    planted.write_text('vocab.one_of("x", x, ("a", "b"))\nchunk.one_of("y", y, "ys", "", [])\n')
    assert _judged(planted) == [(1, "x", ("a", "b"))], "the control did not fire"
    sources = sorted(PACKAGE.glob("mame_*.py"))
    found = {(name, words) for src in sources for _, name, words in _judged(src)}
    published = {(arg, judged()) for _tool, arg, judged in CLOSED}
    assert found == published, f"judged and not published: {found - published}; " \
                               f"published and judged by nothing: {published - found}"
    # EVERY CALL OF THE JUDGE IS ONE THE SCAN READ: a keyword or an aliased form would be a
    # judge it cannot see. `chunk.one_of` judges a session's words and `_one_of` a file's.
    calls = sum(len(re.findall(r"(?<![\w.])vocab\.one_of\(", src.read_text())) for src in sources)
    assert calls == sum(len(_judged(src)) for src in sources), "a judge the scan cannot read"


@pytest.mark.parametrize("by", arming.BY_OPTIONS)
def test_breakpoint_at_accepts_exactly_the_words_its_enum_publishes(by: str) -> None:
    """`breakpoint_at` refuses every `by` outside `BREAKPOINT_BY`, the enum it publishes; the
    parametrization is every word a declaration knows, so the two a breakpoint cannot be must
    refuse."""
    ref = {"pointer": "[base]", "expr": "d0==1", "symbol": "Start"}.get(by, "0x400")
    try:
        breakpoints.check_breakpoint_at(ref, by=by)
        accepted = True
    except st.Invalid as e:
        assert e.code == "bad_argument", e
        accepted = False
    assert accepted is (by in breakpoints.BREAKPOINT_BY), by


#: What a call needs besides the argument under test to reach that argument's judge.
NEEDS: dict[str, dict[str, Any]] = {
    "watch_add": {"ref": "0x400", "mode": "show"}, "scan_start": {"ref": "0x400", "length": 16},
    "watch_clear": {"ref": "0x400"},
    "breakpoint_at": {"ref": "0x400"}, "gfx_film": {"trigger": "0x400"},
    "log": {"pattern": "."}, "log_wait": {"pattern": "."},
    "start": {"binary": "/nowhere/mame", "system": "x", "rompath": "/nowhere",
              "reference_rom": "/nowhere/x.bin"},
    "gfx_locate": {"layouts": ["8x8"], "patch": [0, 0, 8, 8], "tag": "gfx"},
    "gfx_sweep": {"tag": "gfx"}}

#: A word outside each closed vocabulary: its scalar's type, in no vocabulary here.
OUTSIDE: dict[str, Any] = {"string": "zz", "integer": 3}

#: What a refusal adds after `one_of`'s sentence, where it adds anything.
TAILS: dict[tuple[str, str], str] = {
    ("log", "channel"): mfiles.NO_GUEST, ("log_wait", "channel"): mfiles.NO_GUEST,
    ("gfx_film", "length"): mfilm.LENGTH_WHY}


@pytest.mark.parametrize(("tool", "arg", "judged"), CLOSED, ids=[f"{t}.{a}" for t, a, _ in CLOSED])
def test_a_word_outside_the_enum_is_still_the_servers_refusal_through_the_protocol(
    tool: str, arg: str, judged: Callable[[], Words],
) -> None:
    """The enum is advice to the client; a client that sends another word through the protocol
    still gets `one_of`'s own sentence, whole, never a schema error of the SDK's."""
    outside = OUTSIDE[_json_type(judged())]
    reply = test_envelope_seam._call(tool, {**NEEDS.get(tool, {}), arg: outside})[1]
    words = judged()
    assert reply.get("code") == "bad_argument", reply
    tail = TAILS.get((tool, arg), "")
    assert reply.get("message") == f"{arg} is one of {words}; got {outside!r}{tail}", reply


#: An item outside each list's vocabulary or range.
BAD_ITEM: dict[tuple[str, str], Any] = {("gfx_locate", "flips"): ["zz"],
                                        ("gfx_sweep", "sizes"): [[8, 9]],
                                        ("gfx_sweep", "planes"): [ml.PLANES_MAX + 1]}


#: Every item each list's schema publishes, as a list the judge must accept whole.
PUBLISHED_ITEMS: dict[tuple[str, str], Any] = {
    ("gfx_locate", "flips"): list(mlocate.FLIPS),
    ("gfx_sweep", "sizes"): [[side, side] for side in msweep.SIDES],
    ("gfx_sweep", "planes"): [1, ml.PLANES_MAX]}


@pytest.mark.parametrize(("tool", "arg"), list(PUBLISHED_ITEMS),
                         ids=[f"{t}.{a}" for t, a in PUBLISHED_ITEMS])
def test_a_list_judge_accepts_every_item_its_schema_publishes(tool: str, arg: str) -> None:
    """The other direction of the items' schema: a client that sends only what it was shown is
    never refused, so the list's judge and the words or range on its items are one decision."""
    import mame_args as margs
    # One depth beside the sizes, so the family stays inside one sheet.
    beside = {"planes": [1]} if arg == "sizes" else {}
    margs.check(tool, **NEEDS.get(tool, {}), **beside, **{arg: PUBLISHED_ITEMS[(tool, arg)]})


def test_a_display_outside_its_words_is_refused_before_the_quick_run_is() -> None:
    """The word is wrong on any machine and in any mode, so it is judged before what `shared`
    makes of it, and before any file is looked for."""
    with pytest.raises(st.Invalid, match=r"^display is one of \('', 'main', 'secondary'\); "
                                         r"got 'tv'$"):
        launch.judge(binary="/nowhere/mame", system="x", rompath="/nowhere",
                     reference_rom="/nowhere/x.bin", symbols="", reference_addr="0x0",
                     inipath="", wait=8.0, shared=False, boot_lua="", env=None, bases=None,
                     reference_base="0x0", display="tv", port=0, state_dir="",
                     throttle_from_frame=0)


@pytest.mark.parametrize(("tool", "arg"), list(BAD_ITEM), ids=[f"{t}.{a}" for t, a in BAD_ITEM])
def test_an_item_outside_the_list_schema_is_still_the_servers_refusal(tool: str, arg: str) -> None:
    """The items' enum and range are advice too: the list's own judge still answers, naming
    the argument and the list it was given."""
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
    """A `perform` step is judged by the tool's signature before it runs: a closed argument is
    still its scalar there, whatever the schema annotation around it."""
    integer = _json_type(judged()) == "integer"
    wrong, said = ("5", "an integer") if integer else (5, "a string")
    out = s.perform(steps=[{"op": tool, **NEEDS.get(tool, {}), arg: wrong}])
    assert f"{arg} is {said}; got {wrong!r}" in out.get("message", ""), out


#: Every scalar argument held to a range, and the bounds its judge holds it to: the wait bound
#: of every tool that takes `seconds` or `settle_seconds` is read off the schema itself below.
import mame_blits as mblits  # noqa: E402
import mame_gfx as mgfx  # noqa: E402
import mame_inputs as inputs  # noqa: E402
import mame_ramdac as mramdac  # noqa: E402
import mame_read as mread  # noqa: E402

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
    ("gfx_view", "columns", 1, mgfx.COLUMNS_MAX),
    ("start", "stub_port", 0, launch.PORT_MAX),
    ("step", "count", 1, advance.step_max()),
]
WAITS = ("seconds", "settle_seconds", "boot_seconds")


def _scalar(prop: dict[str, Any]) -> dict[str, Any]:
    """The scalar branch of an optional argument (`T | None`), or the argument itself."""
    return next((b for b in prop.get("anyOf", []) if b.get("type") != "null"), prop)


@pytest.mark.parametrize(("tool", "arg", "lo", "hi"), RANGES,
                         ids=[f"{t}.{a}" for t, a, _, _ in RANGES])
def test_a_ranged_argument_publishes_its_judges_bounds(tool: str, arg: str, lo: int,
                                                       hi: int) -> None:
    prop = _scalar(_schemas()[tool]["properties"][arg])
    assert (prop.get("minimum"), prop.get("maximum")) == (lo, hi), prop


def test_every_wait_publishes_the_one_wait_bound_and_every_published_range_has_a_row() -> None:
    with pytest.raises(mstate.Invalid):
        inputs.seconds_bound(0)        # the judge refuses the floor the schema leaves open
    published, waits = set(), 0
    for tool, schema in _schemas().items():
        for arg, prop in schema["properties"].items():
            scalar = _scalar(prop)
            if "maximum" not in scalar or scalar.get("type") == "array":
                continue
            published.add((tool, arg))
            if arg in WAITS:
                waits += 1
                # 0 IS A WAIT OF ITS OWN only where a judge says what it means (`resume`'s no
                # deadline, a list's never wait); everywhere else the judge refuses it.
                low = ("minimum" if arg == "settle_seconds" or tool == "resume"
                       else "exclusiveMinimum")
                assert (scalar.get(low), scalar["maximum"]) == (0, inputs.WAIT_MAX_S), (tool, arg)
    rows = {(t, a) for t, a, _, _ in RANGES}
    assert waits >= 20, "the waits were not found: the schema read examined nothing"
    assert {p for p in published if p[1] not in WAITS} == rows
    every_wait = {(t, a) for t, schema in _schemas().items() for a in schema["properties"]
                  if a in WAITS}
    assert every_wait <= published, every_wait - published
