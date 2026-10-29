"""The shape of every reply: `status`, the tool's own fields, then the `session` block."""

from __future__ import annotations

from typing import Any

from scry_core import prose
from scry_core import reply_contract as contract
from scry_core import session_block as blocks

from scry_mame import state as st
from scry_mame.state import STATE


def invalid(code: contract.Code, message: str, **fields: Any) -> dict[str, Any]:
    """A refusal as a reply, for tools that answer INVALID without raising."""
    return envelope(contract.refusal(code, message, **fields))


def console_counts() -> dict[str, int]:
    """Console-channel failures, as the Lua-family readers counted them."""
    return {"thread_errors": STATE.console_thread_errors,
            "reruns": STATE.console_reruns_seen,
            "lost": STATE.console_lines_lost}


def envelope(extra: dict[str, Any]) -> dict[str, Any]:
    """Every reply's body: `status` (`ok` unless the fields declare INVALID), then the fields."""
    out: dict[str, Any] = {"status": extra.get("status", "ok")}
    out.update(extra)
    # Cleared by `State.end_call`, so a discarded inner reply cannot spend the one-time report.
    if STATE.found_stop_last and "stopped_on_its_own" not in out:
        out["stopped_on_its_own"] = dict(STATE.found_stop_last)
    return contract.check_envelope(out)


def with_view(reply: dict[str, Any]) -> dict[str, Any]:
    """Name the snapshot view a capture was rendered through."""
    if reply.get("status") != "ok":
        return reply
    tail = reply.pop("session", None)
    reply["view"] = STATE.view
    if tail is not None:
        reply["session"] = tail
    return reply


def session_block(whole: bool = False) -> dict[str, Any]:
    """The `session` block, read off the state without writing any of it."""
    n = STATE.altered()
    alive = STATE.ses is not None and STATE.proc is not None and STATE.proc.poll() is None
    broken = STATE.broken
    alarms: dict[str, Any] = {
        "alive": alive,
        # A broken channel supports no reading of the running flag, so `broken` answers.
        "running": bool(alive and STATE.ses is not None and STATE.ses.running and not broken),
        "altered": bool(n),
    }
    console = console_counts()
    fixed: dict[str, Any] = {"altering_writes": n}
    # Any non-zero count puts the session's reports in doubt.
    (alarms if any(console.values()) else fixed)["console"] = console
    # A throttle that did not land skews every later timing.
    if broken:
        alarms["broken"] = broken
    if STATE.throttles_not_applied:
        alarms["throttles_not_applied"] = [dict(r) for r in STATE.throttles_not_applied]
    # The tap still counts in the guest though its declaration is gone.
    if stuck := st.tallies_not_removed():
        alarms["tallies_not_removed"] = stuck
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
