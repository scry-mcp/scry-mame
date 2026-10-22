"""`mame_args`: the table that decides which arguments are judged before the machine is asked for.

Every entry in `BY_TOOL` is the `check_*` function of the module that does the work, and that
module calls the same function itself; so a gate comparing two implementations would compare one
function against itself, a green that cannot go red. What holds the design is STRUCTURAL:

  - every tool the server registers is either in `BY_TOOL` or named in `MACHINE_JUDGES`;
  - every `BY_TOOL` entry is actually CALLED, by the tool body it belongs to in `server.py` AND by
    the module function that implements the tool -- a wiring nothing held before, so a check could
    be deleted from a body with the suite still green;
  - every call site's keywords match the signature they reach, neither swallowed by a `**_` nor
    absent, because a keyword a check silently swallows is an argument nobody judges;
  - and the function in the table is the SAME OBJECT the module uses, which is what makes "one
    implementation" a checked claim rather than a intention.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib
import re
import sys
import tempfile
from collections.abc import Callable
from typing import Any

import pytest
from scry_core import media_tools

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scry_core import strict_arguments as strict  # noqa: E402

import mame_advance as advance  # noqa: E402
import mame_args as args  # noqa: E402
import mame_audio as maudio  # noqa: E402
import mame_blits as mblits  # noqa: E402
import mame_block as block  # noqa: E402
import mame_breakpoints as breakpoints  # noqa: E402
import mame_comments as comments  # noqa: E402
import mame_docs as mdocs  # noqa: E402
import mame_draft as mdraft  # noqa: E402
import mame_files as files  # noqa: E402
import mame_film as mfilm  # noqa: E402
import mame_focus as mfocus  # noqa: E402
import mame_gfx as mgfx  # noqa: E402
import mame_launch as launch  # noqa: E402
import mame_locate as mlocate  # noqa: E402
import mame_lua as mlua  # noqa: E402
import mame_machine as machine  # noqa: E402
import mame_manifest as manifest  # noqa: E402
import mame_maps as mmaps  # noqa: E402
import mame_mcp  # noqa: E402
import mame_palette as mpalette  # noqa: E402
import mame_ramdac as mramdac  # noqa: E402
import mame_read as read  # noqa: E402
import mame_recording as mrec
import mame_regpoints as regpoints  # noqa: E402
import mame_running as running  # noqa: E402
import mame_savestates as savestates  # noqa: E402
import mame_scan as mscan  # noqa: E402
import mame_screen as mscreen  # noqa: E402
import mame_sequence as sequence  # noqa: E402
import mame_series as mseries  # noqa: E402
import mame_state as st  # noqa: E402
import mame_sweep as msweep  # noqa: E402
import mame_trace as mtrace  # noqa: E402
import mame_watches as watches  # noqa: E402
import mame_write as mwrite  # noqa: E402
import server as s  # noqa: E402

SERVER = pathlib.Path(s.__file__)


def _registered() -> set[str]:
    return {t.name for t in asyncio.run(s.mcp.list_tools())}


#: THE MEDIA FILE TOOLS have scry-core's bodies, registered with no body in this server: each
#: core body asks its own judge, which scry-core's suite holds, so no `args.check` call site
#: exists here for them to be bound to.
MEDIA = set(media_tools.TOOLS)


def _call_sites() -> dict[str, set[str]]:
    """Every `args.check("<tool>", ...)` in the server, keyed by the tool literal, with the keywords
    it passes -- AND BOUND TO THE FUNCTION IT SITS IN. A walk over the whole module found the
    literal wherever it was, so a check moved into the wrong tool's body still counted as present;
    the literal has to match the enclosing tool, and a tool asking twice is an error, not a
    last-wins overwrite."""
    out: dict[str, set[str]] = {}
    for fn in ast.parse(SERVER.read_text(encoding="utf-8")).body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "check"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                tool = str(node.args[0].value)
                assert tool == fn.name, f"{fn.name} asks for {tool!r}'s check, not its own"
                assert tool not in out, f"{tool} asks for its check twice"
                out[tool] = {kw.arg for kw in node.keywords if kw.arg}
    return out


def test_every_registered_tool_is_either_checked_or_named_as_unchecked() -> None:
    """RED BOTH WAYS: a tool the server grows with no entry, and an entry for a tool that is gone.
    An absent entry and a forgotten one look identical, which is why `MACHINE_JUDGES` names the
    deliberate omissions instead of leaving them out."""
    registered = _registered()
    assert not sorted(registered - args.KNOWN), (
        f"no entry in mame_args, not even a deliberate none: {sorted(registered - args.KNOWN)}")
    assert not sorted(args.KNOWN - registered), (
        f"mame_args names tools this server does not register: {sorted(args.KNOWN - registered)}")


def test_every_checked_tool_actually_asks_its_check() -> None:
    """THE WIRING, WHICH NOTHING HELD. A tool can sit in `BY_TOOL`, satisfy the roster test above,
    and have no `args.check(...)` in its body at all -- so its arguments are judged after the gate
    and the table says otherwise. The lines were inserted mechanically, and an omitted
    insertion is exactly the failure a mechanical edit has."""
    missing = sorted(set(args.BY_TOOL) - set(_call_sites()) - MEDIA)
    assert not missing, f"in BY_TOOL but never asked by the tool body: {missing}"


def test_no_tool_in_machine_judges_asks_for_a_check_anyway() -> None:
    """The mirror: a call site for a tool the table says needs none would pass silently (`check`
    returns without judging), leaving a line that reads like a guarantee and is not one."""
    pointless = sorted(set(_call_sites()) & args.MACHINE_JUDGES)
    assert not pointless, f"these ask for a check the table says they do not have: {pointless}"


@pytest.mark.parametrize("tool", sorted(set(args.BY_TOOL) - MEDIA))
def test_each_call_site_passes_what_its_check_takes(tool: str) -> None:
    """A KEYWORD A CHECK CANNOT TAKE IS A TypeError; ONE IT SWALLOWS IS AN ARGUMENT NOBODY JUDGES.
    Most of these checks end in `**_` so they can be reached from a batch step's loose dict, which
    means a misspelling is absorbed in silence rather than raised. This is the only thing that
    looks."""
    passed = _call_sites()[tool]
    sig = inspect.signature(args.BY_TOOL[tool])
    named = {p.name for p in sig.parameters.values()
             if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    required = {p.name for p in sig.parameters.values()
                if p.default is p.empty and p.kind is p.POSITIONAL_OR_KEYWORD}
    assert not passed - named, (
        f"{tool} passes {sorted(passed - named)}, which {args.BY_TOOL[tool].__qualname__} does not "
        f"take: swallowed by `**_` and never judged")
    assert not required - passed, (
        f"{tool} does not pass {sorted(required - passed)}, which its check requires")
    # AND EVERY PARAMETER THE TOOL ALSO HAS, default or not. This is the rule that was missing, and
    # what it cost: `seconds` was dropped from `run_for`'s call site while `check_run_for` still
    # declared it with a default, so the bound judged 30.0 on every call and `run_for(seconds=0)`
    # was never refused, because a parameter with a default looked optional. It is not optional
    # when the TOOL has an argument by that name --
    # then not passing it means judging a value the caller never sent.
    tool_params = {p.name for p in inspect.signature(getattr(s, tool)).parameters.values()
                   if p.name != "ctx"}
    owed = (named & tool_params) - passed
    assert not owed, (
        f"{tool} has {sorted(owed)} and does not pass it to its check, which declares it: the "
        f"check would judge its own default instead of what the caller sent")


#: THE SAME OBJECT, NOT AN EQUAL ONE, for every entry of the table: a routing that quietly pointed a
#: tool at another module's check would satisfy the roster and call-site tests above. (A private
#: copy inside the owning module is the body test's to catch, not this one's.)
OWNERS = {
    "read_memory": read.check_read_memory, "disassemble": read.check_disassemble,
    "registers": read.check_registers, "read_block": block.check_read_block,
    "find": read.check_find, "history": read.check_history,
    "symbols_find": read.check_symbols_find, "memdump": files.check_memdump,
    "snapshot": files.check_snapshot, "log": files.check_log,
    "log_wait": files.check_log_wait, "run_for": advance.check_run_for,
    "step": advance.check_step, "run_to": advance.check_run_to,
    "breakpoint_at": breakpoints.check_breakpoint_at, "watch_add": watches.check_watch_add,
    "regpoint_add": regpoints.check_regpoint_add,
    "write": mwrite.check_write, "set_register": mwrite.check_set_register,
    "perform": sequence.check_perform,
    "drive": sequence.check_drive,
}

OWNERS.update({
    "breakpoint_clear": breakpoints.check_breakpoint_clear, "debug": mwrite.check_debug,
    "machine_map": machine.check_machine_map,
    "watch_clear": watches.check_watch_clear, "regpoint_clear": regpoints.check_regpoint_clear,
    "resume": running.check_resume, "throttle": mlua.check_throttle,
    "record": mrec.check_record, "input": mlua.check_input,
    "audio_record": maudio.check_audio_record,
    "screen_signature": mscreen.check_screen_signature, "lua": mlua.check_lua,
    "state_save": savestates.check_state_name, "state_load": savestates.check_state_name,
    "rom_check": launch.check_rom_check, "start": launch.check_start,
    "focus": mfocus.check_focus,
    "palette": mpalette.check_palette, "screen_view": mscreen.check_screen_view,
    "gfx_view": mgfx.check_gfx_view, "gfx_locate": mlocate.check_gfx_locate,
    "gfx_load": manifest.check_gfx_load, "gfx_blits": mblits.check_gfx_blits,
    "gfx_blit_source": mblits.check_gfx_blit_source,
    "palette_log": mramdac.check_palette_log, "gfx_film": mfilm.check_gfx_film,
    "gfx_sweep": msweep.check_gfx_sweep, "gfx_draft": mdraft.check_gfx_draft,
    "scan_start": mscan.check_scan_start, "scan_filter": mscan.check_scan_filter,
    "comment_add": comments.check_comment_add, "comment_delete": comments.check_comment_delete,
    "comment_save": comments.check_comment_save, "comment_load": comments.check_comment_load,
    "trace": mtrace.check_trace, "series_capture": mseries.check_series_capture,
    "map_load": mmaps.check_map_load, "map_save": mmaps.check_map_save,
    "map_add": mmaps.check_map_add,
    **{name: spec.check for name, spec in media_tools.TOOLS.items()},
})


def test_owners_names_every_entry_of_the_table() -> None:
    """A hand-kept list walks whatever it happens to say; this holds it to the table."""
    assert set(OWNERS) == set(args.BY_TOOL), sorted(set(OWNERS) ^ set(args.BY_TOOL))


@pytest.mark.parametrize("tool", sorted(OWNERS))
def test_the_table_routes_to_the_modules_own_function(tool: str) -> None:
    assert args.BY_TOOL[tool] is OWNERS[tool], (
        f"{tool} is routed somewhere other than the module function that owns the rule")


def test_the_surfaces_table_is_the_batchs_plus_the_tools_that_are_not_operations() -> None:
    """ONE TABLE. A batch operation missing from it is skipped by `preflight` in silence, so a later
    step's bad value runs the steps before it while the surface refuses the same value before the
    machine is asked for. Held as set equality, not as an intersection: an intersection stays green
    when an entry is deleted."""
    surface = set(sequence.BY_OP) | {"perform", "drive", "rom_check", "start"}
    assert set(args.BY_TOOL) == surface, sorted(set(args.BY_TOOL) ^ surface)
    differ = sorted(op for op in sequence.BY_OP if sequence.BY_OP[op] is not args.BY_TOOL[op])
    assert not differ, f"the batch and the surface route these elsewhere from each other: {differ}"


def test_every_step_operation_is_either_checked_or_named_as_unchecked() -> None:
    """The batch's own roster, held to the server's operation vocabulary the way the surface's is
    held to the registry: an operation with no entry and no deliberate none is a step whose values
    nobody looks at before the list runs."""
    ops = set(s._step_ops())
    covered = set(sequence.BY_OP) | sequence.MACHINE_JUDGES
    assert not sorted(ops - covered), (
        f"steps nobody judges before the list runs: {sorted(ops - covered)}")
    assert not sorted(covered - ops), f"named but not an operation: {sorted(covered - ops)}"


def test_every_module_body_asks_its_own_check() -> None:
    """THE OTHER DIRECTION OF THE WIRING. The server asking a check before the gate is half the
    contract; the module function that does the work asking the SAME function is the other half,
    and it is what makes the rule one implementation rather than a table entry. `run_to`'s body did
    not, so a control was armed and persisted before the condition's shape was judged."""

    bodies: dict[str, Callable[..., Any]] = {
        "read_memory": read.read_memory, "disassemble": read.disassemble,
        "registers": read.registers_at_last_stop,
        "read_block": block.read_block,
        "find": read.find, "history": read.history,
        "symbols_find": read.symbols_find, "memdump": files.memdump,
        "snapshot": files.snapshot, "log": files.log, "log_wait": files.log_wait,
        "run_for": advance.run_for, "step": advance.step, "run_to": advance.run_to,
        "resume": running.resume, "throttle": mlua.throttle,
        "breakpoint_at": breakpoints.breakpoint_at, "watch_add": watches.watch_add,
        "regpoint_add": regpoints.regpoint_add,
        "write": mwrite.write, "set_register": mwrite.set_register,
        "record": mrec.record, "input": mlua.input_field,
        "audio_record": maudio.audio_record,
        "screen_signature": mscreen.screen_signature, "lua": mlua.lua,
        "state_save": savestates.state_save, "state_load": savestates.state_load,
        "focus": mfocus.focus,
        "palette": mpalette.palette, "screen_view": mscreen.screen_view,
        "gfx_view": mgfx.gfx_view, "gfx_locate": mlocate.gfx_locate,
        "gfx_load": manifest.gfx_load, "gfx_blits": mblits.gfx_blits,
        "gfx_blit_source": mblits.gfx_blit_source, "palette_log": mramdac.palette_log,
        "gfx_film": mfilm.gfx_film, "gfx_sweep": msweep.gfx_sweep, "gfx_draft": mdraft.gfx_draft,
        "scan_start": mscan.scan_start, "scan_filter": mscan.scan_filter,
        "comment_add": comments.comment_add, "comment_delete": comments.comment_delete,
        "comment_save": comments.comment_save, "comment_load": comments.comment_load,
        "trace": mtrace.trace, "map_load": mmaps.map_load, "map_save": mmaps.map_save,
        "map_add": mmaps.map_add,
        "breakpoint_clear": breakpoints.breakpoint_clear, "watch_clear": watches.watch_clear,
        "regpoint_clear": regpoints.regpoint_clear, "debug": mwrite.debug,
        "machine_map": machine.machine_map, "series_capture": mseries.series_capture,
        **{name: spec.body for name, spec in media_tools.TOOLS.items()},
    }
    assert set(bodies) == set(sequence.BY_OP), sorted(set(bodies) ^ set(sequence.BY_OP))
    for op, body in bodies.items():
        check = sequence.BY_OP[op]
        src = inspect.getsource(body)
        wanted = f"{check.__name__}("
        assert wanted in src, f"{op}'s body never asks {check.__name__}"


def test_an_unknown_tool_name_is_refused_rather_than_passed_through() -> None:
    """A name the table has never heard of is a PROGRAMMER's error, not a caller's: passing it
    through would make the pre-gate check a no-op nobody notices."""
    with pytest.raises(AssertionError, match="no such tool"):
        args.check("warp_core", ref="0x0")


def test_a_tool_the_machine_judges_passes_through_without_a_verdict() -> None:
    """The other half of `check`: a tool named in `MACHINE_JUDGES` is asked nothing and answers
    nothing. Without this case that branch is never taken by any test."""
    args.check("registers")
    args.check("breakpoint_list")


def test_a_region_search_is_not_refused_for_the_length_it_is_not_given() -> None:
    """`find(region=...)` ASKS for a zero length: the class supplies its own range. Whether the
    class EXISTS is the machine's answer, so that part still waits."""
    args.check("find", ref="", length=0, data_hex="00", symbol_class="DATA")


def test_the_one_hex_parser_accepts_what_it_always_accepted() -> None:
    """`bytes.fromhex` IGNORES ASCII WHITESPACE by documented design, so `de ad` is two bytes, and
    a line pasted out of a dump is exactly what somebody has in hand."""
    assert read.hex_bytes("data_hex", "de ad", verb="write") == b"\xde\xad"
    assert read.hex_bytes("data_hex", "dead", verb="write") == b"\xde\xad"
    args.check("write", ref="0x0", data_hex="de ad")
    args.check("find", ref="0x0", length=4, data_hex="de ad")


@pytest.mark.parametrize("value", ["", "abc", "zz", "de-ad"])
def test_the_one_hex_parser_refuses_what_is_not_hex(value: str) -> None:
    with pytest.raises(st.Invalid):
        read.hex_bytes("data_hex", value, verb="write")


@pytest.mark.parametrize(("dest", "expected"), [
    ("relative/x.png", "must be an absolute path or start with `~`"),
    ("/x\x00y.png", "holds a NUL"),
])
def test_a_dest_is_judged_as_a_path_with_no_machine_in_sight(dest: str, expected: str) -> None:
    """The refusal asked of the table directly: no session, no emulator, and two faults told
    apart by WHY each one fails."""
    with pytest.raises(st.Invalid) as caught:
        args.check("snapshot", dest=dest)
    assert expected in str(caught.value)


def test_a_dest_that_is_absolute_and_free_is_accepted() -> None:
    """THE POSITIVE CONTROL. Without it every row above passes on a check that refuses everything,
    and "the path rules are applied" and "the path rules reject all paths" look identical."""
    fresh = pathlib.Path(tempfile.gettempdir()) / "mame-args-positive-control-never-written.png"
    assert not fresh.exists(), "the control needs a path that is not there yet"
    args.check("snapshot", dest=str(fresh))


def test_an_empty_dest_is_the_scratch_for_the_tools_that_allow_one() -> None:
    """`snapshot` and `record` name the file themselves when given no `dest`, so an empty one is not
    a mistake there. `memdump` has no such default, and says so as a path refusal rather than in a
    sentence of its own."""
    args.check("snapshot", dest="")
    args.check("record", frames=2, dest="")
    with pytest.raises(st.Invalid):
        args.check("memdump", ref="0x4a0", length=16, dest="")


def test_no_refusal_sentence_is_written_at_more_than_one_site() -> None:
    """THE GATE THE DUPLICATION NEEDED, general rather than a list of known cases: the same refusal
    sentence raised at two SITES, in one module or two. It sees verbatim copies and nothing else --
    two copies that have already drifted by a word are two keys here -- which is why "one
    implementation" is held by the routing tests above and this is only the net under them."""
    import collections
    import re as _re
    seen: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    for path in sorted(pathlib.Path(args.__file__).parent.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", getattr(node.func, "id", ""))
                    in ("Invalid", "invalid")):
                continue
            parts = [sub.value for arg in node.args[1:] for sub in ast.walk(arg)
                     if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]
            if not parts:
                continue
            key = " ".join(w for w in _re.sub(r"[^a-z ]+", " ", " ".join(parts).lower()).split()
                           if len(w) > 2)
            if len(key.split()) >= 3:
                seen[key].add(f"{path.name}:{node.lineno}")
    shared = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    #: NOTHING IS EXEMPT, and there is no baseline: a baseline is the only thing that can grow.
    assert not shared, (
        "these refusal sentences are written at more than one site:\n"
        + "\n".join(f"  {v}: {k[:70]}" for k, v in sorted(shared.items())))


def test_a_segmented_ref_is_refused_before_the_machine_and_stored_nowhere() -> None:
    """This server's map is flat, so `12345:0010` is not a spelling of anything here and
    needs no table to say so: it is refused cold on every tool that
    takes a ref by name or address, while a NAME the table may hold still waits for the
    machine (the control)."""
    st.STATE.ses = None
    calls: tuple[Callable[[], dict[str, Any]], ...] = (
                 lambda: s.breakpoint_at(ref="12345:0010"),
                 lambda: s.watch_add(ref="12345:0010", mode="show", length=2),
                 lambda: s.run_to(ref="12345:0010"),
                 lambda: s.read_memory(ref="12345:0010", length=4),
                 lambda: s.write(ref="12345:0010", data_hex="00"),
                 lambda: s.find(ref="12345:0010", length=4, data_hex="00"))
    for call in calls:
        got = call()
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
        assert "linear" in got["message"] and "12345:0010" in got["message"], got["message"]
    control = s.breakpoint_at(ref="no_such_symbol")
    assert control["code"] == "no_session", control


def test_the_instructions_say_a_wrong_type_is_the_schemas_refusal() -> None:
    """A list where an integer is due never reaches the tool: the SDK refuses it against the
    schema, as its own error text and not this envelope, and the instructions say so."""
    assert "wrong TYPE" in (s.mcp.instructions or ""), "the sentence is missing"


# THE SENTENCE A TOOL USES TO CLAIM IT ANSWERS WHILE THE MACHINE RUNS. It is matched without
# regard to case because the docstrings shout the word or do not, and the claim is the same.
_CLAIMS_RUNNING = re.compile(r"(answers?|works|safe)[^.]{0,40}\brunning machine", re.IGNORECASE)


def test_every_tool_that_claims_it_answers_while_running_is_in_the_one_list() -> None:
    """THE INVARIANT, not one tool's case. A tool whose docstring tells a caller it answers on
    a running machine, and which is missing from `RUNNING_OK_OPS`, is refused by `perform` and
    `drive` for want of its name: the sequence waits for a stop that never comes and answers
    `not_stopped` about a call that would have answered at once on its own.

    A case about ONE tool cannot catch the rule for a tool added later, and this list is
    exactly the kind that grows. A case covers the failures its author thought of; this covers
    the rule.

    `close` and `start` are the lifecycle and are not sequence operations; they are named here
    rather than filtered by a predicate, so that adding one is a deliberate act.
    """
    lifecycle = {"close", "start"}
    docs = {t.name: (getattr(s, t.name).__doc__ or "")
            for t in s.mcp._tool_manager.list_tools()}
    # A CLAIM CONDITIONED ON AN ARGUMENT IS NOT THIS CLAIM. `registers` answers while running
    # with `from_last_stop=True` and needs a stop without it, and this list is per OPERATION:
    # putting the bare name in it would let a plain `registers` step through on a running
    # machine and fail on the wire. A tool that also carries the needs-stopped sentence is
    # saying its DEFAULT needs a stop, whatever one of its arguments can do.
    claimed = {name for name, doc in docs.items()
               if _CLAIMS_RUNNING.search(doc) and mdocs.NEEDS_STOPPED not in doc} - lifecycle
    assert claimed, "no tool claims it at all, so this examined nothing and is not a verdict"
    conditional = {name for name, doc in docs.items()
                   if _CLAIMS_RUNNING.search(doc) and mdocs.NEEDS_STOPPED in doc}
    assert conditional, ("no tool makes the CONDITIONAL claim any more, so the distinction "
                         "above is untested and this case has stopped watching half of itself")
    missing = sorted(claimed - sequence.RUNNING_OK_OPS)
    assert not missing, (
        f"these tools tell a caller they answer on a running machine and are not in "
        f"RUNNING_OK_OPS, so a sequence refuses them: {missing}")
    # AND THE OTHER DIRECTION, because a list may not name what the server does not register.
    unknown = sorted(sequence.RUNNING_OK_OPS - {t.name for t in s.mcp._tool_manager.list_tools()})
    assert not unknown, f"RUNNING_OK_OPS names tools this server does not register: {unknown}"


def test_the_instructions_families_are_the_registered_tools_and_the_running_ones_answer() -> None:
    """The roster's families name every registered tool once and nothing else (a misspelt name
    would be a tool the session looks for and never finds), and the instructions carry the
    sentence the table renders of what answers while the machine runs."""
    registered = [t.name for t in strict.registered(s.mcp)]
    assert mame_mcp.ROSTER.unlisted(registered) == []
    assert mame_mcp.ROSTER.running_sentence() in (s.mcp.instructions or "")


@pytest.mark.parametrize("addr", ["0xffff1", "0x10000000"])
def test_rom_check_refuses_an_address_outside_the_image_before_the_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, addr: str,
) -> None:
    """The image's size is a property of the FILE, so an address it does not cover is the
    caller's argument, refused before the gate as `start` refuses it, in the envelope and
    never as an exception out of the tool."""
    monkeypatch.setattr(st.STATE, "ses", None)
    monkeypatch.setattr(st.STATE, "proc", None)
    image = tmp_path / "rom.bin"
    image.write_bytes(bytes(0x100000))
    got = s.rom_check(reference_rom=str(image), reference_addr=addr)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "OUTSIDE" in got["message"], got["message"]
    # THE CONTROL: the image's last sixteen bytes are inside it, so that call passes the
    # argument check and reaches the gate, which has no machine to give it.
    control = s.rom_check(reference_rom=str(image), reference_addr="0xffff0")
    assert control["code"] == "no_session", control


_START_OK = {"binary": "/b/mame", "rompath": "/r", "reference_rom": "/r/rom.bin"}


@pytest.mark.parametrize(("given", "name"), [
    ({"binary": "mame"}, "binary"),
    ({"reference_rom": "rom.bin"}, "reference_rom"),
    ({"rompath": "roms"}, "rompath"),
    ({"inipath": "/a;ini"}, r"inipath\[1\]"),
    ({"cfg": "x.cfg"}, "cfg"),
    ({"boot_lua": "print('x')"}, "boot_lua"),
    ({"symbols": {"maincpu": "a.map"}}, r"symbols\['maincpu'\]"),
    ({"types": "t.types"}, "types"),
    ({"state_dir": "states"}, "state_dir"),
    ({"boot_lua": "/x\0y"}, "boot_lua"),
])
def test_starts_machine_independent_half_judges_every_path_by_its_name(
        given: dict[str, Any], name: str) -> None:
    """`launch.check_start` is the shape of each path `start` takes, the half a probe can ask:
    each refused under its own name, and a path no machine holds taken, since whether a file is
    there is the host's."""
    with pytest.raises(st.Invalid, match=rf"^{name}="):
        launch.check_start(**{**_START_OK, **given})
    launch.check_start(**_START_OK, boot_lua="/no/such/harness.lua", symbols={"a": "/no/a.map"},
                       inipath="/no/ini;/no/ini2", cfg="/no/x.cfg", state_dir="/no/states",
                       types={"maincpu": "/no/a.types", "audiocpu": ""})
    launch.check_start(**_START_OK, types="/no/a.types")


def test_starts_path_shapes_are_judged_in_the_order_judge_reads_them() -> None:
    """Two paths wrong at once: the one `judge` reads first is the one named."""
    with pytest.raises(st.Invalid, match=r"^binary="):
        launch.check_start(binary="mame", rompath="/r", reference_rom="rom.bin")
    with pytest.raises(st.Invalid, match=r"^reference_rom="):
        launch.check_start(binary="/b/mame", rompath="roms", reference_rom="rom.bin")


def test_a_start_refused_for_the_shape_of_a_path_still_carries_start_retries() -> None:
    """Every `start` reply carries `start_retries`, refusals included, so an empty list is an
    answer and never a missing field: the refusal of a path's shape, before anything else is
    judged, keeps that contract."""
    out = s.start(binary="mame", system="m68k", rompath="/r", reference_rom="/r/rom.bin")
    assert out["code"] == "bad_argument" and out["message"].startswith("binary="), out
    assert out["start_retries"] == [], out
