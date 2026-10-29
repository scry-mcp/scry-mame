"""The tools that fold one resource's operations (`scry_core.methods`): the declarations by `kind`,
and the comments, the screen map, the value scan and the saved states by `method`. Each method's
body runs behind the gate it needs and its judge is its own module's, so the batch and the
surface ask one table (`sequence.BY_OP`)."""

from __future__ import annotations

from typing import Any

from scry_core import declaration_rows, methods, screen_map
from scry_core import progress as mprogress
from scry_core import scan_vocabulary as words
from scry_core import vocabulary as vocab
from scry_core.methods import Method

from scry_mame import (
    breakpoints,
    comments,
    cpus,
    inputs,
    iotaps,
    regpoints,
    savestates,
    summaries,
    watches,
)
from scry_mame import maps as mmaps
from scry_mame import scan as mscan
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame.running import contact, stopped

KINDS = tuple(summaries.DECLARATION_ROWS)


def _list_watches(ses: Any, cpu: str) -> dict[str, Any]:
    """The watches with each io tap among them (`space: "io"`, `stored: false`)."""
    reply = watches.list_watches(ses, cpu)
    reply["watches"] += iotaps.rows(None, at_stop=False,
                                    cpu=cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None)
    return reply


_LISTS = {"breakpoint": breakpoints.list_breakpoints, "regpoint": regpoints.list_regpoints,
          "watch": _list_watches}


def check_list_declarations(kind: str = "", **_: Any) -> None:
    vocab.one_of("kind", kind, ("", *KINDS))


def list_declarations(kind: str, cpu: str) -> dict[str, Any]:
    """Each kind's rows under its field, every kind when `kind` is empty
    (`scry_core.declaration_rows.merged`)."""
    check_list_declarations(kind)
    ses = contact()[0]
    return declaration_rows.merged({summaries.DECLARATION_ROWS[k]: _LISTS[k](ses, cpu)
                                    for k in declaration_rows.chosen_kinds(kind, KINDS)})


def check_clear_declarations(kind: str = "", ref: str = "", all: bool = False,
                             space: str = mspace.PROGRAM, **_: Any) -> None:
    vocab.one_of("kind", kind, KINDS)
    if kind == "watch":
        watches.check_clear_watches(ref, all, space)
        return
    if space != mspace.PROGRAM:
        raise st.Invalid("bad_argument", f"kind `{kind}` does not take `space`: only a watch "
                         "has one")
    (breakpoints.check_clear_breakpoints if kind == "breakpoint"
     else regpoints.check_clear_regpoints)(ref, all)


def clear_declarations(kind: str, ref: str, cpu: str, all: bool, space: str) -> dict[str, Any]:
    """`kind`'s declarations `ref` names, or every one with `all`, disarmed; a watch's
    `space: io` is an io tap's, and `all` takes the taps too."""
    check_clear_declarations(kind, ref, all, space)
    ses = contact()[0]
    if kind == "breakpoint":
        return breakpoints.clear_breakpoints(ses, ref, cpu, all)
    if kind == "regpoint":
        return regpoints.clear_regpoints(ses, ref, cpu, all)
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    if space == mspace.IO:
        return iotaps.clear_taps(ses, ref, only)
    reply = watches.clear_watches(ses, ref, cpu, all)
    if all and (gone := iotaps.clear("", only)):
        reply["tallies_removed"] = [*reply.get("tallies_removed", []), *gone]
    return reply


def _add_comment(ref: str, text: str, cpu: str = "") -> dict[str, Any]:
    return comments.add_comment(*stopped("comment_write add"), ref, text, cpu)


def _delete_comment(ref: str, cpu: str = "") -> dict[str, Any]:
    return comments.delete_comment(*stopped("comment_write delete"), ref, cpu)


def _save_comments(dest: str) -> dict[str, Any]:
    contact()
    return comments.save_comments(dest)


def _load_comments(path: str) -> dict[str, Any]:
    return comments.load_comments(*stopped("comment_write load"), path)


COMMENT = {
    "add": Method(_add_comment, comments.check_add_comment, summaries.add_comment),
    "delete": Method(_delete_comment, comments.check_delete_comment, summaries.delete_comment),
    "save": Method(_save_comments, comments.check_save_comments, summaries.save_comments),
    "load": Method(_load_comments, comments.check_load_comments, summaries.load_comments),
}


def _add_map(screen: str, match: list[list[int]], controls: list[dict[str, Any]] | None = None,
             cells: str = "rgb", anchor: str = "", *,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    return mmaps.add_map(*stopped("a screen map"), screen, match, controls, cells, anchor,
                         progress)


def _load_map(path: str, scale: int = 1, margin: list[int] | None = None) -> dict[str, Any]:
    return mmaps.load_map(path, scale, margin)


def _save_map(dest: str, overwrite: bool = False) -> dict[str, Any]:
    return mmaps.save_map(dest, overwrite)


MAP = {
    "add": Method(_add_map, mmaps.check_add_map, screen_map.add_line),
    "load": Method(_load_map, mmaps.check_load_map, screen_map.load_line),
    "save": Method(_save_map, mmaps.check_save_map, screen_map.save_line),
}


def _start_scan(ref: str, length: int, cell_bytes: int = 1, cpu: str = "") -> dict[str, Any]:
    return mscan.start_scan(*stopped("a value scan"), ref, length, cell_bytes, cpu)


def _filter_scan(operator: str = "=", value: int | None = None,
                 limit: int = words.HITS_DEFAULT) -> dict[str, Any]:
    return mscan.filter_scan(*stopped("a value scan"), operator, value, limit)


def _clear_scan() -> dict[str, Any]:
    contact()
    return mscan.clear_scan()


SCAN = {
    "start": Method(_start_scan, mscan.check_start_scan, summaries.start_scan),
    "filter": Method(_filter_scan, mscan.check_filter_scan, summaries.filter_scan),
    "clear": Method(_clear_scan, methods.no_check, summaries.clear_scan),
}


def _save_state(name: str) -> dict[str, Any]:
    return savestates.save_state(*stopped("a state save"), name)


def _load_state(name: str) -> dict[str, Any]:
    return savestates.load_state(*stopped("a state load"), name)


STATE_METHODS = {
    "save": Method(_save_state, savestates.check_state_name, summaries.save_state),
    "load": Method(_load_state, savestates.check_state_name, summaries.load_state),
}

#: Each `method` fold's method names, which the running gate is held to.
METHODS = {"comment_write": tuple(COMMENT), "screen_map_write": tuple(MAP), "scan": tuple(SCAN),
           "state_write": tuple(STATE_METHODS)}

#: Each fold's pre-gate judge, as the batch's table holds it.
CHECKS = {
    "declaration_list": check_list_declarations,
    "declaration_clear": check_clear_declarations,
    "comment_write": methods.fold_check(COMMENT),
    "screen_map_write": methods.fold_check(MAP),
    "scan": methods.fold_check(SCAN),
    "state_write": methods.fold_check(STATE_METHODS),
}
