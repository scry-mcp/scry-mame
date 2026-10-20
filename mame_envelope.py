"""THE SHAPE EVERY REPLY TAKES: `status`, the tool's own fields, then the `session` block that says
whether the machine is alive, running and written to. It is built FROM the state the server
holds (`mame_state`). Every body closes its reply through `envelope`; the block the caller reads
is composed again by `mame_mcp.tool` once the body is done
(`scry_core.boundary.Boundary.finished`), so it says what the machine is doing after the call.
"""

from __future__ import annotations

from typing import Any

from scry_core import prose
from scry_core import reply_contract as contract
from scry_core import session_block as blocks

import mame_state as st
from mame_state import STATE


def invalid(code: contract.Code, message: str, **fields: Any) -> dict[str, Any]:
    """A refusal as a REPLY, for the tools that answer INVALID without raising: built through
    the contract's class, so a code outside the table or a reserved field is refused here."""
    return envelope(contract.refusal(code, message, **fields))


def console_counts() -> dict[str, int]:
    """What the console channel has done to this session so far: reader deaths, chunks it ran
    AGAIN, and lines it took and never evaluated, AS THE LUA-FAMILY READERS COUNTED THEM when
    they read an answer back. A line sent and never read back (a `throttle` asked while
    stopped) is counted by nobody until the next such read or until `close`, which reads
    what nobody did, so three zeros before `close` describe what has been read, not the
    whole of what the console did.

    ONE PLACE MAPS THE FIELDS TO THE KEYS, so the block a caller reads and the counters the
    detectors feed cannot drift into two spellings of one idea.
    """
    return {"thread_errors": STATE.console_thread_errors,
            "reruns": STATE.console_reruns_seen,
            "lost": STATE.console_lines_lost}


def envelope(extra: dict[str, Any]) -> dict[str, Any]:
    """Every reply: `status`, the tool's own fields, then the `session` block.

    `status` is `ok` unless the tool's own fields declared the answer INVALID (`invalid` above, or a
    raised `Invalid` the server's wrapper turns into one), and the `session` block at the end (which
    `mame_mcp.tool` composes again after the body, `close`'s aside) carries `alive`, `running`,
    `altered` and each alarm while it holds, with a `note` beside them once the machine has been
    written to (`session_block` says which half rides where). The one-line `summary` that opens
    every reply is added by `mame_mcp.tool`, which knows the tool's name and arguments; this
    function does not. The contract's guard runs on the result, so a malformed refusal is a
    programmer's error here and never a reply.
    """
    out: dict[str, Any] = {"status": extra.get("status", "ok")}
    out.update(extra)
    # A stop the machine reached on its own is reported ONCE, by the reply of whichever
    # tool found it. ATTACHED HERE, CLEARED BY `State.end_call` when the outer call ends:
    # a tool body that builds another body's reply on its way (`run_to` declaring its control,
    # `input` running its frames) would otherwise spend the account on a reply it discards.
    if STATE.found_stop_last and "stopped_on_its_own" not in out:
        out["stopped_on_its_own"] = dict(STATE.found_stop_last)
    out["session"] = session_block()
    return contract.check_envelope(out)


def session_block(whole: bool = False) -> dict[str, Any]:
    """The `session` block, READ off the state and writing none of it: `envelope`'s, and the one
    `mame_mcp.tool` composes after a body (`scry_core.boundary.Boundary.finished`). Its alarms
    ride on every reply; what only counts rides whole on `start` and `status`
    (`scry_core.session_block`), and on `close` as the last account of the session it ends."""
    n = STATE.altered()
    alive = STATE.ses is not None and STATE.proc is not None and STATE.proc.poll() is None
    broken = STATE.broken
    alarms: dict[str, Any] = {
        "alive": alive,
        # A BROKEN SESSION CLAIMS NEITHER: `running` is what the flag TAKES the machine to be,
        # and a channel that lost its place supports no such reading, so `broken` answers.
        "running": bool(alive and STATE.ses is not None and STATE.ses.running and not broken),
        "altered": bool(n),
    }
    console = console_counts()
    fixed: dict[str, Any] = {"altering_writes": n}
    # THE CONSOLE'S COUNTS ARE AN ALARM ONCE ANY IS NOT ZERO: a line lost, a reader that died or a
    # chunk run twice, and from then on what the session reports rests on that channel. Three
    # zeros are a count, on `start` and `status`.
    (alarms if any(console.values()) else fixed)["console"] = console
    # ON EVERY REPLY UNTIL IT IS DEALT WITH. A throttle that did not land makes every
    # timing this session goes on to take a timing of a speed nobody asked for, and the
    # call that would naturally report it is one nobody is obliged to make.
    if broken:
        alarms["broken"] = broken
    if STATE.throttles_not_applied:
        alarms["throttles_not_applied"] = [dict(r) for r in STATE.throttles_not_applied]
    if STATE.lua_read_only_claims:
        alarms["read_only_claims"] = STATE.lua_read_only_claims
        st.add_note(alarms,
            f"{prose.counted(STATE.lua_read_only_claims, 'raw `lua` call')} "
            f"{prose.agrees(STATE.lua_read_only_claims, 'was', 'were')} declared read_only BY THE "
            "CALLER and are not counted as writes. Nothing verified that claim: a Lua string can "
            "read a byte or rewrite RAM and the text does not say which, so `altered` here rests "
            "on the caller's word for those calls")
    if n:
        st.add_note(alarms, "this session has been MODIFIED: what is measured here does not "
                            "describe a normal run of the game")
    return blocks.block(alarms, fixed, whole)
