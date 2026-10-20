"""The INPUTS every tool shares, each judged by one rule written once.

A value or an offset given as an integer or `0x`, a yes or no, a ref, an address argument, a
count held to a range, a closed
vocabulary, a wait, a regular expression, a path, a cpu given or not, a one-word name and an
argument that would do nothing beside the others: the judge of each rule two tools share
lives here, so a caller meets one sentence per rule whatever tool refused the call. The address
rule lives here whole, with the two readings that follow from it: the key a held ref is compared
under, and where a stored base or trigger points. It imports
nothing of this server's but the reply contract and reads no session and no server state (the
path judges ask the file system), which is what lets a tool judge its arguments before any
emulator exists.
"""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any, NoReturn, overload

from scry_core import judges, picture, prose, steps
from scry_core import vocabulary as vocab
from scry_core.reply_contract import Invalid


def check_ref(ref: object, name: str = "ref") -> None:
    """A ref is a symbol name or a linear `0x` address, and a `SEG:OFF` is neither: this
    server's map is flat, so the segmented form is refused before any table is asked, on
    every tool that takes a ref. `name` is the argument the refusal names (`trigger`, `pc`)."""
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


# A pointer's offset written without `0x`: the shared grammar reads it as hex (`+10` is 16),
# which is right for a row this server stored, always written `0x`, and wrong for a call whose
# bare decimal digits read either way. One digit, or a hex letter, reads one way only.
_BARE_OFFSET = re.compile(r"\]\s*[+-]\s*([0-9a-fA-F]+)\s*$")


def check_pointer_offset(ref: str) -> None:
    """Refuse a call's pointer offset written without `0x` when its digits read as decimal and
    as hex (`+10`); one digit, or a hex letter, reads one way."""
    m = _BARE_OFFSET.search(ref)
    if m is not None and m.group(1).isdigit() and int(m.group(1)) >= 10:
        digits = m.group(1)
        raise Invalid("bad_argument",
                      f"the offset in {ref!r} is written without `0x`, and +{digits} is "
                      f"{prose.counted(int(digits, 16), 'byte')} in hex and {digits} in decimal: "
                      f"write `0x{digits}` or `{int(digits):#x}`")


def cpu_given(cpu: str) -> bool:
    """Whether a call named a cpu: whitespace alone names none, in every tool that takes one."""
    return bool(cpu.strip())


def name_word(name: str, value: object, what: str) -> None:
    """A name a caller gives (a device tag, an entry of the manifest): given, one word with no
    whitespace, since the line a script prints it on is read by words; else the refusal naming
    `name` and `what` it names."""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise Invalid("bad_argument", f"{name}={value!r}: {what}, one word with no whitespace")


def idle(name: str, goes_with: str, why: str) -> NoReturn:
    """The refusal of an argument that would do nothing beside the ones given: refused, never
    dropped, so a caller who meant it learns it was not read."""
    raise Invalid("bad_argument", f"`{name}` goes with `{goes_with}`: {why}")


def check_bool(name: str, value: object) -> None:
    """An argument that is a yes or a no, in one sentence for every tool that takes one."""
    if not isinstance(value, bool):
        raise Invalid("bad_argument", f"{name} is a boolean; got {value!r}")


def _count(value: object) -> bool:
    """A count as JSON carries it: an integer, never a bool (which Python counts as one). An
    INTEGRAL float is a count, because a client's schema makes `6.0` the int `6` before the tool
    sees it, and the same call judged here has to come out the same; a fractional one counts
    nothing, and neither does `nan` or an infinity, none of which is integral. Every judge of a
    count asks this first."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def integral_counts(value: object, annotation: str) -> object:
    """`value` with an integral float made the int it equals wherever `annotation` (a tool
    parameter's, as a string) declares a count: `int`, or a list of them, with or without
    `| None`, a schema half included (`unannotated`), at any depth of lists. The judges take
    `6.0` as the count 6 (`_count`), and this is what makes every body behind them receive the
    int, so a `range()` or a `%x` downstream never meets a float."""
    parts = sorted(p.strip() for p in steps.unannotated(annotation).split("|"))
    kind = next((p for p in parts if p != "None"), "") if len(parts) <= 2 else ""

    def convert(v: object, kind: str) -> object:
        if kind == "int":
            return int(v) if isinstance(v, float) and v.is_integer() else v
        if kind.startswith("list[") and kind.endswith("]") and isinstance(v, list):
            return [convert(x, kind[5:-1]) for x in v]
        return v
    return convert(value, kind)


def is_natural(value: object, lo: int = 0, hi: int | None = None) -> bool:
    """`value` is a count (`_count`) within `lo..hi`."""
    return _count(value) and value >= lo and (hi is None or value <= hi)  # type: ignore[operator]


def is_naturals(value: object, n: int | None = None, lo: int = 0) -> bool:
    """`value` is a list of `n` naturals at or above `lo` (any length when `n` is None): a point,
    a rectangle's corner, a list of pens. The list is asked for before its length, so a
    number or a string is refused here rather than raising in `len()`."""
    return (isinstance(value, list | tuple) and (n is None or len(value) == n)
            and all(is_natural(v, lo) for v in value))


def natural(name: str, value: object, what: str, lo: int = 0, hi: int | None = None) -> None:
    """Refuse `value` unless `is_natural`, as `<name>=<value!r><what>`: the guard written once,
    the sentence its caller's, so each refusal still says what the number counts."""
    if not is_natural(value, lo, hi):
        raise Invalid("bad_argument", f"{name}={value!r}{what}")


def is_rectangle(value: object) -> bool:
    """`value` is `[x, y, width, height]`: four naturals, the width and the height above zero."""
    return (is_naturals(value, 4) and is_naturals(value[:2], 2)  # type: ignore[index]
            and is_naturals(value[2:], 2, 1))  # type: ignore[index]


#: Hex digits with or without `0x`: how an OLDER store or file may spell an address, read back
#: by the rows that predate the rule; a call's address is `ADDRESS`.
HEX_ADDR = re.compile(r"(?:0[xX])?[0-9a-fA-F]+")


def hex_arg(name: str, value: str) -> int:
    """An address argument, written `0x` like every address, or a refusal that names the
    ARGUMENT and not just the text.

    `int(value, 16)` alone accepts a sign and underscores, so `-400` would read as a negative
    base and `4_00` as 0x400, both in silence; and its own error names neither the parameter
    nor the shape wanted. Bare hex is refused with its `0x` spelling, as a bare ref is. Every
    address argument a tool takes goes through here.
    """
    text = value.strip()
    if ADDRESS.fullmatch(text):
        return int(text, 16)
    if _BARE_HEX.fullmatch(text):
        raise Invalid("bad_argument", f"{name} is {value!r}; an address is written 0x{text}")
    raise Invalid("bad_argument", f"{name} is {value!r}, which is not an address like `0x400`")


#: The annotation of a value, a byte offset or a pen base: a JSON integer or a `0x` string, so
#: the schema a client reads offers both and `number_arg` decides (REFERENCE.md, *Names for
#: addresses*, says why).
NumberArg = judges.NumberArg

#: The widest number MAME's debugger holds: its expressions are 64-bit.
NUMBER_BITS = 64


def number_arg(name: str, value: object) -> int:
    """`value` as the integer it is or spells (`scry_core.judges.number`, the one grammar both
    servers hold), at most `NUMBER_BITS` wide."""
    return judges.number(name, value, NUMBER_BITS, "MAME's debugger")


#: A list of numbers, each a `NumberArg` (a list of pens).
NumberList = list[NumberArg]


def pen(name: str, value: object) -> None:
    """The one judge of a pen number, read already by `number_arg` (an integer or `0x`): every
    pen argument (`pen_base`, `palette`'s `first`, `palette_log`'s `pen`, each of `screen_view`'s
    `pens`) is refused in one sentence."""
    natural(name, value, " is not a pen number")


@functools.cache
def number_lists(fn: Callable[..., Any]) -> frozenset[str]:
    """The arguments `fn` declares a `NumberList`, optional or not."""
    return frozenset(name for name, p in inspect.signature(fn, eval_str=True).parameters.items()
                     if p.annotation in (NumberList, NumberList | None))


@functools.cache
def number_params(fn: Callable[..., Any]) -> dict[str, bool]:
    """The arguments `fn` declares `NumberArg`, each with whether it is optional (`| None`)."""
    return {name: p.annotation != NumberArg
            for name, p in inspect.signature(fn, eval_str=True).parameters.items()
            if p.annotation in (NumberArg, NumberArg | None)}


@overload
def as_read(value: NumberArg) -> int: ...
@overload
def as_read(value: NumberArg | None) -> int | None: ...
def as_read(value: NumberArg | None) -> int | None:
    """A `NumberArg` the server's `tool()` wrapper has already read (`numbers_read`), as the int it
    now is: the conversion is the wrapper's, once; this only tells the type checker so."""
    assert value is None or isinstance(value, int), value
    return value


def list_as_read(values: NumberList | None) -> list[int] | None:
    """`as_read` for a `NumberList` the wrapper has read item by item; a value that is no
    list at all reaches the tool's judge as it came, and that judge refuses it."""
    return values  # type: ignore[return-value]


def numbers_read(fn: Callable[..., Any], args: dict[str, Any]) -> dict[str, Any]:
    """`args` with each number `fn` declares read by `number_arg` (each item of a `NumberList`
    too), `None` left only where the number is optional: what the server's `tool()` wrapper
    hands every body, and what a judge asked about a call without making it (a batch step, the
    probe) sees the same way."""
    declared, lists = number_params(fn), number_lists(fn)
    return {name: (number_arg(name, value)
                   if name in declared and (value is not None or not declared[name]) else
                   [number_arg(f"{name}[{i}]", v) for i, v in enumerate(value)]
                   if name in lists and isinstance(value, list) else value)
            for name, value in args.items()}


# ------------------------------------------------------------------ what a ref names

# AN ADDRESS IS WRITTEN `0x`, AND NOTHING ELSE IS ONE. A bare hex string is also a plausible
# name (`adc`, `fade`, `beef` are all valid hex AND symbols of real builds), and a rule that let
# the table decide would read the same text as a symbol on one build and an address on the next,
# so a delete by the name `adc` could reach the comment at 0xadc. So the spelling decides, never
# the table: `0x...` is an address, anything else a symbol, and bare hex that names no symbol is
# refused with the `0x` spelling it most likely meant, never guessed.
ADDRESS = re.compile(r"0[xX][0-9a-fA-F]+")
_BARE_HEX = re.compile(r"[0-9a-fA-F]+")


class BareHex(Invalid):
    """The refusal of bare hex that names no symbol: its own type, so a tool that words an
    unresolved name its own way (a `control`, a trigger) still lets this one through whole."""


def given(text: object) -> bool:
    """Whether an optional ref was given: anything but empty or whitespace text, so a ref of the
    wrong type reaches `check_ref`'s refusal rather than failing on `.strip()`."""
    return not isinstance(text, str) or bool(text.strip())


def zero_x(ref: str, name: str = "ref") -> None:
    """Refuse text that starts like an address and is not one (`0x` alone, or before anything but
    hex): no symbol may start with `0x`, so it cannot be a name either. `name` is the argument
    the refusal names (`trigger`, `pc`, a pointer's `base`)."""
    text = ref.strip()
    if text[:2].lower() == "0x" and not ADDRESS.fullmatch(text):
        raise Invalid("bad_argument", f"{name}={ref!r} starts like an address and is not one: "
                                      "`0x` is followed by hex digits")


def by_spelling(by: str, ref: str) -> str | None:
    """Why `ref` contradicts the `by` it was declared with, or None: by address it is written
    `0x`, and by symbol it never is."""
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
    """Whether `text` is written as an address: `0x` and hex digits, and nothing else."""
    return ADDRESS.fullmatch(text.strip()) is not None


def bare_hex(ref: str, cpu: str | None, loaded: int) -> BareHex:
    """The refusal of `ref`, bare hex naming no symbol of `cpu`'s table, with the spelling that
    would make it an address."""
    text = ref.strip()
    whose = f"{cpu}'s" if cpu else "the machine's"
    return BareHex("unknown_ref", f"{text!r} names no symbol of {whose} table ({loaded} loaded); "
                                  f"an address is written 0x{text}")


def not_a_ref(what: str, text: str, cpu: str | None = None, *, loaded: int | None = None,
              then: str = "") -> str:
    """The one sentence for a ref that names no symbol of `cpu`'s table (the build's one table
    when None) and is no `0x` address: `what` names the argument (`the trigger`), `then` what
    that left undone, and the sentence ends on the lookup that settles it, on that same table."""
    table = f"{cpu}'s table" if cpu else "this build's table"
    count = "" if loaded is None else f" ({prose.counted(loaded, 'symbol')} loaded)"
    lookup = f'symbols_find(name=..., cpu="{cpu}")' if cpu else "symbols_find(name=...)"
    return (f"{what} {text!r} is neither a symbol of {table}{count} nor a `0x` address{then}: "
            f"`{lookup}` says whether the table has one")


def classify(ref: str, names: Collection[str], cpu: str | None,
             held: Collection[str] = ()) -> str:
    """`"address"` or `"symbol"` for a ref a CALL typed, read once against `names` (the table's,
    upper-case) and `held` (the stored refs a call may name back, which stay reachable by the
    name they were stored under); bare hex in neither is refused (`bare_hex`). A ref read from a
    file or the store is never judged here: there the shape it was written in stands."""
    text = ref.strip()
    if ADDRESS.fullmatch(text):
        return "address"
    key = text.upper()
    if (_BARE_HEX.fullmatch(text) and key not in names
            and key not in {h.strip().upper() for h in held}):
        raise bare_hex(text, cpu, len(names))
    return "symbol"


#: A number in the console's grammar, where a bare number is hex: `0x` or `$` and hex digits,
#: `#` and decimal ones, `0o` octal, `0b` binary (a `0b` token with other digits falls back to
#: hex, as the console's does), or a token that starts with a digit; never a run of letters
#: (`ab`), which may name a symbol. A `$` or `#` inside a token is part of a name, as the console
#: reads it. A `#` run longer than a u64's 20 decimal digits is left as typed rather than read.
_CONSOLE_NUMBER = re.compile(
    r"(?<![\w.$#:])(?:0[xX](?P<hex>[0-9a-fA-F]+)|\$(?P<dollar>[0-9a-fA-F]+)"
    r"|#(?P<dec>[0-9]{1,20})|0[oO](?P<oct>[0-7]+)(?![\w])|0[bB](?P<bin>[01]+)(?![\w])"
    r"|(?P<bare>[0-9][0-9a-fA-F]*))(?![\w])")
#: Each prefix's group in `_CONSOLE_NUMBER` and the base the console reads its digits in.
_BASES = (("dec", 10), ("oct", 8), ("bin", 2), ("hex", 16), ("dollar", 16), ("bare", 16))


def _console_value(m: re.Match[str]) -> int:
    """The value the console reads a `_CONSOLE_NUMBER` match as."""
    return next(int(m[group], base) for group, base in _BASES if m[group] is not None)


def match_key(ref: str, by: str) -> str:
    """The spelling two refs of one kind are COMPARED under: an address canonical (`0x`, lower
    case, unpadded), a symbol upper-case as the tables are keyed, an expression with each number
    read as the console reads it (`_CONSOLE_NUMBER`), anything else stripped. What is stored
    stays as the caller typed it; only the comparison folds."""
    text = ref.strip()
    if by == "address" and HEX_ADDR.fullmatch(text):
        return f"0x{int(text, 16):x}"
    if by == "symbol":
        return text.upper()
    if by == "expr":
        return _CONSOLE_NUMBER.sub(lambda m: f"0x{_console_value(m):x}", text)
    return text


def place_key(text: str) -> str:
    """The key a place is compared under when its kind is read from its spelling (a capture's
    trigger, a pointer's base): `0x` an address, anything else a name."""
    return match_key(text, "address" if is_address(text) else "symbol")


def stored_place(text: str, table: Mapping[str, int]) -> int | None:
    """Where a place read from the store (a capture's trigger, a pointer's base) points against
    `table`: a `0x` address, else a name of the table in any case, else None. What carries no
    `0x` is a name, as in a call, so one a rebuild dropped points nowhere, never at the address
    its letters would spell."""
    key = text.strip()
    if is_address(key):
        return int(key, 16)
    return table.get(key.upper())


def count(name: str, value: int, hi: int | None = None, tail: str = "", lo: int = 1) -> None:
    """The one judge of a count a caller gave, held to `lo`..`hi` (no ceiling when `hi` is None),
    in the same sentences for every count: one for a value that is not a count at all, one for a
    count outside its range, and one for a count below a floor with no ceiling. `tail` is the one
    thing a caller adds: why the bound is where it is, or what to do instead. The floor is 1 for
    a count of something to do, and 0 only where none is an answer of its own."""
    if not _count(value):
        raise Invalid("bad_argument", f"{name} is a count; got {value!r}")
    if hi is not None and not lo <= value <= hi:
        raise Invalid("bad_argument", f"{name}={value!r} is outside {lo}..{hi}{tail}")
    if value < lo:
        raise Invalid("bad_argument", f"{name}={value!r} is below {lo}{tail}")


# THE CEILING ON EVERY WAIT a tool takes: the server answers one call at a time, so a wait with
# no ceiling would hold every other call behind an answer that may never arrive.
WAIT_MAX_S = 600.0
#: A wait's schema half, `Annotated[float, WAIT_BOUNDS]`, as `seconds_bound` judges it: above 0
#: and at most `WAIT_MAX_S`; `WAIT_OR_NONE_BOUNDS` for the two whose 0 means no wait at all.
WAIT_BOUNDS = vocab.bounds(0, WAIT_MAX_S, open_lo=True)
WAIT_OR_NONE_BOUNDS = vocab.bounds(0, WAIT_MAX_S)


# WHAT A PATH HANDED TO THE CONSOLE, OR WRITTEN AS A `dest`, MAY NOT HOLD. The console's command
# line (`debugcon.cpp`) splits the parameters at a comma, ends the command at a semicolon outside
# brackets, opens a string at a quote, refuses the whole line on a bracket left open or closed
# alone, and trims spaces at a parameter's ends. This rule is stricter on purpose (a `;` or a
# bracket anywhere, balanced or not, and whitespace anywhere), so the rule a caller learns is
# one set of characters, not the console's parser. The control characters (Unicode's `Cc`, the
# two ranges below) go with them, because whatever reads the path back, a terminal or a log,
# acts on one; a joiner or a name in another script is a name and stays allowed.
_PATH_BREAK = re.compile(r'[,;"\s()\[\]{}\x00-\x1f\x7f-\x9f]')


def path_break(text: str) -> str | None:
    """The first character of `text` the rule above forbids, or None."""
    return found.group() if (found := _PATH_BREAK.search(text)) else None


def absolute(name: str, value: str, **fields: Any) -> Path:
    """THE ONE JUDGE OF A PATH ARGUMENT is scry-core's (`scry_core.judges.absolute`), shared with
    the other server and the media file tools: absolute or `~`-led, `~` expanded, not empty, no
    NUL and no lone surrogate, or refused naming `name`; `fields` ride on the refusal. A caller
    whose argument is optional asks only when it was given, since `""` means "not given". THE
    SERVER RUNS MAME FROM A SCRATCH DIRECTORY OF ITS OWN, which is why a relative path is refused:
    it would be judged in one directory and used in another. A path that reaches a console line
    is judged there too (`path_break`)."""
    return judges.absolute(name, value, **fields)


def no_such(thing: str, path: str, **fields: Any) -> NoReturn:
    """The refusal of an input that is not there, in ONE sentence for every argument that
    names one: a sentence written once per argument is on its way to being one slightly
    different sentence per argument, which is what a caller grepping a refusal finds out the
    hard way. The path reaching it has passed `absolute`. WHAT STAYS WITH THE CALLER IS THE
    CHECK: which input may be a directory, which has to be executable, is its own business."""
    raise Invalid("bad_argument", f"no such {thing}: {path}", **fields)


def input_file(name: str, value: str, thing: str, **fields: Any) -> Path:
    """An input FILE argument: `absolute`, then a file, or `no_such` naming it as `thing`.
    `is_file()` and never `exists()`, which answers yes to a directory carrying the name."""
    path = absolute(name, value, **fields)
    if not path.is_file():
        no_such(thing, str(path), **fields)
    return path


#: What a path a tool writes may not hold, in the words its refusal and every description use.
PATH_CHARS = "no comma, semicolon, quote, whitespace, bracket or control character"


def writable_path(name: str, value: str) -> Path:
    """A file a tool is about to WRITE, judged before any console: scry-core's
    `judges.writable_file` (absolute or `~`-led, in a directory that exists), and holding nothing
    `path_break` forbids once expanded, since the expanded text is what a console line carries.

    `path_break` holds for every `dest`, whether or not the tool's path reaches the console
    (`memdump`'s does, as `save`'s parameter), so a caller learns one contract for a file a tool
    writes rather than one per tool."""
    dest = judges.writable_file(name, value)
    _console_safe(name, value, dest)
    return dest


def fresh_dest(name: str, value: str) -> Path:
    """`writable_path`, and not there yet (`judges.fresh_file`): a refusal after the console
    wrote the file would leave one nobody asked for, and an accepted call would overwrite
    somebody's."""
    dest = judges.fresh_file(name, value)
    _console_safe(name, value, dest)
    return dest


def _console_safe(name: str, value: str, dest: Path) -> None:
    if broken := path_break(str(dest)):
        raise Invalid("bad_argument",
            f"{name}={value!r} holds {broken!r}{'' if str(dest) == value else f' (as {dest})'}: "
            f"a path here holds {PATH_CHARS}, so one rule serves every console line it may "
            "reach")


def optional_dest(dest: str) -> Path | None:
    """A tool's `dest`, `fresh_dest`'s, or None when it is empty: the file then lands in the
    scratch under a name the tool chooses."""
    return fresh_dest("dest", dest) if dest else None


def picture_args(scale: int = 0, dest: str = "", attach: bool = True) -> Path | None:
    """What every graphics tool judges before the machine: the scale (`scry_core.picture`'s
    range), whether to attach the picture (a view's), and a `dest` that is a fresh absolute path,
    handed back as the `Path` it built."""
    picture.check_scale(scale)
    picture.check_attach(attach)
    return optional_dest(dest)


def regex(name: str, pattern: object) -> re.Pattern[str]:
    """A regular expression a caller gave, compiled, or the refusal naming `name`: one judge for
    every tool that takes one. Empty is refused, never "every line": a pattern left empty by
    mistake would hand back the whole log; `.` is every line, written."""
    if not isinstance(pattern, str):
        raise Invalid("bad_argument", f"{name} is a regular expression; got {pattern!r}")
    if not pattern:
        raise Invalid("bad_argument", f"{name} is a non-empty regular expression ('.' for every "
                      "line)")
    try:
        return re.compile(pattern)
    except re.error as e:
        raise Invalid("bad_argument", f"{name}={pattern!r} does not compile: {e}") from None


def seconds_bound(value: object, name: str = "seconds", zero_means: str = "") -> None:
    """A WAIT, a number (never a bool) held to more than zero and at most `WAIT_MAX_S`: one sentence
    for every wait this server takes, naming the argument `name`. Every value a JSON client can
    send that it refuses fails that sentence (a `Fraction` would not, and no client can send
    one), so it names the type before the range: a bool is an `int` to Python, and
    `True` sits inside the range. Where zero is a wait of its own kind, `zero_means` says
    which, and zero is then taken."""
    if not (isinstance(value, int | float) and not isinstance(value, bool)
            and (value >= 0 if zero_means else value > 0) and value <= WAIT_MAX_S):
        floor = f"0 ({zero_means}) or more than zero" if zero_means else "more than zero"
        raise Invalid("bad_argument", f"{name}={value!r} is not a bound: a number of seconds, "
                                         f"never a bool, {floor} and at most {WAIT_MAX_S}")
