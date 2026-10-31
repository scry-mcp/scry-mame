"""The window MAME's live session asked for."""

from __future__ import annotations

from scry_core.window import WindowRequest
from scry_core.window_stand_ins import hosts

from scry_mame.state import STATE


def asked() -> tuple[int, WindowRequest] | None:
    if STATE.proc is None or STATE.window is None:
        return None
    return STATE.proc.pid, STATE.window


def obeying() -> hosts.Obeying:
    return hosts.Obeying(asked)
