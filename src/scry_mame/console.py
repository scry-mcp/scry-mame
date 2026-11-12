"""Grammar of MAME's debug console as `debug` needs it: command splitting, which commands
write or release the machine, and how the console reports a refusal.

The console has no exit code. The refusal shapes matched here are the ones captured live
(`tests/fixtures/console/provenance.txt`), each anchored at a line's start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from scry_core import prose
from scry_core.reply_contract import or_unavailable

from scry_mame import gdb_session as gs
from scry_mame import lexer

# An assignment anywhere on the line can write (`d0=1234`, `print pc,d0=1`, a breakpoint
# action), so no prefix sees it. Searched outside quoted strings only: the console prints a
# string and never evaluates it.
DEBUG_ASSIGNS = re.compile(lexer.ASSIGNS)

# Every command the core console registers (debugcmd.cpp, debugcon.cpp), by its effect.
#
# RELEASES: runs the console starts without a stop packet, so the session counts as RUNNING
# until the frame counter proves the stop.
_RELEASES = frozenset({
    "g", "go", "gbf", "gbt", "ge", "gex", "gi", "gint", "gni", "gp", "gt", "gtime", "gv",
    "gvblank", "n", "next", "o", "out", "over", "s", "step",
})
# WRITES: what changes the machine on top of a release. Bare, `suspend` and `resume` only
# list (`_LIST_WHEN_BARE`). The breakpoint family counts only through an action (`_ACTION_AT`).
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
    """The core command `word` names, or None if ambiguous or not in the core."""
    low = word.lower()
    if low in CORE_COMMANDS:
        return low
    spelled = [name for name in CORE_COMMANDS if name.startswith(low)] if low else []
    return spelled[0] if len(spelled) == 1 else None


def parameters(command: str) -> tuple[str, list[str]]:
    """A command's lower-cased word and stripped parameters, split at `,` outside brackets
    and quotes; `ignore ,` has two empty ones."""
    text = command.lstrip()
    pieces = [text[b:e] for b, e in _cuts(text, ",")]
    head = pieces[0].split(None, 1)
    word = head[0] if head else ""
    rest = head[1] if len(head) > 1 else ""
    params = [] if rest.strip() == "" and len(pieces) == 1 else [rest, *pieces[1:]]
    return word.lower(), [p.strip() for p in params]


def releases(command: str) -> bool:
    return command_name(command) in _RELEASES


# An action is a command list run at every hit or traced instruction, so it counts as a write.
# Found by its parameter position (always the last), never by braces: a condition is braced
# too and writes only through an assignment, which `DEBUG_ASSIGNS` catches. The same keys arm
# something evaluated later (`evaluated_later`).
_ACTION_AT = {
    "bp": 2, "bpset": 2, "ep": 2, "epset": 2, "rp": 1, "rpset": 1, "trace": 3, "traceover": 3,
    **dict.fromkeys(("wp", "wpset", "wpd", "wpdset", "wpi", "wpiset", "wpo", "wposet"), 4),
}
# Bare, these only list.
_LIST_WHEN_BARE = frozenset({"suspend", "resume", "ignore", "observe"})
_CPU_SETTERS = frozenset({"focus", "ignore", "observe"})
_REWINDS = frozenset({"rewind", "rw"})
_REPLACES = frozenset({"stateload", "sl"}) | _REWINDS
_RESETS = frozenset({"softreset"})        # `debug` refuses a typed `hardreset`


def _named(command: str) -> tuple[str | None, list[str]]:
    word, params = parameters(command)
    return resolve_command(word), params


def command_name(command: str) -> str | None:
    return _named(command)[0]


def stale_counter_command(command: str) -> str | None:
    """The command `command` runs when it leaves `totalcycles` stale, else None."""
    name = _named(command)[0]
    return name if name in _REPLACES | _RESETS else None


# Printed only when `rewind` failed.
REWIND_REFUSED = "Rewind error occured.  See error.log for details."


def refused_rewind(commands: list[str], output: str) -> bool:
    """Whether the line's only stale-counter command is a rewind MAME refused. With more than
    one, it stays marked."""
    stale = [name for one in commands if (name := stale_counter_command(one))]
    return len(stale) == 1 and stale[0] in _REWINDS and REWIND_REFUSED in output


def is_reset(name: str) -> bool:
    return name in _RESETS


def evaluated_later(command: str) -> bool:
    """Whether `command` arms something evaluated at a hit or traced instruction."""
    return _named(command)[0] in _ACTION_AT


def sets_cpus(command: str) -> bool:
    """Whether `command` moves which cpus are shown or ignored, not their bare listing."""
    name, params = _named(command)
    return name in _CPU_SETTERS and not (name in _LIST_WHEN_BARE and not params)


def _writes(command: str) -> bool:
    name, params = _named(command)
    if name in _LIST_WHEN_BARE and not params:
        return False
    at = _ACTION_AT.get(name or "")
    return name in _WRITES or (at is not None and len(params) > at and params[at] != "")


def _cuts(line: str, sep: str) -> list[tuple[int, int]]:
    """Where `line` is cut at `sep` outside quotes and `()`, `[]`, `{}`."""
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
    """Offsets of each command of a console line, split at `;` outside quotes and brackets;
    a trailing `;` opens no empty command."""
    spans = _cuts(line, ";")
    return spans[:-1] if len(spans) > 1 and spans[-1][0] == len(line) else spans


def console_commands(line: str) -> list[str]:
    """The commands of one line, each judged alone."""
    return [line[b:e] for b, e in command_spans(line)]


def mutates(command: str) -> bool:
    """Whether a line typed through `debug` can change the machine, ignoring debugger temps."""
    return mutates_any(console_commands(command))


def mutates_any(commands: list[str]) -> bool:
    for one in commands:
        text = lexer.without_temp_writes(one)
        if DEBUG_ASSIGNS.search(lexer.blank_quoted(_evaluated(text))) or _writes(text):
            return True
    return False


# A comment's text is never evaluated; only its address is.
_TEXT_FROM = {"//": 1, "comadd": 1, "/*": 1, "commit": 1}


def _evaluated(command: str) -> str:
    word, params = parameters(command)
    at = _TEXT_FROM.get(resolve_command(word) or "")
    return command if at is None else " ".join([word, ",".join(params[:at])])


def is_expression(command: str) -> bool:
    """Whether the console takes `command` as an assignment expression: one parameter holding
    `=`, `++` or `--` outside brackets and quotes, or a `do ` prefix."""
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



_PARSE_REASONS = re.compile(
    r"^(?:unknown command|ambiguous command|unbalanced parentheses|unbalanced quotes|"
    r"not enough parameters for command|too many parameters for command|"
    r"error in assignment expression: .*)$")
_CARET_PIECE = re.compile(r"^ *\^?$")
_CARET_REASON = re.compile(r"^ *\^\S.*$")
# Errors printed while a command runs, pinned on the command carrying the expression, file
# or family; `other` names none, so it pins only on a one-command line.
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
REFUSED_LISTED_MAX = 16
REFUSED_NAMED_MAX = 4


@dataclass(frozen=True)
class Refused:
    """One refused command; `index` and `command` are None when the answer does not say which.
    `stopped` is True for a parse error, False for one printed while the command ran."""
    index: int | None
    command: str | None
    error: str
    stopped: bool


@dataclass(frozen=True)
class Refusals:
    """What the console refused in one line; `not_run` are the indices a parse error skipped."""
    refused: list[Refused]
    not_run: list[int]

    def skipped(self) -> set[int]:
        """The commands that never ran; a command refused while running stays counted."""
        return {r.index for r in self.refused if r.stopped and r.index is not None} | set(
            self.not_run)

    def fields(self, commands: list[str]) -> dict[str, Any]:
        unpinned = "the console's answer does not say which command it was"
        listed = [{"index": or_unavailable(r.index, unpinned),
                   "command": or_unavailable(r.command, unpinned), "error": r.error}
                  for r in self.refused[:REFUSED_LISTED_MAX]]
        return {"refused": listed, "refused_total": len(self.refused),
                "not_run": [commands[k] for k in self.not_run]}


def _joined(pieces: list[str]) -> str:
    """The logical line MAME's wrap cut into `pieces`: a piece of `CONSOLE_WRAP_COLS` was cut
    hard, a shorter one at a dropped space."""
    out = ""
    for k, piece in enumerate(pieces):
        if k and len(pieces[k - 1]) != gs.CONSOLE_WRAP_COLS:
            out += " "
        out += piece
    return out


def _parse_error(command: str, lines: list[str], i: int) -> tuple[int, str, int] | None:
    """A parse error at `lines[i]` (the echo) as caret offset, reason and next index, else None."""
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
    """What the console refused in `command`, read off `output`, or None if no captured error
    shape is in it. Errors that cannot be pinned name no command and leave all counted as run."""
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
    """The console's refusal in one sentence; past a few refusals the rest are counted."""
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
    """The `:<cpu>` suffix naming a console command's cpu, empty for a cpu the console cannot
    name."""
    return f":{cpu}" if cpu else ""
