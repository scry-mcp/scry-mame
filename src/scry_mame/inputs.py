"""The inputs every tool shares, each judged by one rule written once."""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any, NoReturn, overload

from scry_core import judges, picture, prose, steps
from scry_core.reply_contract import Invalid


def check_ref(ref: object, name: str = "ref") -> None:
    """A ref is a symbol name or a linear `0x` address; `SEG:OFF` is refused (the map is flat)."""
    if not isinstance(ref, str):
        raise Invalid("bad_argument",
                      f"{name}={ref!r} is not a string: a symbol or a `0x` address")
    if not ref.strip():
        raise Invalid("bad_argument", f"{name}={ref!r} is empty: a symbol or a `0x` address")
    if ":" in ref:
        raise Invalid("bad_argument",
                      f"an address here is linear, and {ref!r} carries a segment: give the "
                      "linear `0x` address, or the symbol")
    zero_x(ref, name)


# The shared grammar reads `+10` as hex, wrong for a call whose digits read either way.
_BARE_OFFSET = re.compile(r"\]\s*[+-]\s*([0-9a-fA-F]+)\s*$")


def check_pointer_offset(ref: str) -> None:
    """Refuse a pointer offset without `0x` whose digits read as decimal and as hex."""
    m = _BARE_OFFSET.search(ref)
    if m is not None and m.group(1).isdigit() and int(m.group(1)) >= 10:
        digits = m.group(1)
        raise Invalid("bad_argument",
                      f"the offset in {ref!r} is written without `0x`, and +{digits} is "
                      f"{prose.counted(int(digits, 16), 'byte')} in hex and {digits} in decimal: "
                      f"write `0x{digits}` or `{int(digits):#x}`")


def cpu_given(cpu: str) -> bool:
    return bool(cpu.strip())


def name_word(name: str, value: object, what: str) -> None:
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise Invalid("bad_argument", f"{name}={value!r}: {what}, one word with no whitespace")


def idle(name: str, goes_with: str, why: str) -> NoReturn:
    """Refuse an argument idle beside the others."""
    raise Invalid("bad_argument", f"`{name}` goes with `{goes_with}`: {why}")



def is_natural(value: object, lo: int = 0, hi: int | None = None) -> bool:
    return judges.whole(value, lo, hi)


def is_naturals(value: object, n: int | None = None, lo: int = 0) -> bool:
    """`value` is a list of `n` naturals at or above `lo`."""
    return (isinstance(value, list | tuple) and (n is None or len(value) == n)
            and all(is_natural(v, lo) for v in value))


def natural(name: str, value: object, what: str, lo: int = 0, hi: int | None = None) -> None:
    """Refuse `value` unless `is_natural`."""
    if not is_natural(value, lo, hi):
        raise Invalid("bad_argument", f"{name}={value!r}{what}")


def is_rectangle(value: object) -> bool:
    return (is_naturals(value, 4) and is_naturals(value[:2], 2)  # type: ignore[index]
            and is_naturals(value[2:], 2, 1))  # type: ignore[index]


#: Hex digits with or without `0x`: how an older store or file may spell an address.
HEX_ADDR = re.compile(r"(?:0[xX])?[0-9a-fA-F]+")


def hex_arg(name: str, value: str) -> int:
    """An address argument written `0x`; bare `int(value, 16)` accepts `-400` and `4_00`."""
    text = value.strip()
    if ADDRESS.fullmatch(text):
        return int(text, 16)
    if _BARE_HEX.fullmatch(text):
        raise Invalid("bad_argument", f"{name} is {value!r}; an address is written 0x{text}")
    raise Invalid("bad_argument", f"{name} is {value!r}, which is not an address like `0x400`")


#: A JSON integer or a `0x` string (REFERENCE.md, *Names for addresses*).
NumberArg = judges.NumberArg


def address_arg(name: str, value: object) -> int:
    """An address argument, `0x` text or an integer as CONTRIBUTING.md takes every address."""
    address = number_arg(name, value)
    if address < 0:
        raise Invalid("bad_argument", f"{name} is {value!r}: an address is not negative")
    return address

#: The widest number MAME's debugger holds: its expressions are 64-bit.
NUMBER_BITS = 64


def number_arg(name: str, value: object) -> int:
    """`value` as the integer it is or spells, `NUMBER_BITS` wide."""
    return judges.number(name, value, NUMBER_BITS, "MAME's debugger")


#: A list of numbers, each a `NumberArg` (a list of pens).
NumberList = list[NumberArg]


def pen(name: str, value: object) -> None:
    natural(name, value, " is not a pen number")


@functools.cache
def number_lists(fn: Callable[..., Any]) -> frozenset[str]:
    return frozenset(name for name, p in steps.signature_of(fn, eval_str=True).parameters.items()
                     if p.annotation in (NumberList, NumberList | None))


@functools.cache
def number_params(fn: Callable[..., Any]) -> dict[str, bool]:
    return {name: p.annotation != NumberArg
            for name, p in steps.signature_of(fn, eval_str=True).parameters.items()
            if p.annotation in (NumberArg, NumberArg | None)}


@overload
def as_read(value: NumberArg) -> int: ...
@overload
def as_read(value: NumberArg | None) -> int | None: ...
def as_read(value: NumberArg | None) -> int | None:
    assert value is None or isinstance(value, int), value
    return value


def list_as_read(values: NumberList | None) -> list[int] | None:
    return values  # type: ignore[return-value]


def numbers_read(fn: Callable[..., Any], args: dict[str, Any]) -> dict[str, Any]:
    """`args` with each number `fn` declares read by `number_arg`."""
    declared, lists = number_params(fn), number_lists(fn)
    return {name: (number_arg(name, value)
                   if name in declared and (value is not None or not declared[name]) else
                   [number_arg(f"{name}[{i}]", v) for i, v in enumerate(value)]
                   if name in lists and isinstance(value, list) else value)
            for name, value in args.items()}


# The spelling decides, never the table: bare hex (`adc`, `fade`) is also a plausible symbol,
# and letting the table decide would read one text as a symbol on one build and an address on
# the next. Bare hex naming no symbol is refused with the `0x` spelling it likely meant.
ADDRESS = re.compile(r"0[xX][0-9a-fA-F]+")
_BARE_HEX = re.compile(r"[0-9a-fA-F]+")


class BareHex(Invalid):
    """Bare hex naming no symbol; its own type so tools pass it through whole."""


def given(text: object) -> bool:
    return not isinstance(text, str) or bool(text.strip())


def zero_x(ref: str, name: str = "ref") -> None:
    """Refuse text that starts `0x` and is not an address; no symbol starts with `0x`."""
    text = ref.strip()
    if text[:2].lower() == "0x" and not ADDRESS.fullmatch(text):
        raise Invalid("bad_argument", f"{name}={ref!r} starts like an address and is not one: "
                                      "`0x` is followed by hex digits")


def by_spelling(by: str, ref: str) -> str | None:
    text = ref.strip()
    if by == "address" and not is_address(text):
        return (f"a declaration by address needs a `0x` address; got {ref!r}"
                + (f": an address is written 0x{text}" if HEX_ADDR.fullmatch(text) else
                   ": `breakpoint_at(by=\"address\")` and `watch_add(by=\"address\")` take one"))
    if by == "symbol" and is_address(text):
        return (f"a declaration by symbol names a symbol; got {ref!r}, which is written as an "
                "address: `breakpoint_at(by=\"address\")`, or `by=\"auto\"`")
    return None


def is_address(text: str) -> bool:
    return ADDRESS.fullmatch(text.strip()) is not None


def bare_hex(ref: str, cpu: str | None, loaded: int) -> BareHex:
    text = ref.strip()
    whose = f"{cpu}'s" if cpu else "the machine's"
    return BareHex("unknown_ref", f"{text!r} names no symbol of {whose} table ({loaded} loaded); "
                                  f"an address is written 0x{text}")


def not_a_ref(what: str, text: str, cpu: str | None = None, *, loaded: int | None = None,
              then: str = "") -> str:
    """The sentence for a ref that is no symbol and no `0x` address."""
    table = f"{cpu}'s table" if cpu else "this build's table"
    count = "" if loaded is None else f" ({prose.counted(loaded, 'symbol')} loaded)"
    lookup = f'symbols_find(name=..., cpu="{cpu}")' if cpu else "symbols_find(name=...)"
    return (f"{what} {text!r} is neither a symbol of {table}{count} nor a `0x` address{then}: "
            f"`{lookup}` says whether the table has one")


def classify(ref: str, names: Collection[str], cpu: str | None,
             held: Collection[str] = ()) -> str:
    """`"address"` or `"symbol"` for a ref a call typed, against `names` (upper-case) and `held`
    (stored refs); bare hex in neither is refused."""
    text = ref.strip()
    if ADDRESS.fullmatch(text):
        return "address"
    key = text.upper()
    if (_BARE_HEX.fullmatch(text) and key not in names
            and key not in {h.strip().upper() for h in held}):
        raise bare_hex(text, cpu, len(names))
    return "symbol"


#: A number in the console's grammar, where a bare number is hex; a run of letters is not one
#: (it may name a symbol), a `0b` token with other digits falls back to hex, and a `$` or `#`
#: inside a token is part of a name. A `#` run past 20 decimal digits is left as typed.
_CONSOLE_NUMBER = re.compile(
    r"(?<![\w.$#:])(?:0[xX](?P<hex>[0-9a-fA-F]+)|\$(?P<dollar>[0-9a-fA-F]+)"
    r"|#(?P<dec>[0-9]{1,20})|0[oO](?P<oct>[0-7]+)(?![\w])|0[bB](?P<bin>[01]+)(?![\w])"
    r"|(?P<bare>[0-9][0-9a-fA-F]*))(?![\w])")
_BASES = (("dec", 10), ("oct", 8), ("bin", 2), ("hex", 16), ("dollar", 16), ("bare", 16))


def _console_value(m: re.Match[str]) -> int:
    return next(int(m[group], base) for group, base in _BASES if m[group] is not None)


def match_key(ref: str, by: str) -> str:
    """The spelling two refs of one kind are compared under."""
    text = ref.strip()
    if by == "address" and HEX_ADDR.fullmatch(text):
        return f"0x{int(text, 16):x}"
    if by == "symbol":
        return text.upper()
    if by == "expr":
        return _CONSOLE_NUMBER.sub(lambda m: f"0x{_console_value(m):x}", text)
    return text


def place_key(text: str) -> str:
    return match_key(text, "address" if is_address(text) else "symbol")


def stored_place(text: str, table: Mapping[str, int]) -> int | None:
    """Where a stored place points: a `0x` address, else a name of `table`, else None."""
    key = text.strip()
    if is_address(key):
        return int(key, 16)
    if key.upper() in getattr(table, "ambiguous", ()):
        return None         # kept across a rebuild that repeated the name: waits, never guessed
    return table.get(key.upper())


def count(name: str, value: int, hi: int | None = None, tail: str = "", lo: int = 1) -> None:
    """The one judge of a count held to `lo`..`hi` (no ceiling when None)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise Invalid("bad_argument", f"{name} is a count; got {value!r}")
    if hi is not None and not lo <= value <= hi:
        raise Invalid("bad_argument", f"{name}={value!r} is outside {lo}..{hi}{tail}")
    if value < lo:
        raise Invalid("bad_argument", f"{name}={value!r} is below {lo}{tail}")


# The console's command line (`debugcon.cpp`) splits at a comma, ends at a semicolon outside
# brackets, opens a string at a quote and refuses an unbalanced bracket. This is stricter on
# purpose, so a caller learns one set of characters rather than the console's parser; control
# characters go too, since a terminal or log acts on them.
_PATH_BREAK = re.compile(r'[,;"\s()\[\]{}\x00-\x1f\x7f-\x9f]')


def path_break(text: str) -> str | None:
    return found.group() if (found := _PATH_BREAK.search(text)) else None


def absolute(name: str, value: str, **fields: Any) -> Path:
    """A path argument via `scry_core.judges.absolute`; MAME runs from its own scratch
    directory, so a relative path would be judged in one place and used in another."""
    return judges.absolute(name, value, **fields)


def no_such(name: str, thing: str, path: str, **fields: Any) -> NoReturn:
    """The refusal of the path argument `name` where no `thing` is, in `judges.existing_file`'s
    words."""
    raise Invalid("bad_argument", f"{name}: no {thing} at {path}", **fields)


input_file = judges.existing_file


PATH_CHARS = "no comma, semicolon, quote, whitespace, bracket or control character"


def writable_path(name: str, value: str) -> Path:
    """A file a tool will write: `judges.writable_file` holding nothing `path_break` forbids."""
    dest = judges.writable_file(name, value)
    _console_safe(name, value, dest)
    return dest


def fresh_dest(name: str, value: str) -> Path:
    dest = judges.fresh_file(name, value)
    _console_safe(name, value, dest)
    return dest


def fresh_folder(name: str, value: str) -> Path:
    dest = judges.fresh_folder(name, value)
    _console_safe(name, value, dest)
    return dest


def _console_safe(name: str, value: str, dest: Path) -> None:
    if broken := path_break(str(dest)):
        raise Invalid("bad_argument",
            f"{name}={value!r} holds {broken!r}{'' if str(dest) == value else f' (as {dest})'}: "
            f"a path here holds {PATH_CHARS}, so one rule serves every console line it may "
            "reach")


def optional_dest(dest: str) -> Path | None:
    return fresh_dest("dest", dest) if dest else None


def picture_args(scale: int = 0, dest: str = "", attach: bool = True) -> Path | None:
    """What every graphics tool judges before the machine."""
    picture.check_scale(scale)
    picture.check_attach(attach)
    return optional_dest(dest)
