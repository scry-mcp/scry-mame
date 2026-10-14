"""THE SHAPE EVERY REPLY TAKES: `status`, the tool's own fields, then the `session` block that says
whether the machine is alive, running and written to. It is built FROM the state the server
holds (`mame_state`). Every body closes its reply through `envelope`; the block the caller reads
is composed again by the server's `tool` once the body is done (`server._finished`), so it says
what the machine is doing after the call.
"""

from __future__ import annotations

from typing import Any

from scry_core import reply_contract as contract

import mame_prose as prose
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
    the server's `tool` composes again after the body, `close`'s aside) carries `alive`, `running`,
    `altered` and the `altering_writes` count (see the server's module docstring), with a `note`
    beside them once the machine has been written to. The one-line `summary` that opens every reply
    is added by the server's `tool`, which knows the tool's name and arguments; this function does
    not. The contract's guard runs on the result, so a malformed refusal is a programmer's error
    here and never a reply.
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


def session_block() -> dict[str, Any]:
    """The `session` block alone, READ off the state and writing none of it: `envelope`'s, and
    the one the server's `tool` composes after a body (`server._finished`)."""
    n = STATE.altered()
    alive = STATE.ses is not None and STATE.proc is not None and STATE.proc.poll() is None
    broken = STATE.broken
    session: dict[str, Any] = {
        "alive": alive,
        # A BROKEN SESSION CLAIMS NEITHER: `running` is what the flag TAKES the machine to be,
        # and a channel that lost its place supports no such reading, so `broken` answers.
        "running": bool(alive and STATE.ses is not None and STATE.ses.running and not broken),
        "altered": bool(n),
        "altering_writes": n,
        # PRESENT ON EVERY REPLY, three zeros and all, for the reason
        # `mame_transport.console_did` gives its own fields: a zero is read as looked-at, and an
        # object that appears only when something went wrong is one a caller never learns to read.
        "console": console_counts(),
    }
    # ON EVERY REPLY UNTIL IT IS DEALT WITH. A throttle that did not land makes every
    # timing this session goes on to take a timing of a speed nobody asked for, and the
    # call that would naturally report it is one nobody is obliged to make.
    if broken:
        session["broken"] = broken
    if STATE.throttles_not_applied:
        session["throttles_not_applied"] = [dict(r) for r in STATE.throttles_not_applied]
    if STATE.lua_read_only_claims:
        session["read_only_claims"] = STATE.lua_read_only_claims
        st.add_note(session,
            f"{prose.counted(STATE.lua_read_only_claims, 'raw `lua` call')} "
            f"{prose.agrees(STATE.lua_read_only_claims, 'was', 'were')} declared read_only BY THE "
            "CALLER and are not counted as writes. Nothing verified that claim: a Lua string can "
            "read a byte or rewrite RAM and the text does not say which, so `altered` here rests "
            "on the caller's word for those calls")
    if n:
        st.add_note(session, "this session has been MODIFIED: what is measured here does not "
                             "describe a normal run of the game")
    return session
