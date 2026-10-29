"""Address-space rules, below `watches` and `iotaps` to avoid an import cycle."""

from __future__ import annotations

from scry_core import vocabulary as vocab

from scry_mame import declarations as dec
from scry_mame import inputs
from scry_mame import state as st

PROGRAM, IO = "program", "io"
SPACES = (PROGRAM, IO)


def crosses(addr: int, width: int, data_width: int) -> bool:
    """Whether the range crosses a bus word, so no single write carries it."""
    nb = data_width // 8
    return addr % nb + width > nb


def splits_bus_word(addr: int, width: int, data_width: int) -> bool:
    """Whether the range crosses a bus word without starting and ending on a boundary."""
    nb = data_width // 8
    return crosses(addr, width, data_width) and (addr % nb != 0 or (addr + width) % nb != 0)


def suffix(space: str) -> str:
    """`@io` outside the program space, nothing inside it."""
    return "" if space == PROGRAM else f"@{space}"


def shown(held: str) -> dict[str, str]:
    """A tap's key as a reply carries it: the bare `ref`, plus `space` outside program."""
    tail = suffix(IO)
    if held.lower().endswith(tail):
        return {"ref": held[:-len(tail)], "space": IO}
    return {"ref": held}


def port(text: str, name: str) -> int:
    """Parse an io-space port: `0x` address, since the io space has no symbols."""
    if not inputs.is_address(text):
        raise st.Invalid("bad_argument", f"{name}={text!r} must be a port: an address written "
                         "`0x` (`0x6`), since the io space has no symbols"
                         + (f"; an address is written 0x{text.strip()}"
                            if inputs.HEX_ADDR.fullmatch(text.strip()) else ""))
    return int(text, 16)


def check_space(space: str, mode: str, ref: str, by: str, trigger: str) -> None:
    """Validate a watch's `space` and the modes and spelling a port takes."""
    vocab.one_of("space", space, SPACES)
    if space != IO:
        return
    if mode not in dec.TAP_MODES:
        raise st.Invalid("bad_argument", f'space="io" on a {mode} watch: a port is tapped by a '
                         "count or a capture watch; a change or show watch and an expr are the "
                         "debugger's, which watches and reads the program space")
    if by not in ("auto", "address") and mode == "count":
        raise st.Invalid("bad_argument", f"by={by!r} on a port: a port is an address written "
                         "`0x`, and the io space has no symbols")
    if by not in ("auto", "symbol", "address"):
        raise st.Invalid("bad_argument", f"by={by!r} on a capture's block: a tap sits on one "
                         "range for its life, by symbol or by address")
    if mode == "count":
        port(ref, "ref")
    else:
        port(trigger, "trigger")


def ranges_meet(a: int, a_width: int, b: int, b_width: int) -> bool:
    """Whether two ranges share a byte."""
    return a < b + b_width and b < a + a_width
