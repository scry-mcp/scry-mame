"""One Lua chunk that READS, evaluated for a graphics tool: the console's text and its account.

The graphics tools compose their chunk from function definitions (the screen's capture, a block's
dump, a palette's pens) and a body that calls them, so what several of them read is read by ONE
evaluation, of one instant: no guest instruction runs inside a chunk. This is the evaluation, the
fields every such reply carries, and the refusals every such chunk shares, in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from scry_core import progress as mprogress

import gdb_session as gs
import mame_state as st
import mame_transport as transport
from mame_state import STATE


def run(ses: gs.Session, scratch: Path, script: str, seconds: float, progress: mprogress.Progress,
        what: str) -> tuple[str, dict[str, Any]]:
    """Evaluate `script`, altering nothing, and answer the console's text and the account
    (`evaluated_by`, `lines_ahead`, `reader_steps`, the console's mishaps, `call`, `pc_before`).
    A script that raised is `unexpected_answer`, in the console's own words."""
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
    """Where the next chunk writes a file: named after the console call it belongs to (its
    sentinel's number, the one `mame_transport.send` is about to take), so a file found in the
    scratch says which `call` wrote it."""
    return scratch / f"{stem}-{STATE.lua_seq + 1}.bin"


def no_line(what: str, text: str, common: dict[str, Any]) -> NoReturn:
    """The chunk printed none of the lines its parser knows: the console's tail, verbatim."""
    raise st.Invalid("unexpected_answer",
                     f"the console printed no {what} line: {text.strip()[-200:]!r}", **common)


def one_of(thing: str, have: list[str], field: str, remedy: str,
           common: dict[str, Any]) -> NoReturn:
    """A tool that takes the machine's only `thing` found none, or several: `no_channel` for none,
    `ambiguous_ref` for several with the `remedy`, each naming what the machine has under
    `field`."""
    if not have:
        raise st.Invalid("no_channel", f"this machine has no {thing}", **{field: have}, **common)
    raise st.Invalid("ambiguous_ref", f"{len(have)} {thing}s here, {have}: {remedy}",
                     **{field: have}, **common)
