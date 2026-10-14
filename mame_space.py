"""The address space a tap is installed in: the program's, or a port's in the io space.

The word and its rules, below every module that takes a `space`: `mame_watches` judges a
watch's arguments with them and `mame_iotaps` builds on `mame_watches`, so the rules cannot live
in either without an import cycle.
"""

from __future__ import annotations

import mame_declarations as dec
import mame_inputs as inputs
import mame_state as st

PROGRAM, IO = "program", "io"
SPACES = (PROGRAM, IO)


def lane_shift(at: int, width: int, data_width: int, endianness: str) -> int:
    """How far right to shift a bus write's data for the `width` bytes at byte `at` of its word:
    on a big-endian bus the lowest address is the high lane."""
    nb = data_width // 8
    return (nb - width - at) * 8 if endianness == "big" else at * 8


def crosses(addr: int, width: int, data_width: int) -> bool:
    """Whether the `width` bytes at `addr` cross a bus word, so no single write carries them."""
    nb = data_width // 8
    return addr % nb + width > nb


def splits_bus_word(addr: int, width: int, data_width: int) -> bool:
    """Whether the `width` bytes at `addr` cross a bus word of `data_width` bits without starting
    and ending on one. A write lands in one bus word, so a range inside one word is written
    whole and a range of whole words word by word, each row one word of it; this one covers a
    word only in part at an edge, and a row there is a fragment of that word."""
    nb = data_width // 8
    return crosses(addr, width, data_width) and (addr % nb != 0 or (addr + width) % nb != 0)


def suffix(space: str) -> str:
    """What a tap's id, and the key it is held under, carry outside the program space (`@io`):
    nothing inside it. A reply never shows the key: it shows `shown`'s pair."""
    return "" if space == PROGRAM else f"@{space}"


def shown(held: str) -> dict[str, str]:
    """A tap's key as a reply carries it: the bare `ref` a call takes back and, outside the
    program space, the `space` it is in, one spelling going in and coming out."""
    tail = suffix(IO)
    if held.lower().endswith(tail):
        return {"ref": held[:-len(tail)], "space": IO}
    return {"ref": held}


def port(text: str, name: str) -> int:
    """A port, an address in the io space, written `0x` like every address; the io space has no
    symbols. `name` is the argument it came in, which the refusal names."""
    if not inputs.is_address(text):
        raise st.Invalid("bad_argument", f"{name}={text!r} must be a port: an address written "
                         "`0x` (`0x6`), since the io space has no symbols"
                         + (f"; an address is written 0x{text.strip()}"
                            if inputs.HEX_ADDR.fullmatch(text.strip()) else ""))
    return int(text, 16)


def check_space(space: str, mode: str, ref: str, by: str, trigger: str) -> None:
    """A watch's `space`: the word, the modes a port takes (a tap's: a change or show watch and an
    expr are the debugger's, which watches and reads the program space), and the port spelled as
    a number, a count's `ref` or a capture's `trigger`. A capture's block stays in the program
    space and takes a symbol or an address, as there."""
    inputs.one_of("space", space, SPACES)
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
