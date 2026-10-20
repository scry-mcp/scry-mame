"""Debugging DECLARATIONS: the intent behind a breakpoint, a watch or a registerpoint, declared BY
NAME.

The debugger holds the ARMED instances; this holds what the caller MEANT: a breakpoint or a
watch at a SYMBOL or at a raw ADDRESS, or a registerpoint's condition with its symbols by name.
Keeping the intent is what makes a rebuild free: an address moves when the program is
relinked, a name does not, so a declaration by name re-resolves against the new table and
re-arms itself, and one whose name has VANISHED is KEPT, unresolved and said out loud, never
dropped in silence.

A resolution here is a lookup in the flat table `start` loaded for the declaration's cpu
(`name -> address`): the linker's map and the per-class bases already solve the moving half,
so nothing is measured at load time.

WHAT IT DOES NOT DO: talk to the debugger. Arming is `mame_arming`'s.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scry_core import fresh
from scry_core import value_format as vf
from scry_core.reply_contract import unavailable

import mame_comment_file as cf
import mame_inputs as inputs

# The kinds that stop or watch, and the comment. MAME has no interrupt breakpoint to declare:
# an arcade board's vectors are addresses like any other, and a breakpoint on one is a
# breakpoint. A REGPOINT (the kind's name in the store; the debugger calls it a registerpoint) is
# a stop when a condition over the registers comes true wherever that happens: it has no address,
# so its `ref` IS the condition, as typed. A COMMENT is a text at a place, by symbol or by
# address, which neither stops nor watches: it is held here so it follows its symbol through a
# rebuild like the others, and MAME's own disassembly is fed from it (`mame_comments`).
COUNTED_KINDS = ("breakpoint", "watch", "regpoint")
KINDS = (*COUNTED_KINDS, "comment")
#: Each kind that stops or watches, by its name as a count of it in a reply.
COUNT_KEYS = dict(zip(COUNTED_KINDS, ("breakpoints", "watches", "regpoints"), strict=True))


def no_counts() -> dict[str, int]:
    """A cpu's count of each kind, before any is counted."""
    return dict.fromkeys(COUNT_KEYS.values(), 0)
# A declaration is BY a symbol name, BY a raw address, or BY an EXPRESSION: the third is a
# watch of mode `expr`, an expression the MAME debugger evaluates (`beamy`, `totalcycles`,
# `a0+4`), which resolves against no table and arms nothing, or a registerpoint, whose condition
# is one.
# And BY A POINTER: a watch whose place is reached THROUGH a pointer held at a global, the
# grammar being `[base]`, `[base]+0x28`, `[base]-0x4` or `base->field`, with `base` a symbol
# or a raw address. The address is resolved when the watch is armed and AGAIN at every stop,
# because the pointer can move; a breakpoint is never declared this way (code does not move
# behind a pointer, and a stop at a moving address is one nobody can attribute).
BY = ("symbol", "address", "expr", "pointer")
# A breakpoint has a ROLE. A `stop` halts the machine, which is what a breakpoint is for. A
# `control` never does: it is the debugger's own conditioned breakpoint whose condition counts
# and never comes true (`bp <addr>,(++tempN)==0`), so it proves a run reached something hot
# without costing a stop. `run_to` reads the controls' counts around every run, and a target's
# silence is a measurement only when a control counted.
ROLES = ("stop", "control")
# A watch has TWO halves: SHOW evaluates the bytes at every stop and arms nothing;
# BREAK-ON-CHANGE arms a write watchpoint in the debugger. One ref may not be both (see
# `DeclarationStore.add`), and that is kept here although MAME arms no trap byte, measured:
# the rule is the store's, and a store rule that holds on one server only is one nobody can
# rely on. COUNT is the third thing a datum can be asked: a write tap (`mame_tally`) that
# counts every write over a pass by value and by writer and never stops for one, the
# datum's twin of a control breakpoint. CAPTURE is the same tap on a TRIGGER, recording the
# whole block at each write to it (`mame_capture`): the joint question a count cannot answer.
# `show` was spelled `read` until "read" was left to name an access only (`trigger_type="r"`):
# a stored row still carrying the old word is read as the new one (`Declaration.from_dict`).
WATCH_MODES = ("show", "change", "expr", "count", "capture")
RETIRED_MODES = {"read": "show"}
# The modes whose watch is a Lua write tap rather than a debugger row: one list, so a mode added
# to the family is added once.
TAP_MODES = ("count", "capture")
# Which access to a capture's trigger makes a row, `wpset`'s own words: `w` a write, `r` a read.
TRIGGER_TYPES = ("w", "r")
# A watch is BYTES AT A NAME read as a FORMAT: a scalar (N of them, `width` bytes), an
# array (`u16[8]`), a string (`char[16]`) or a struct (`{x:i16,y:i16}`), the grammar of
# `value_format`. The values render in the TARGET's byte
# order, which the session knows and this module does not.
FORMATS = tuple(vf.SCALARS)
FORMAT_WIDTH = {name: size for name, (_code, size) in vf.SCALARS.items()}


#: A declaration's identity where its ref alone is not one: the same ref declared on two cpus
#: is two declarations, so every record of what this server armed is keyed by (ref, cpu).
Owner = tuple[str, str | None]


def owner_fields(owner: Owner) -> dict[str, Any]:
    """An owner as a reply names it: its `ref` and its `cpu`, unavailable when none was read."""
    return {"ref": owner[0], "cpu": owner[1] if owner[1] is not None else
            unavailable("no cpu was read for it: the visible cpu was unknown")}


def fmt_for_width(width: int) -> str:
    """The default `fmt` for a width the caller did not name a format for: the widest
    UNSIGNED integer the width is a whole number of. A width divisible by four is read as
    u32 values, an even one as u16, anything else as u8. Signed or float is a caller's
    choice and is never a default."""
    if width % 4 == 0:
        return "u32"
    if width % 2 == 0:
        return "u16"
    return "u8"

# A STORE FILE THAT CANNOT BE READ IS NEVER DISCARDED: what it holds is somebody's intent.
UNTIL_FIXED = "until the file is fixed or removed by hand; it is never discarded"
# Why a session started with no symbol file holds its declarations in memory alone.
SESSION_LIVED_WHY = ("no `symbols` file was given, so nothing can be re-resolved by name: "
                     "declarations are by address and die with this session")


class DeclarationError(Exception):
    """A declaration that cannot be held: malformed, or in conflict with one already held.
    Its own type so the server can turn it into a refusal that names what was wrong."""


@dataclass(frozen=True)
class Declaration:
    """One thing a caller wants armed, BY a symbol name or BY a raw `0x` address.

    The watch fields belong to `kind == "watch"` only and are refused on a breakpoint, so an
    ill-formed declaration cannot be constructed. `created_at` and `origin` (which session
    made or last adopted it) stay OUT of equality: re-declaring the same thing from a new
    session is the same declaration, adopted, and not a second one.
    """

    kind: str
    by: str
    ref: str
    width: int | None = field(default=None, kw_only=True)
    fmt: str | None = field(default=None, kw_only=True)
    watch_mode: str | None = field(default=None, kw_only=True)
    role: str = field(default="stop", kw_only=True)
    # A CONDITION IN THE CONSOLE'S OWN GRAMMAR (`w@0x2031fc==0x25`), on a stop breakpoint or a
    # change watch (where `wpdata` is the value being written): the console evaluates it at
    # every hit and halts when it holds. Part of equality, since the same address under another
    # condition is another declaration.
    condition: str = field(default="", kw_only=True)
    # A CAPTURE'S TRIGGER, a symbol as typed or a `0x` address: the write that makes a row. Part
    # of equality, since the same block on another trigger is another capture.
    trigger: str = field(default="", kw_only=True)
    # WHICH ACCESS TO THE TRIGGER makes a row, in `wpset`'s words: `w` a write, `r` a read. Part
    # of equality, since a capture of the reads is another capture than one of the writes.
    trigger_type: str = field(default="w", kw_only=True)
    created_at: str | None = field(default=None, kw_only=True, compare=False)
    origin: str | None = field(default=None, kw_only=True, compare=False)
    # THE BUILD IT WAS DECLARED AGAINST: the fingerprint of the system, the ROM image and
    # the symbol file (`mame_launch.fingerprint`). A raw address is re-armed only over the
    # same fingerprint; a name re-resolves whatever the fingerprint. Out of equality like
    # the stamps: the same thing declared against a new build is adopted, not doubled.
    fingerprint: str | None = field(default=None, kw_only=True, compare=False)
    # THE CPU IT IS DECLARED ON, part of equality: each cpu runs its own program, so the same
    # ref on two cpus is two declarations. An expr watch carries none, since the console
    # evaluates it on whichever cpu is visible. A row the store read without one (written
    # before a declaration had a cpu) is the first cpu's (`DeclarationStore.bind_first_cpu`).
    cpu: str | None = field(default=None, kw_only=True)
    # A COMMENT'S TEXT, and only a comment's. Out of equality: a comment is the place it names,
    # so the same place under a new text is the same declaration with its text replaced.
    text: str = field(default="", kw_only=True, compare=False)

    @property
    def owner(self) -> Owner:
        """What every record of this declaration's row, tap or counter is keyed by."""
        return self.ref, self.cpu

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise DeclarationError(f"kind is one of {KINDS}; got {self.kind!r}: the kind is the "
                                   "tool's, `breakpoint_at`, `watch_add`, `regpoint_add` or "
                                   "`comment_add`")
        if self.by not in BY:
            raise DeclarationError(f"`by` is one of {BY}; got {self.by!r}: `breakpoint_at(by=...)` "
                                   "and `watch_add(by=...)` take it")
        if not self.ref.strip():
            raise DeclarationError("a declaration needs a ref, a symbol name or a `0x` address: "
                                   "`breakpoint_at(ref=...)`, `watch_add(ref=...)`")
        if (self.kind == "comment") != bool(self.text):
            raise DeclarationError(
                "a comment, and only a comment, carries a text; got "
                f"text={self.text!r} on a {self.kind}: `comment_add(ref=..., text=...)`")
        if self.kind == "comment" and self.by not in ("symbol", "address"):
            raise DeclarationError(
                f"a comment is at a symbol or at an address; got by={self.by!r}: a place "
                "reached through a pointer or an expression moves at run time, and "
                "`comment_add(ref=...)` takes a symbol or a `0x` address")
        if (why := inputs.by_spelling(self.by, self.ref)) is not None:
            raise DeclarationError(why)
        if self.by == "expr" and self.kind not in ("watch", "regpoint"):
            raise DeclarationError(
                f"only a watch or a registerpoint is declared by expr; got a {self.kind}: "
                "`breakpoint_at` takes `by` symbol, address or auto")
        if self.kind == "regpoint" and self.by != "expr":
            raise DeclarationError(
                f"a registerpoint is declared by expr, its condition; got by={self.by!r}: "
                "`regpoint_add(condition=...)` declares one")
        if self.by == "pointer":
            if self.kind != "watch":
                raise DeclarationError(
                    f"a {self.kind} is not declared through a pointer: a breakpoint is at "
                    "code, and a stop at an address that moves is one nobody can attribute; "
                    "`watch_add(ref=\"[base]+0x..\")` is where a pointer goes")
            if vf.parse_pointer(self.ref) is None:
                raise DeclarationError(
                    f"{self.ref!r} is not a pointer ref: `[base]`, `[base]+0x28`, "
                    "`[base]-0x4` or `base->field`, with `base` a symbol or a `0x` address, "
                    "is what `watch_add(by=\"pointer\")` takes")
        if self.kind != "watch":
            extras = {k: v for k, v in (("width", self.width), ("fmt", self.fmt),
                                        ("watch_mode", self.watch_mode)) if v is not None}
            if extras:
                raise DeclarationError(f"a {self.kind} carries no watch fields; got {extras}: "
                                       "`watch_add` takes them")
            if self.kind == "comment":
                if self.role != "stop" or self.condition or self.trigger:
                    raise DeclarationError(
                        "a comment carries no role, condition or trigger; got "
                        f"role={self.role!r} condition={self.condition!r} "
                        f"trigger={self.trigger!r}: `comment_add(ref=..., text=...)` alone")
                # THE FILE'S RULES, held where a comment is held: a store edited by hand cannot
                # carry a comment the comment file could not write.
                if (fault := cf.ref_fault(self.ref)) is not None:
                    raise DeclarationError(f"a comment's ref {self.ref!r} {fault}: "
                                           "`comment_add(ref=...)` takes a symbol or an address")
                if (fault := cf.text_fault(self.text)) is not None:
                    raise DeclarationError(f"a comment's text {fault}: "
                                           "`comment_add(text=...)` takes one line")
                return
            if self.kind == "regpoint":
                if self.role != "stop" or self.condition:
                    raise DeclarationError(
                        "a registerpoint's ref IS its condition and it always stops: it carries no "
                        f"role and no condition field; got role={self.role!r} "
                        f"condition={self.condition!r}; `regpoint_add(condition=...)` alone")
                return
            if self.role not in ROLES:
                raise DeclarationError(f"a breakpoint's role is one of {ROLES}; got {self.role!r}: "
                                       "`breakpoint_at(role=...)`")
            if self.condition and self.role != "stop":
                raise DeclarationError("a control counts every hit and carries no condition; "
                                       f"got condition={self.condition!r} on a control: "
                                       "`breakpoint_at(role=\"stop\", condition=...)` stops")
            return
        if self.role != "stop":
            raise DeclarationError(f"a watch carries no role; got role={self.role!r}: `role` "
                                   "belongs to `breakpoint_at`")
        if self.watch_mode not in WATCH_MODES:
            raise DeclarationError(
                f"a watch needs a mode, one of {WATCH_MODES}; got {self.watch_mode!r}: "
                "`watch_add(mode=...)`")
        if self.condition and self.watch_mode != "change":
            raise DeclarationError(
                f"only a change watch carries a condition; got {self.condition!r} on a "
                f"{self.watch_mode} watch: `watch_add(mode=\"change\", condition=...)`")
        if bool(self.trigger.strip()) != (self.watch_mode == "capture"):
            raise DeclarationError(
                f"a capture watch, and only it, carries a trigger; got trigger="
                f"{self.trigger!r} on a {self.watch_mode} watch: "
                "`watch_add(mode=\"capture\", trigger=...)`")
        if self.trigger_type not in TRIGGER_TYPES or (
                self.trigger_type != "w" and self.watch_mode != "capture"):
            raise DeclarationError(
                f"a trigger type is one of {TRIGGER_TYPES}, and only a capture takes one other "
                f"than `w`; got trigger_type={self.trigger_type!r} on a {self.watch_mode} watch: "
                "`watch_add(mode=\"capture\", trigger_type=...)`")
        if (self.watch_mode == "expr") != (self.by == "expr"):
            raise DeclarationError(
                "a watch of mode expr is declared by expr and nothing else is: got "
                f"mode={self.watch_mode!r} by={self.by!r}; `watch_add(mode=\"expr\")` with "
                "`by` left at auto")
        if self.watch_mode == "expr":
            if self.cpu is not None:
                raise DeclarationError(
                    f"an expr watch carries no cpu; got {self.cpu!r}: the console evaluates it "
                    "on the visible cpu, which `focus` moves")
            if self.width is not None or self.fmt is not None:
                raise DeclarationError(
                    f"an expr watch carries no length and no format; got length={self.width!r} "
                    f"fmt={self.fmt!r}: the debugger evaluates the expression to one number, so "
                    "`watch_add(ref=<expression>, mode=\"expr\")` alone")
            return
        if self.fmt is None:
            raise DeclarationError(f"a watch needs a format, one of {FORMATS}, an array like "
                                   "u16[8], a string like char[16] or a struct; got None: "
                                   "`watch_add(fmt=...)` or `watch_add(length=...)`")
        try:
            width = vf.parse(self.fmt).width_for(self.width or 0)
        except vf.FormatError as e:
            raise DeclarationError(str(e)) from None
        # A SIZED FORMAT NAMES ITS OWN WIDTH: the declaration carries it so every reader
        # of `width` (the watchpoint's length, the read) sees one number.
        object.__setattr__(self, "width", width)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"kind": self.kind, "by": self.by, "ref": self.ref}
        if self.kind == "watch":
            d.update(width=self.width, fmt=self.fmt, watch_mode=self.watch_mode)
        elif self.role != "stop":
            d["role"] = self.role
        if self.condition:
            d["condition"] = self.condition
        if self.trigger:
            d["trigger"] = self.trigger
        if self.trigger_type != "w":
            d["trigger_type"] = self.trigger_type
        if self.text:
            d["text"] = self.text
        for key in ("created_at", "origin", "fingerprint", "cpu"):
            if getattr(self, key) is not None:
                d[key] = getattr(self, key)
        return d

    def adopted_by(self, origin: str | None, created_at: str | None,
                   fingerprint: str | None = None) -> Declaration:
        """The same declaration under a new origin, stamp and build; a half not carried
        (None) keeps what was held."""
        return Declaration(self.kind, self.by, self.ref, width=self.width, fmt=self.fmt,
                           watch_mode=self.watch_mode, role=self.role,
                           condition=self.condition, trigger=self.trigger,
                           trigger_type=self.trigger_type, created_at=created_at, origin=origin,
                           fingerprint=self.fingerprint if fingerprint is None else fingerprint,
                           cpu=self.cpu, text=self.text)

    @staticmethod
    def from_dict(d: dict[str, object]) -> Declaration:
        """Rebuild a declaration from a stored object, refusing corruption as a
        `DeclarationError`: a hand-edited or truncated file must come back as a NAMED
        refusal, because the store reads it at `start`."""
        width = d.get("width")
        if width is not None:
            try:
                width = int(width)  # type: ignore[call-overload]
            except (TypeError, ValueError):
                raise DeclarationError(f"a stored watch has a non-integer width {width!r}; "
                                       f"`start` refuses it {UNTIL_FIXED}") from None
        opt = {k: (str(d[k]) if d.get(k) is not None else None)
               for k in ("fmt", "watch_mode", "created_at", "origin", "fingerprint", "cpu")}
        # A ROW STORED UNDER A RETIRED MODE is read under its new word, and the next write
        # persists that word, as a bare-hex address below.
        opt["watch_mode"] = RETIRED_MODES.get(opt["watch_mode"] or "", opt["watch_mode"])
        # A MISSING key is refused by name: `str(None)` is the four-letter word "None",
        # which is a truthy ref and would have sailed past every check below.
        for key in ("kind", "by", "ref"):
            if d.get(key) is None:
                raise DeclarationError(f"a stored declaration lacks `{key}`: {d!r}; `start` "
                                       f"refuses it {UNTIL_FIXED}")
        # A COMMENT'S STAMP IS THE FILE'S, held where the store is read, as `__post_init__`
        # holds its ref and text: a store edited by hand cannot carry a stamp `comment_save`
        # could not write.
        if d["kind"] == "comment" and (
                fault := cf.stamp_fault(opt["created_at"] or "")) is not None:
            raise DeclarationError(f"a stored comment's created_at {fault}; `start` refuses it "
                                   f"{UNTIL_FIXED}")
        # A ROW STORED BY ADDRESS IN BARE HEX is read in the address's one spelling: its `by`
        # says what it is, so nothing is guessed, and the next write persists it so. A row
        # stored BY SYMBOL in the `0x` spelling names no symbol any table can hold, so it is
        # read as the address it spells rather than refusing the whole store.
        ref, by = str(d["ref"]), str(d["by"])
        if by == "symbol" and inputs.is_address(ref):
            by = "address"
        if by == "address" and inputs.HEX_ADDR.fullmatch(ref.strip()):
            ref = canonical_ref(ref, "address")
        return Declaration(str(d["kind"]), by, ref, width=width,
                           role=str(d.get("role", "stop")),
                           condition=str(d.get("condition") or ""),
                           trigger=str(d.get("trigger") or ""),
                           trigger_type=str(d.get("trigger_type") or "w"),
                           text=str(d.get("text") or ""), **opt)


@dataclass(frozen=True)
class Resolved:
    """A declaration paired with where it points NOW: `address` (a raw address, nothing to
    resolve), `resolved` (the name is in the table), or `unresolved` (it is not, and the
    declaration is kept). `addr` is None only when unresolved."""

    decl: Declaration
    state: str
    addr: int | None = None
    # A POINTER ref resolves to its BASE here and to its address only against the machine
    # (the pointer's value is a read), so the state is `pointer` and the arming side
    # chases it: `base_addr` holds the pointer, `offset` is added to what it holds,
    # `pointer_width` is the type's when `types` says (else the machine's word), and
    # `field_fmt` is the named field's format. `why` says what an unresolved pointer lacks.
    pointer: vf.PointerRef | None = None
    base_addr: int | None = None
    offset: int = 0
    pointer_width: int | None = None
    field_fmt: str | None = None
    # The class the pointer's TARGET lives in when the type names it (`ptr16@CODE`): the
    # arming side places the value under that class's base instead of the base symbol's.
    pointer_class: str | None = None
    why: str | None = None


def resolve(decl: Declaration, symbols: dict[str, int],
            types: dict[str, str] | None = None) -> Resolved:
    """Where a declaration points against THIS table. The one name->address routine, so the
    tool that arms and the list that reports cannot disagree on what a name means. The
    table's keys are upper-cased by the reader that built it; a name is looked up the same
    way, and MAME's own reader refuses a table with one name twice, so there is no ambiguity
    to report here."""
    if decl.by == "address":
        return Resolved(decl, "address", int(decl.ref, 16))
    if decl.by == "expr":
        return Resolved(decl, "expr")
    if decl.by == "pointer":
        return _resolve_pointer(decl, symbols, types or {})
    addr = symbols.get(decl.ref.strip().upper())
    if addr is None:
        return Resolved(decl, "unresolved")
    return Resolved(decl, "resolved", addr)


def _resolve_pointer(decl: Declaration, symbols: dict[str, int],
                     types: dict[str, str]) -> Resolved:
    """The base of a pointer ref against the table and the types: `pointer` with the base's
    address, the offset (a field's from the type) and the pointer's width when typed; else
    `unresolved` with `why`. A base the table lacks is named as what it most likely is, a
    stack local, which has no stable address a pointer ref could start from."""
    pr = vf.parse_pointer(decl.ref)
    assert pr is not None
    base = inputs.stored_place(pr.base, symbols)
    if base is None:
        return Resolved(decl, "unresolved", pointer=pr, why=(
            inputs.not_a_ref("the pointer base", pr.base, decl.cpu, then=(
                ", so there is no pointer to start from (a pointer ref needs a GLOBAL, a symbol "
                "of the table or an address, as its base; a stack local has no stable "
                "address)"))))
    spec = types.get(pr.base.strip().upper())
    fmt = vf.parse(spec) if spec else None
    width = fmt.size if fmt is not None and fmt.kind == "pointer" else None
    klass = fmt.target_class if fmt is not None and fmt.kind == "pointer" else None
    if pr.field is None:
        return Resolved(decl, "pointer", pointer=pr, base_addr=base, offset=pr.offset,
                        pointer_width=width, pointer_class=klass)
    if fmt is None or fmt.kind != "pointer" or fmt.target is None or fmt.target.kind != "struct":
        return Resolved(decl, "unresolved", pointer=pr, base_addr=base, why=(
            f"`{pr.base}->{pr.field}` needs {pr.base} typed as a pointer to a struct "
            f"(`ptr32{{...}}` or `ptr16{{...}}` in the `types` file `start` takes); it is "
            f"{spec or 'untyped'}. Or name the offset: `[{pr.base}]+0x..`"))
    try:
        offset, field_fmt = vf.field_offset(fmt.target, pr.field)
    except vf.FormatError as e:
        return Resolved(decl, "unresolved", pointer=pr, base_addr=base, why=str(e))
    return Resolved(decl, "pointer", pointer=pr, base_addr=base, offset=offset,
                    pointer_width=width, field_fmt=field_fmt, pointer_class=klass)


def same_place(a: Declaration, b: Declaration) -> bool:
    """Two declarations are ONE when they differ only in how their ref is spelt: the store
    compares them with the ref under `match_key` (an address in any spelling, a symbol in any
    case), and everything else as the dataclass compares it."""
    from dataclasses import replace
    return (replace(a, ref=match_key(a.ref, a.by), trigger=inputs.place_key(a.trigger))
            == replace(b, ref=match_key(b.ref, b.by), trigger=inputs.place_key(b.trigger)))


# `match_key`'s rule in a client's words, one clause per kind of ref, composed per family from
# the kinds that family declares: a clear's refusal and its tool's description carry the same
# words, and a family is never told of a kind it cannot hold.
_ADDRESS = "a `0x` address in any spelling (`0x00ff` is `0xff`)"
_SYMBOL = "a symbol in any case"
_POINTER = "a pointer's base as either of those"
_EXPRESSION = ("an expression as typed but for its numbers, each read as the console reads it: "
               "bare, `0x` and `$` numbers are hex, `#` decimal, `0o` octal and `0b` binary "
               "(`d1==7fff`, `d1==0x7fff`, `d1==$7fff` and `d1==#32767` match)")
_IO = ('with `space="io"`, an io tap\'s port as an address or its block as a symbol, in those '
       "spellings")
#: What a clear's `ref` matches, by family.
REF_MATCH = {
    "breakpoint": f"{_ADDRESS}, and {_SYMBOL}",
    "watch": f"{_ADDRESS}, {_SYMBOL}, {_POINTER}, {_EXPRESSION}, and {_IO}",
    "regpoint": _EXPRESSION,
}


def match_key(ref: str, by: str) -> str:
    """The spelling a ref of kind `by` is compared under (`inputs.match_key`); a pointer ref
    in its canonical shape, its base a name in any case or an address in any spelling
    (`inputs.place_key`)."""
    if by != "pointer":
        return inputs.match_key(ref, by)
    text = canonical_ref(ref, by)
    pr = vf.parse_pointer(text)
    return text if pr is None else _pointer_text(pr, inputs.place_key(pr.base))


def _pointer_text(pr: vf.PointerRef, base: str) -> str:
    """A pointer ref rebuilt in its one shape around `base`."""
    if pr.field is not None:
        return f"{base}->{pr.field}"
    sign = "-" if pr.offset < 0 else "+"
    return f"[{base}]" + (f"{sign}0x{abs(pr.offset):x}" if pr.offset else "")


def canonical_ref(ref: str, by: str) -> str:
    """The one spelling a ref is stored and matched under: an address as `0x` and lower-case
    hex with no padding; a symbol, an expression or a pointer ref as typed, stripped. Inside
    a pointer ref a `0x` base folds the same way and any other base is a name kept as typed:
    `[BEEF]` through a symbol and `[0xBEEF]` at an address are two places. What a ref is
    COMPARED under is `match_key`."""
    text = ref.strip()
    if by == "address" and inputs.HEX_ADDR.fullmatch(text):
        return f"0x{int(text, 16):x}"
    if by == "pointer":
        # A `0x` BASE INSIDE A POINTER REF FOLDS LIKE AN ADDRESS REF, and the ref is rebuilt
        # in one shape: two spellings of one base stacked two watches on one byte.
        pr = vf.parse_pointer(text)
        if pr is not None:
            base = pr.base.strip()
            if inputs.is_address(base):
                base = canonical_ref(base, "address")
            return _pointer_text(pr, base)
    return text


def is_stale(decl: Declaration, fingerprint: str | None) -> bool:
    """A raw-ADDRESS declaration made against ANOTHER BUILD (or against none recorded):
    kept and listed `stale`, never re-armed on its own, because an address re-resolves
    against nothing and armed blind it lands on whatever the new build put there. The
    build is the fingerprint of the system, the ROM image and the symbol file, so a session
    over the same board re-arms every raw address it finds, whoever declared it; the first
    rule keyed this on the declaring SESSION and threw away every declaration of a board
    that had not changed. A by-symbol declaration is never stale: it is re-placed against
    the new table, which is the point of keeping it. WHERE THIS DIFFERS FROM THE SIBLING:
    there only a breakpoint can be stale, because nothing re-arms a watch across sessions;
    here `start`'s re-arm brings change watches back too, and a count watch's tap with them, so
    the same caution covers both. A capture's trigger is a second place, raw when it is written as
    an address (`inputs.is_address`), the reading `inputs.stored_place` gives it. A show or
    expr watch arms nothing and is never stale."""
    raw = decl.by == "address" or inputs.is_address(decl.trigger)
    if not raw or fingerprint is None:
        return False          # no build recorded for this session: nothing to judge against
    if decl.kind == "watch" and decl.watch_mode not in ("change", *TAP_MODES):
        return False
    return decl.fingerprint is None or decl.fingerprint != fingerprint


def state_home() -> Path:
    """This server's XDG state directory: what lives here survives a session and is not
    mistaken for a cache to be cleared."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "mame-debug"


_STORE_FILENAME = "declarations.json"


def default_path() -> Path:
    """Where the project's declarations live, in the state directory."""
    return state_home() / _STORE_FILENAME


def store_path(state_dir: Path | None) -> Path:
    """The store a session with a symbol file uses: its own `state_dir`'s when it names one,
    else the project's, which every session without one shares."""
    return state_dir / _STORE_FILENAME if state_dir is not None else default_path()


def store_key(system: str, symbols: str) -> str:
    """THE IDENTITY THAT KEYS THE STORE: the system name plus the RESOLVED path of the symbol
    file. Two spellings of one file are one key; two boards sharing a map (a family of sets)
    are told apart by the system; two maps of one board by the path. A session started with
    no symbol file has no key, because it can re-resolve nothing: its declarations are by
    address and die with it, which is the honest answer."""
    if not system:
        raise DeclarationError("a store key needs the system name: `start(system=...)` gives it")
    return f"{system} {Path(symbols).resolve()}"


class DeclarationStore:
    """The declarations of ONE guest: persistent in a file shared by every guest, or in
    memory for this session.

    The file maps a key (`store_key`) to a list of declarations; a store reads the whole
    file but exposes only its own key's list, and a write persists ONLY that key, so a
    store opened for another guest never clobbers this one's. With `path=None` the store
    lives as long as the session.
    """

    def __init__(self, identity: str, path: Path | None) -> None:
        if not identity:
            raise DeclarationError("a store needs a non-empty identity to key by: `start` builds "
                                   "it from the system and the symbol file")
        self._identity = identity
        self._path = path
        self._items: list[Declaration] = (
            [] if path is None else self._decls_for(self._read_raw(), identity))

    @staticmethod
    def _decls_for(raw: dict[str, object], key: str) -> list[Declaration]:
        """This key's declarations out of the whole file, refusing a shape that is not a
        list of objects as a NAMED refusal, never an `AttributeError` three layers down."""
        items = raw.get(key, [])
        if not isinstance(items, list):
            raise DeclarationError(
                f"key {key!r} maps to a {type(items).__name__}, not a list of declarations; "
                f"`start` refuses it {UNTIL_FIXED}")
        out: list[Declaration] = []
        seen: set[Declaration] = set()
        for d in items:
            if not isinstance(d, dict):
                raise DeclarationError(
                    f"a declaration under {key!r} is a {type(d).__name__}, not an object: "
                    f"{d!r}; `start` refuses it {UNTIL_FIXED}")
            decl = Declaration.from_dict(d)
            # ONE DECLARATION IN TWO SPELLINGS (`4a0` and `0x4a0` by address) reads as one, the
            # first kept, as `add` adopts the second rather than holding it twice.
            if decl not in seen:
                seen.add(decl)
                out.append(decl)
        return out

    def _read_raw(self) -> dict[str, object]:
        """The whole file as it is on disk right now, or empty when there is none. A file
        that cannot be read is refused and NOT discarded: fix or remove it rather than lose
        what it holds."""
        assert self._path is not None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise DeclarationError(
                f"the declaration file {self._path} could not be read: {exc}. It is not "
                f"discarded: fix or remove it by hand rather than lose what it holds, and "
                "`start` again") from None
        if not isinstance(raw, dict):
            raise DeclarationError(
                f"the declaration file {self._path} is not a mapping of key to declarations; "
                f"it holds a {type(raw).__name__}; `start` refuses it {UNTIL_FIXED}")
        return raw

    @property
    def persistent(self) -> bool:
        return self._path is not None

    @property
    def path(self) -> Path | None:
        """The file this store persists in, or None for a session-lived one."""
        return self._path

    def declarations(self) -> list[Declaration]:
        return list(self._items)

    def counts_by_cpu(self, more_watches: dict[str, int]) -> dict[str, dict[str, int]]:
        """How many declarations of each kind every cpu holds, in any state, by the cpu each
        names and under each kind's `COUNT_KEYS` name, plus `more_watches` (watches the store
        never holds, by cpu); one that names no cpu (an expr watch) is counted nowhere, and a
        comment, which neither stops nor watches, is not counted."""
        out: dict[str, dict[str, int]] = {}
        for d in self._items:
            if d.cpu is not None and d.kind in COUNT_KEYS:
                out.setdefault(d.cpu, no_counts())[COUNT_KEYS[d.kind]] += 1
        for cpu, n in more_watches.items():
            out.setdefault(cpu, no_counts())[COUNT_KEYS["watch"]] += n
        return out

    def bind_first_cpu(self, cpu: str | None) -> None:
        """Every row read without a cpu is the FIRST cpu's, `cpu`: a store written before a
        declaration had one held the declarations of the only table a start then took, the
        first cpu's. An expr watch keeps none. Held in memory; the next write persists it."""
        if cpu is None:
            return
        self._items = [d if d.cpu is not None or d.watch_mode == "expr"
                       else dataclasses.replace(d, cpu=cpu) for d in self._items]

    def add(self, decl: Declaration) -> bool:
        """Hold a declaration; True when NEW, False when this exact one was already held and
        is ADOPTED by the caller's origin and stamp (each half taken only when carried).

        ONE conflict is refused: the same watch `ref` carrying the OTHER half, show where a
        change already sits or the reverse: one row is one declaration, and clearing either
        half would disarm the other.
        """
        i = self.index_of(decl)
        if i is not None:
            held = self._items[i]
            origin = decl.origin if decl.origin is not None else held.origin
            created = decl.created_at if decl.created_at is not None else held.created_at
            build = decl.fingerprint if decl.fingerprint is not None else held.fingerprint
            if (origin, created, build) != (held.origin, held.created_at, held.fingerprint):
                self._items[i] = held.adopted_by(origin, created, build)
                self._persist()
            return False
        self.refuse_conflict(decl)
        self._items.append(decl)
        self._persist()
        return True

    def replace(self, old: Declaration, new: Declaration) -> None:
        """`new` in the place `old` holds, persisted once: for a declaration whose TEXT is
        corrected and whose identity is not. It is ADOPTED in the same write, as `add` adopts
        one declared again: each of origin, stamp and build taken from `new` only when carried."""
        i = self.index_of(old)
        if i is None:
            raise DeclarationError(f"{old.ref!r} is not held, so there is nothing to replace: "
                                   "`breakpoint_at` declares it")
        held = self._items[i]
        self._items[i] = dataclasses.replace(
            new,
            origin=new.origin if new.origin is not None else held.origin,
            created_at=new.created_at if new.created_at is not None else held.created_at,
            fingerprint=new.fingerprint if new.fingerprint is not None else held.fingerprint)
        self._persist()

    def index_of(self, decl: Declaration) -> int | None:
        """Where the store holds this declaration, an address matched in any spelling."""
        return next((i for i, d in enumerate(self._items) if same_place(d, decl)), None)

    def matches(self, d: Declaration, by: str, ref: str) -> bool:
        """Whether `ref`, a ref of kind `by`, names what `d` names: only a declaration of the
        same kind can (an address never reaches a symbol's row, nor the reverse), compared
        under `match_key`."""
        return d.by == by and match_key(d.ref, by) == match_key(ref, by)

    def held_ref(self, ref: str, by: str, kinds: tuple[str, ...], cpu: str | None) -> str | None:
        """The stored spelling of `ref`, of kind `by`, among `cpu`'s declarations of `kinds`
        (`matches`); None when nothing is held under it."""
        return next((d.ref for d in self._items if d.kind in kinds and d.cpu == cpu
                     and self.matches(d, by, ref)), None)

    def refuse_conflict(self, decl: Declaration) -> None:
        """The refusals `add` makes, asked on their own by the tool that ARMS before it
        arms: a watchpoint left in the debugger for a declaration the store then refused
        would be a row nothing lists and nothing clears (a test found exactly that). A
        watch's ref carries ONE declaration: the other half (show where change sits, or the
        reverse) is refused for the shared rule, and another SHAPE (width, format, condition,
        trigger) under the same ref is refused too, because it would be a second declaration
        arming a second row that a clear by ref could only half account for."""
        if self.index_of(decl) is not None or decl.kind == "regpoint":
            return      # a registerpoint's ref is its whole identity: the same text is the same one
        if decl.kind == "comment":
            return      # a comment shares its place with whatever else is declared there
        if decl.kind == "breakpoint":
            other = next((d for d in self._items if d.kind == "breakpoint"
                          and d.cpu == decl.cpu and self.matches(d, decl.by, decl.ref)), None)
            if other is not None:
                held = (f"under the condition {other.condition!r}" if other.condition
                        else "with no condition")
                raise DeclarationError(
                    f"{decl.ref!r} is already declared as a {other.role} breakpoint {held}; "
                    f"`breakpoint_clear(ref={decl.ref!r})` before declaring it another way")
            return
        for d in self._items:
            if d.kind != "watch" or d.cpu != decl.cpu or not self.matches(d, decl.by, decl.ref):
                continue
            if d.watch_mode != decl.watch_mode:
                raise DeclarationError(
                    f"{decl.ref!r} already has a {d.watch_mode!r} watch, and one ref may "
                    f"not be both {d.watch_mode} AND {decl.watch_mode}: one ref carries one "
                    f"declaration; `watch_clear(ref={d.ref!r})` before declaring the other")
            held = (f" under the condition {d.condition!r}" if d.condition
                    else " with no condition" if d.watch_mode == "change"
                    else f" on the trigger {d.trigger!r} "
                         f"({'its reads' if d.trigger_type == 'r' else 'its writes'})"
                    if d.trigger else "")
            raise DeclarationError(
                f"{decl.ref!r} is already declared as a {d.watch_mode} watch of width "
                f"{d.width} rendered as {d.fmt}{held}; `watch_clear(ref={d.ref!r})` before "
                "declaring it another way")

    def apply(self, adds: Collection[Declaration] = (),
              replaces: Collection[tuple[Declaration, Declaration]] = (),
              removes: Collection[Declaration] = ()) -> None:
        """Several changes as ONE write: every `(old, new)` of `replaces` puts `new` where `old`
        is held, `removes` go, `adds` are appended, the new list is installed in memory and
        then persisted once. A write that fails leaves the new list in memory and raises, so
        the caller can say the change is held for this session and not on disk. Unlike `add`
        and `replace` it judges nothing: each `old` and removal is a declaration as
        `declarations()` returned it, and the caller has already decided what is one place
        and kept every stamp it means to keep."""
        items = list(self._items)
        for old, new in replaces:
            items[items.index(old)] = new
        items = [d for d in items if d not in removes]
        self._items = [*items, *adds]
        self._persist()

    def discard(self, decls: Collection[Declaration]) -> int:
        """Drop exactly `decls` and return how many went."""
        keep = [d for d in self._items if d not in decls]
        removed = len(self._items) - len(keep)
        if removed:
            self._items = keep
            self._persist()
        return removed

    def _persist(self) -> None:
        """Re-read the file and replace ONLY this key's entry, written through a temporary
        and moved into place, so a crash mid-write cannot leave a half-written file that a
        later read would refuse. ONE WRITER is assumed, which is what this fleet has: the
        server holds one session and serialises its tools under one lock; two servers over
        one file could each read before the other's replace and lose an add, a race this
        design does not run and does not guard. Nothing to do for a session-lived store."""
        if self._path is None:
            return
        raw = self._read_raw()
        raw[self._identity] = [d.to_dict() for d in self._items]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fresh.replace(self._path, json.dumps(raw, indent=2, sort_keys=True).encode(),
                      "the declarations file", named_by_caller=False)
