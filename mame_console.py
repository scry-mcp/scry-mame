"""The console's GRAMMAR, as `debug` needs it: where one line splits into commands and a command
into its parameters, which commands write or release the machine, set a cpu, arm something
evaluated later or leave `totalcycles` stale, and how the console says it refused one.

The console has no exit code. A line it refuses answers text like any other line, and `debug`
once answered `ok` over it, the error only in `output`, with a `perform` going on to the next
step: six readings were lost before anybody noticed. The shapes read here are the ones CAPTURED
live (`tests/fixtures/console/PROVENANCE.txt`, the `refused.*` files), each anchored at a
line's start; a shape not captured is not matched, because a double authored from memory is
the thing that lies.

MAME prints two families (`debugcon.cpp`). A PARSE error (`execute_command`) echoes the whole
line after `>`, puts a caret under the failing command's first character and prints the
reason; the console stops the line there, so the commands before the failing one ran and it
and the ones after it did not. An error a command prints WHILE RUNNING (`Error in expression`
from `validate_number_parameter`, `Invalid ...`, `Error opening file`) leaves the rest of the
line running, and the refused command may have done part of its work before it failed (`print
d0=5,zzz` writes D0, then refuses `zzz`), so it stays counted as run. The console's text
buffer wraps every line at `CONSOLE_WRAP_COLS`, the echo and the caret line included, so a
parse error is read back through the wrap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from scry_core import prose
from scry_core.reply_contract import or_unavailable

import gdb_session as gs
import mame_lexer as lexer

# AN ASSIGNMENT ANYWHERE ON THE LINE CAN WRITE, and no prefix could ever see it: the console's
# own parser executes a one-parameter line holding `=`, `++` or `--` as an expression (`d0=1234`
# forces a register, `w@0x2031fc=1` pokes a word), `print` takes a list of expressions and
# evaluates each (`print pc,d0=1`), and a breakpoint's action (`bpset a,{cond},{d0=1}`) runs its
# expression at every hit. What counts as an assignment is `mame_lexer.ASSIGNS`, shared with a
# breakpoint condition's refusal. IT IS SEARCHED OUTSIDE QUOTED STRINGS ONLY
# (`mame_lexer.blank_quoted`): the console prints a string and never evaluates it, so
# `printf "pc=%x\n",pc` reads the pc and writes nothing.
DEBUG_ASSIGNS = re.compile(lexer.ASSIGNS)

# EVERY COMMAND THE CORE CONSOLE REGISTERS, read off `debugger_commands` in
# src/emu/debug/debugcmd.cpp (and `debugcon.cpp`'s own two), by what it does to the machine. A
# typed word is resolved the way the console resolves it (`resolve_command`): the command it
# spells, else the one command it is a prefix of, else nothing the core has -- a driver's own
# command, or a refusal the console gives by itself.
#
# RELEASES: a run the console starts and the stub sends no stop packet for, so the session is
# marked RUNNING until the stop is proved on the frame counter. The go family, and the steps
# the console takes on its own (`step N`, `over`, `out`, `next`), which are runs of the same kind.
_RELEASES = frozenset({
    "g", "go", "gbf", "gbt", "ge", "gex", "gi", "gint", "gni", "gp", "gt", "gtime", "gv",
    "gvblank", "n", "next", "o", "out", "over", "s", "step",
})
# WRITES: what changes the machine, on top of a release, which counts for the reason a typed
# resume does (it moves the machine to a place the caller did not name). `do` evaluates an
# expression, which may assign; `load` and `loadr` put a file into memory and `stateload`
# replaces the machine; a reset, a rewind, an image mounted or removed, a cpu suspended or
# resumed each leave it other than the game left it (with no cpu named, `suspend` and `resume`
# only list: `_LIST_WHEN_BARE`); `source` runs a file of console commands, any of which may write.
# `save`, `statesave`, `snap` and the lists write OUT and change nothing. The breakpoint,
# watchpoint, registerpoint and exception point family is the debugger's bookkeeping, and
# counts only through an action (`_ACTION_AT`), as a trace does.
_WRITES = _RELEASES | frozenset({
    "do", "fill", "filld", "filli", "fillo", "load", "loadd", "loadi", "loado", "loadr", "sl",
    "stateload", "softreset", "hardreset", "rewind", "rw", "mount", "unmount", "suspend",
    "resume", "source",
})
_READS = frozenset({
    "//", "/*", "bp", "bpclear", "bpdisable", "bpenable", "bplist", "bpset", "cheatinit",
    "cheatlist", "cheatnext", "cheatnextf", "cheatrange", "cheatundo", "ci", "cl", "cls", "cn",
    "cnf", "comadd", "comdelete", "comlist", "commit", "comsave", "condump", "cpulist", "cr", "cu",
    "dasm", "dump", "dumpd", "dumpi", "dumpkbd", "dumpo", "ep", "epclear", "epdisable",
    "epenable", "eplist", "epset", "exit", "f", "fd", "fi", "find", "findd", "findi", "findo",
    "fo", "focus", "help", "helpcustom", "history", "ignore", "images", "input", "logerror",
    "map", "mapd", "mapi", "mapo", "memdump", "observe", "pcatmem", "pcatmemd", "pcatmemi",
    "pcatmemo", "print", "printf", "quit", "rp", "rpclear", "rpdisable", "rpenable", "rplist",
    "rpset", "save", "saved", "savei", "saveo", "saver", "snap", "ss", "statesave",
    "strdump", "strdumpd", "strdumpi", "strdumpo", "symlist", "time", "trace", "traceflush",
    "tracelog", "traceover", "tracesym", "trackmem", "trackpc", "wp", "wpclear", "wpd",
    "wpdisable", "wpdset", "wpenable", "wpi", "wpiset", "wplist", "wpo", "wposet", "wpset",
})
CORE_COMMANDS = tuple(sorted(_WRITES | _READS))


def resolve_command(word: str) -> str | None:
    """The core command `word` names, as the console resolves it (`internal_parse_command` in
    src/emu/debug/debugcon.cpp): the command itself, else the ONE command it is a prefix of.
    None for an ambiguous prefix (the console refuses it), and for a word the core does not
    have (a driver's own command, or an unknown one the console refuses)."""
    low = word.lower()
    if low in CORE_COMMANDS:
        return low
    spelled = [name for name in CORE_COMMANDS if name.startswith(low)] if low else []
    return spelled[0] if len(spelled) == 1 else None


def parameters(command: str) -> tuple[str, list[str]]:
    """One command's word, lower-cased, and its parameters, each stripped of its edge spaces,
    as the console cuts them (`internal_parse_command` and `internal_execute_command`,
    src/emu/debug/debugcon.cpp): the whole command is split at each `,` outside brackets and
    quoted strings, and the word is what the first piece holds up to its first space. A word
    with nothing after it has no parameters; `ignore ,` has two, both empty."""
    text = command.lstrip()
    pieces = [text[b:e] for b, e in _cuts(text, ",")]
    head = pieces[0].split(None, 1)
    word = head[0] if head else ""
    rest = head[1] if len(head) > 1 else ""
    params = [] if rest.strip() == "" and len(pieces) == 1 else [rest, *pieces[1:]]
    return word.lower(), [p.strip() for p in params]


def releases(command: str) -> bool:
    """Whether one console command starts a run the console owns (`_RELEASES`)."""
    return command_name(command) in _RELEASES


# AN ACTION is a console command list run at every hit of a breakpoint, a watchpoint, a
# registerpoint or an exception point, and at every instruction a trace logs (`bpset
# a,1,{fill 100,1,1}`, `trace t.txt,0,,{g}`); nothing in the words before it says what it
# does, so it counts as a write, on the cautious side, braced or bare, whatever it holds. It is
# found BY ITS POSITION, the parameter each command takes it in (debugcmd.cpp; always its last),
# never by a brace: a CONDITION goes in braces too (`rpset {d1==7fff}`, `bpset a,{d0==1}`:
# bare, the console reads `==` after one parameter as an assignment), and a condition is
# evaluated, never run, so it writes only through an assignment, which `DEBUG_ASSIGNS` catches.
# The same keys are the commands that arm something evaluated later (`evaluated_later`).
_ACTION_AT = {
    "bp": 2, "bpset": 2, "ep": 2, "epset": 2, "rp": 1, "rpset": 1, "trace": 3, "traceover": 3,
    **dict.fromkeys(("wp", "wpset", "wpd", "wpdset", "wpi", "wpiset", "wpo", "wposet"), 4),
}
# With no parameter these print the set they would change and change nothing, so a bare
# `suspend` is not a write and a bare `ignore` sets no cpu.
_LIST_WHEN_BARE = frozenset({"suspend", "resume", "ignore", "observe"})
# THE COMMANDS THAT MOVE WHICH CPUS THE DEBUGGER SHOWS OR IGNORES: a re-read too many costs one
# console call, one too few leaves a reply naming a cpu that is no longer the visible one.
_CPU_SETTERS = frozenset({"focus", "ignore", "observe"})
# WHAT LEAVES `totalcycles` STALE (`mame_cycles` says why): a load or a rewind replaces the
# machine without executing, and a reset is applied by the next run.
_REWINDS = frozenset({"rewind", "rw"})
_REPLACES = frozenset({"stateload", "sl"}) | _REWINDS
_RESETS = frozenset({"softreset"})        # `debug` refuses a typed `hardreset`


def _named(command: str) -> tuple[str | None, list[str]]:
    """The core command `command` runs (`resolve_command`) and its parameters (`parameters`)."""
    word, params = parameters(command)
    return resolve_command(word), params


def command_name(command: str) -> str | None:
    """The core command `command` runs, as the console resolves its word; None for none."""
    return _named(command)[0]


def stale_counter_command(command: str) -> str | None:
    """The command `command` runs when it leaves `totalcycles` stale (`_REPLACES`, `_RESETS`),
    else None."""
    name = _named(command)[0]
    return name if name in _REPLACES | _RESETS else None


# WHAT THE CONSOLE PRINTS WHEN `rewind` FAILED, and only then (`execute_rewind` in
# src/emu/debug/debugcmd.cpp prints nothing when it stepped back; `rewind.refused.txt`).
REWIND_REFUSED = "Rewind error occured.  See error.log for details."


def refused_rewind(commands: list[str], output: str) -> bool:
    """Whether a line whose only stale-counter command is a rewind was answered with MAME's own
    refusal of it, so it replaced nothing. A line with more than one of them is not judged by
    this, and stays marked, on the cautious side."""
    stale = [name for one in commands if (name := stale_counter_command(one))]
    return len(stale) == 1 and stale[0] in _REWINDS and REWIND_REFUSED in output


def is_reset(name: str) -> bool:
    """Whether the command `name` is a reset, which the next run applies."""
    return name in _RESETS


def evaluated_later(command: str) -> bool:
    """Whether `command` arms something the console evaluates later, at a hit or a traced
    instruction (`_ACTION_AT`), so an expression in it runs then and not now."""
    return _named(command)[0] in _ACTION_AT


def sets_cpus(command: str) -> bool:
    """Whether `command` moves which cpus are shown or ignored (`_CPU_SETTERS`): not their bare
    listing."""
    name, params = _named(command)
    return name in _CPU_SETTERS and not (name in _LIST_WHEN_BARE and not params)


def _writes(command: str) -> bool:
    name, params = _named(command)
    if name in _LIST_WHEN_BARE and not params:
        return False
    at = _ACTION_AT.get(name or "")
    return name in _WRITES or (at is not None and len(params) > at and params[at] != "")


def _cuts(line: str, sep: str) -> list[tuple[int, int]]:
    """Where `line` is cut at each `sep` outside a quoted string and outside `()`, `[]` and
    `{}`, the console's one rule for both a line's commands and a command's parameters."""
    spans, depth, begin = [], 0, 0
    for i, c in enumerate(lexer.blank_quoted(line)):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == sep and depth == 0:
            spans.append((begin, i))
            begin = i + 1
    spans.append((begin, len(line)))
    return spans


def command_spans(line: str) -> list[tuple[int, int]]:
    """Where each command of one console line begins and ends, split where MAME's console
    splits them (`debugcon.cpp`): at a `;` outside a quoted string and outside `()`, `[]`
    and `{}`. The offsets are what a parse error's caret points into. A `;` that ends the
    line ends the last command and opens no empty one, as the console's own loop does."""
    spans = _cuts(line, ";")
    return spans[:-1] if len(spans) > 1 and spans[-1][0] == len(line) else spans


def console_commands(line: str) -> list[str]:
    """The commands of one console line, as `command_spans` cuts them. The prefix rules only
    see the start of what they are given, so each command is judged alone."""
    return [line[b:e] for b, e in command_spans(line)]


def mutates(command: str) -> bool:
    """Whether a line typed through `debug` can change the machine: `DEBUG_ASSIGNS` outside
    its quoted strings and `_writes` over each of its commands, with the writes to the
    debugger's temps taken out (`mame_lexer.without_temp_writes`), which raise no alarm
    because nothing of the guest moves."""
    return mutates_any(console_commands(command))


def mutates_any(commands: list[str]) -> bool:
    for one in commands:
        text = lexer.without_temp_writes(one)
        if DEBUG_ASSIGNS.search(lexer.blank_quoted(_evaluated(text))) or _writes(text):
            return True
    return False


# A COMMENT'S TEXT is the pane's and never evaluated (`// 0x400,d0=7` leaves D0 as it was),
# while its address is an expression like any other: only that is searched.
_TEXT_FROM = {"//": 1, "comadd": 1, "/*": 1, "commit": 1}


def _evaluated(command: str) -> str:
    """`command` without the parameters the console never evaluates (`_TEXT_FROM`)."""
    word, params = parameters(command)
    at = _TEXT_FROM.get(resolve_command(word) or "")
    return command if at is None else " ".join([word, ",".join(params[:at])])


def is_expression(command: str) -> bool:
    """Whether the console takes `command` as an ASSIGNMENT EXPRESSION rather than a command
    (`debugcon.cpp`, `internal_parse_command`): one parameter (no `,` outside brackets and
    quotes) holding a `=`, a `++` or a `--` outside them, or a `do ` prefix. `print
    d1==1234` is one, and the console refuses it; `print {d1==1234}` is a command."""
    text = command.lstrip()
    if len(text) > 3 and text[:2].lower() == "do" and text[2].isspace():
        return True
    depth, expr = 0, False
    outside = lexer.blank_quoted(command)
    for i, c in enumerate(outside):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and c == ",":
            return False
        elif depth == 0 and (c == "=" or (c in "+-" and i > 0 and outside[i - 1] == c)):
            expr = True
    return expr


# ---------------------------------------------------------------- the console's own refusals

_PARSE_REASONS = re.compile(
    r"^(?:unknown command|ambiguous command|unbalanced parentheses|unbalanced quotes|"
    r"not enough parameters for command|too many parameters for command|"
    r"error in assignment expression: .*)$")
_CARET_PIECE = re.compile(r"^ *\^?$")          # a parse error's caret line, wrapped or not
_CARET_REASON = re.compile(r"^ *\^\S.*$")       # an expression error's caret and its reason
# An error a command prints WHILE RUNNING: pinned on the command that carries its expression
# or its file, or on the one command of its family.
# The rest are the console's printed refusals that name no expression, file or family, read off
# its `printf`s in src/emu/debug/debugcon.cpp and debugcmd.cpp: pinned on the one command of a
# line of one, and on none of a longer line.
_RUN_ERRORS = re.compile(
    r"^(?:Error in expression: (?P<expr>.+)|"
    r"Error in command: (?P<action>.+)|"
    r"Invalid (?P<family>breakpoint|watchpoint|registerpoint) number .+|"
    r"Invalid watchpoint (?P<wptype>type): .+|"
    r"Error opening file '(?P<file>.+)'|"
    r"(?P<other>Unable to find device '.+'|Invalid CPU index \d+|Device .+ is not a CPU|"
    r"Memory space '.+' not found found for device '.+'|No matching memory region found for "
    r"'.+'|Address [0-9a-fA-F]+ in logical space .+ does not map to anything|Not enough "
    r"parameters for format!|Invalid offset|Invalid screen number '-?\d+'|"
    r"Can't ignore all devices!))$")
_FAMILY_PREFIX = {"breakpoint": "bp", "watchpoint": "wp", "registerpoint": "rp"}
# How many refused commands a reply lists in full: a line of hundreds of refused commands
# answers hundreds of error lines, and the reply is bounded like `output` is.
REFUSED_LISTED_MAX = 16
REFUSED_NAMED_MAX = 4


@dataclass(frozen=True)
class Refused:
    """One command the console refused: its `index` on the line and its text, or None for
    both when the answer does not say which command it was; the console's `error` line(s);
    and whether the line `stopped` there (a parse error) or went on (an error printed while
    the command ran, which may have done part of its work first)."""
    index: int | None
    command: str | None
    error: str
    stopped: bool


@dataclass(frozen=True)
class Refusals:
    """What the console refused in one line: each `Refused`, and `not_run`, the indices a
    parse error left unexecuted (its own command and everything after it)."""
    refused: list[Refused]
    not_run: list[int]

    def skipped(self) -> set[int]:
        """The commands that never ran: a parse error's own and the ones after it. A command
        refused while running stays counted, on the cautious side."""
        return {r.index for r in self.refused if r.stopped and r.index is not None} | set(
            self.not_run)

    def fields(self, commands: list[str]) -> dict[str, Any]:
        """The reply's own fields for the refusal, bounded."""
        unpinned = "the console's answer does not say which command it was"
        listed = [{"index": or_unavailable(r.index, unpinned),
                   "command": or_unavailable(r.command, unpinned), "error": r.error}
                  for r in self.refused[:REFUSED_LISTED_MAX]]
        return {"refused": listed, "refused_total": len(self.refused),
                "not_run": [commands[k] for k in self.not_run]}


def _joined(pieces: list[str]) -> str:
    """The logical line MAME's wrap cut into `pieces`: a piece exactly `CONSOLE_WRAP_COLS`
    long was cut hard, a shorter one at a space the wrap dropped (`gdb_session.unwrap_console`
    says why the geometry cannot always tell; here the echo is compared to the command sent,
    which settles it)."""
    out = ""
    for k, piece in enumerate(pieces):
        if k and len(pieces[k - 1]) != gs.CONSOLE_WRAP_COLS:
            out += " "
        out += piece
    return out


def _parse_error(command: str, lines: list[str], i: int) -> tuple[int, str, int] | None:
    """A parse error beginning at `lines[i]` (the echo, `>` + the command, wrapped or not),
    as the caret's offset into the command, the reason, and the index after the reason; None
    when the lines from `i` are not that shape."""
    for j in range(i + 1, len(lines)):
        if _PARSE_REASONS.match(lines[j]):
            break
    else:
        return None
    pieces = lines[i + 1:j]
    k = len(pieces)
    while k > 0 and _CARET_PIECE.match(pieces[k - 1]):
        k -= 1
    caret, echo = pieces[k:], [lines[i][1:], *pieces[:k]]
    if not caret or not caret[-1].endswith("^") or _joined(echo) != command:
        return None
    return _joined(caret).index("^") - 1, lines[j], j + 1


def _only(candidates: list[int]) -> int | None:
    return candidates[0] if len(candidates) == 1 else None


def refusals(command: str, output: str) -> Refusals | None:
    """What the console refused in `command`, read off `output`; None when no captured
    error shape is in it. A parse error is pinned by its caret (for `error in assignment
    expression` the caret's column is the error's code, so it is pinned on the line's one
    expression when it has one); a run-time error by the expression or the file it quotes,
    or by its family's one command. An error that cannot be pinned names no command and
    leaves every command counted as run."""
    spans = command_spans(command)
    texts = [command[b:e] for b, e in spans]
    words = [t.split()[0].lower() if t.split() else "" for t in texts]
    n = len(spans)
    lines = output.split("\n")
    refused: list[Refused] = []
    not_run: list[int] = []

    def pin(at: int | None, error: str, stopped: bool) -> None:
        refused.append(Refused(at, texts[at].strip() if at is not None else None, error,
                               stopped))

    i = 0
    while i < len(lines):
        line = lines[i]
        parsed = _parse_error(command, lines, i) if line.startswith(">") else None
        if parsed is not None:
            offset, reason, i = parsed
            if reason.startswith("error in assignment expression"):
                at = _only([k for k, t in enumerate(texts) if is_expression(t)])
            else:
                at = next((k for k, (b, e) in enumerate(spans) if b <= offset <= e), n - 1)
            pin(at, reason, stopped=True)
            if at is not None:
                not_run.extend(range(at + 1, n))
            continue
        m = _RUN_ERRORS.match(line)
        if m is None:
            i += 1
            continue
        error = line
        if m.group("expr") is not None and i + 1 < len(lines) and _CARET_REASON.match(
                lines[i + 1]):
            error = f"{line} / {lines[i + 1].strip()}"
            i += 1
        if m.group("expr") is not None:
            at = _only([k for k, t in enumerate(texts) if m.group("expr") in t])
        elif m.group("action") is not None:
            at = _only([k for k, t in enumerate(texts) if m.group("action") in t])
        elif m.group("file") is not None:
            at = _only([k for k, t in enumerate(texts) if m.group("file") in t])
        elif m.group("other") is not None:
            at = _only(list(range(n)))
        else:
            prefix = _FAMILY_PREFIX["watchpoint" if m.group("wptype") else m.group("family")]
            at = _only([k for k, w in enumerate(words) if w.startswith(prefix)])
        pin(at, error, stopped=False)
        i += 1
    if not refused:
        return None
    return Refusals(refused, sorted(set(not_run)))


def refusal_message(command: str, found: Refusals) -> str:
    """The console's refusal in one sentence: which command, quoted, and the console's own
    line; on a line of several commands, which ran and which did not. Past a few refusals
    the rest are counted, not quoted."""
    n = len(command_spans(command))
    parts = []
    for r in found.refused[:REFUSED_NAMED_MAX]:
        if r.index is None:
            parts.append(f"the console refused the line: {r.error}; which of its {n} "
                         "commands it refused could not be told from the answer, so every "
                         "command is counted as run")
        elif n == 1:
            parts.append(f"the console refused `{r.command}`: {r.error}")
        else:
            parts.append(f"the console refused command {r.index + 1} of {n}, "
                         f"`{r.command}`: {r.error}")
    if len(found.refused) > REFUSED_NAMED_MAX:
        more = len(found.refused) - REFUSED_NAMED_MAX
        parts.append(f"and {prose.counted(more, 'more console error')}, counted in `refused_total`")
    if found.not_run:
        first = found.not_run[0]
        skipped = ", ".join(f"`{one.strip()}`" for one in console_commands(command)[first:])
        before = "the commands before it ran, and " if first > 1 else ""
        parts.append(f"{before}{skipped} never ran")
    elif n > 1 and all(r.index is not None for r in found.refused):
        parts.append("the rest of the line ran")
    return "; ".join(parts)


def cpu_suffix(cpu: str | None) -> str:
    """The `:<cpu>` a console command names its cpu with (`bp <addr>:<cpu>`, `wp
    <addr>:<cpu>,<len>,w`, `map <addr>:<cpu>`, all in MAME's own `help`), so a row lands on the
    cpu the reply names and not on whichever is visible; the stub's `Z0` and `Z2` reach the
    visible cpu only. A cpu the console cannot name (`cpulist` marked none) leaves the suffix
    off: the visible cpu."""
    return f":{cpu}" if cpu else ""
