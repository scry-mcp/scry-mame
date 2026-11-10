"""The one Lua chunk evaluation every graphics tool shares, and its common refusals."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from scry_core import file_names
from scry_core import progress as mprogress

from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame import transport
from scry_mame.state import STATE


def run(ses: gs.Session, scratch: Path, script: str, seconds: float, progress: mprogress.Progress,
        what: str) -> tuple[str, dict[str, Any]]:
    """Evaluate `script` without altering anything; answer the console's text and the account.
    A script that raised is `unexpected_answer`."""
    pc_before = ses.current_pc()
    answer, ahead, evaluated_by, reader_steps, resent, seq = transport.evaluate(
        ses, scratch, script, seconds, progress, pc_before, alters=False)
    common: dict[str, Any] = dict(evaluated_by=evaluated_by, lines_ahead=ahead,
                                  reader_steps=reader_steps,
                                  **transport.console_did(answer, resent),
                                  call=st.sentinel_line(seq), pc_before=st.hex_addr(pc_before))
    if not answer.ok:
        raise st.Invalid("unexpected_answer", f"the console raised in the {what} chunk: "
                         f"{answer.error}", **common)
    return answer.text, common


def next_file(scratch: Path, stem: str) -> Path:
    """The next chunk's file, named by the console call number `send` is about to take."""
    return scratch / file_names.name(stem, STATE.lua_seq + 1, extension="bin")


def no_line(what: str, text: str, common: dict[str, Any]) -> NoReturn:
    """The chunk printed none of the lines its parser knows."""
    raise st.Invalid("unexpected_answer",
                     f"the console printed no {what} line: {text.strip()[-200:]!r}", **common)


def one_of(thing: str, have: list[str], field: str, remedy: str,
           common: dict[str, Any]) -> NoReturn:
    """Refuse a tool that needs the machine's only `thing`: `no_channel`, or `ambiguous_ref`."""
    if not have:
        raise st.Invalid("no_channel", f"this machine has no {thing}", **{field: have}, **common)
    raise st.Invalid("ambiguous_ref", f"{len(have)} {thing}s here, {have}: {remedy}",
                     **{field: have}, **common)
