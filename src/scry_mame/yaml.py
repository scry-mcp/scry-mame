"""A STRICT reader of the YAML a project's `gfx.yaml` is written in, and the writer of the same
subset (`dumps`, what `gfx_draft` writes a draft with).

WHY A READER OF OUR OWN. The server takes no dependency it can do without, and a manifest is
written by hand, with comments, by people who read it next to the driver. So the file is YAML,
and this reads the part of YAML such a file needs: comments, block mappings, block sequences,
one-line flow sequences and mappings of scalars, integers in decimal or hex, `true` and `false`,
and strings plain or quoted on one line.

WHY STRICT. A lenient subset misreads silently: YAML 1.1 readers turn `no` into false, `012`
into ten, `1999-12-31` into a date and `1:20` into eighty, and a reader that took them as
strings would disagree with every other tool that opens the same file. So a plain scalar that
some YAML reader would type differently is refused with its line and the advice to quote it,
and so is everything outside the subset (anchors, tags, multi-line scalars, tabs, a key given
twice). What is read is read the way any YAML reader reads it; what might not be is refused.
"""

from __future__ import annotations

import re
from typing import Any

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEC = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_HEX = re.compile(r"^0x[0-9a-fA-F]+$")
# THE PLAIN SCALARS ANOTHER YAML READER WOULD TYPE: YAML 1.1's implicit resolvers, as PyYAML
# spells them (bool, float, int, merge, null, timestamp, value), with the spec's single-letter
# `y` and `n` that PyYAML leaves out and other 1.1 readers do not, and YAML 1.2's core schema. A
# plain scalar matching one is refused unless it is one of the two forms read here (a decimal
# without a sign or leading zero, `0x` hex) or `true`/`false`; a KEY matching one is refused
# outright, since a reader types a key as it types a value (`on:` is the key true).
_TYPED = [re.compile(p, re.X) for p in (
    r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF|y|n)$",
    r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?
        |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$""",
    r"""^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+
        |[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$""",
    r"^(?:<<)$",
    r"^(?:~|null|Null|NULL|)$",
    r"""^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]
        |[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[\ \t]+)[0-9][0-9]?:[0-9][0-9]
        :[0-9][0-9](?:\.[0-9]*)?(?:[\ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$""",
    r"^(?:=)$",
    # YAML 1.2's core schema, which a newer reader applies instead
    r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$",
    r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
)]
# A plain scalar may not start with a character YAML gives a meaning.
_INDICATOR = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`]")


class YamlError(ValueError):
    """Text outside the subset, or not YAML at all: the message names the line."""


def _error(line: int, message: str) -> YamlError:
    return YamlError(f"line {line}: {message}")


def _strip_comment(text: str, line: int) -> str:
    """`text` without its comment: a `#` at the start or after a space, outside quotes. A quote
    opens a string only where a scalar can start (after `: `, `- `, `[`, `{`, `,` or the
    indent), so the apostrophe in `the game's own # note` is a letter and the note a comment,
    as every YAML reader has it."""
    if "\t" in text:
        raise _error(line, "a tab: indent and separate with spaces")
    quote, i = "", 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ch == "'" and text[i + 1:i + 2] == "'":
                i += 2
                continue
            quote = "" if ch == "'" else quote
        elif quote == '"':
            if ch == "\\":
                i += 2
                continue
            quote = "" if ch == '"' else quote
        elif ch in "'\"" and _opens(text, i):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] == " "):
            return text[:i].rstrip()
        i += 1
    return text.rstrip()


def _opens(text: str, i: int) -> bool:
    """Whether a quote at `i` starts a scalar: the first thing on the line, or after `[`, `{`,
    `,`, or a `:` or `-` that a space follows."""
    before = text[:i].rstrip(" ")
    if not before:
        return True
    last = before[-1]
    return last in "[{," or (last in ":-" and before != text[:i])


def _scalar(text: str, line: int) -> Any:
    """One scalar: quoted, flow, an integer, a boolean, or a plain string no reader types."""
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise _error(line, f"{text!r} is a single-quoted string that does not close on its "
                               "line (a string is one line here)")
        body = text[1:-1]
        if "'" in body.replace("''", ""):
            raise _error(line, f"{text!r} has a lone quote inside; write it twice")
        return body.replace("''", "'")
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"'):
            raise _error(line, f"{text!r} is a double-quoted string that does not close on its "
                               "line (a string is one line here)")
        return _double(text[1:-1], text, line)
    if text.startswith(("[", "{")):
        return _flow(text, line)
    if text in ("true", "false"):
        return text == "true"
    if _DEC.match(text):
        return int(text)
    if _HEX.match(text):
        return int(text, 16)
    if any(p.match(text) for p in _TYPED) or _INDICATOR.match(text) or ": " in text \
            or text.endswith(":"):
        raise _error(line, f"{text!r} is a plain scalar some YAML reader would read as another "
                           "type or as syntax: quote it")
    return text


def _double(body: str, text: str, line: int) -> str:
    """A double-quoted string's body with its two escapes read, `\\"` and `\\\\`; any other
    escape, or a quote left bare, is refused."""
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            nxt = body[i + 1:i + 2]
            if nxt not in ('"', "\\"):
                raise _error(line, f"{text!r}: the only escapes read are \\\" and \\\\")
            out.append(nxt)
            i += 2
            continue
        if ch == '"':
            raise _error(line, f"{text!r} has a bare quote inside")
        out.append(ch)
        i += 1
    return "".join(out)


class _Flow:
    """A flow collection on one line, `[...]` or `{...}`, nested as deep as it is written: items
    are scalars (quoted, or plain up to the next `,`, `]` or `}`) or collections."""

    def __init__(self, text: str, line: int) -> None:
        self.text, self.line, self.at = text, line, 0

    def _space(self) -> None:
        while self.at < len(self.text) and self.text[self.at] == " ":
            self.at += 1

    def _item_text(self) -> str:
        """The text of one scalar item: a quoted string whole, or plain up to a delimiter."""
        self._space()
        start = self.at
        if self.at < len(self.text) and self.text[self.at] in "'\"":
            quote = self.text[self.at]
            self.at += 1
            while self.at < len(self.text):
                ch = self.text[self.at]
                if quote == '"' and ch == "\\":
                    self.at += 2
                    continue
                if ch == quote:
                    if quote == "'" and self.text[self.at + 1:self.at + 2] == "'":
                        self.at += 2
                        continue
                    self.at += 1
                    break
                self.at += 1
            return self.text[start:self.at]
        while self.at < len(self.text) and self.text[self.at] not in ",]}":
            self.at += 1
        return self.text[start:self.at].strip()

    def value(self) -> Any:
        self._space()
        ch = self.text[self.at:self.at + 1]
        if ch == "[":
            return self._sequence()
        if ch == "{":
            return self._mapping()
        text = self._item_text()
        if not text:
            raise _error(self.line, "an empty item in a flow collection")
        return _scalar(text, self.line)

    def _close(self, end: str) -> bool:
        """After an item: `True` at the collection's end (consumed), `False` after a comma."""
        self._space()
        ch = self.text[self.at:self.at + 1]
        if ch == end:
            self.at += 1
            return True
        if ch != ",":
            raise _error(self.line, f"{self.text!r}: expected `,` or `{end}` at column "
                                    f"{self.at + 1}")
        self.at += 1
        return False

    def _sequence(self) -> list[Any]:
        self.at += 1
        out: list[Any] = []
        self._space()
        if self.text[self.at:self.at + 1] == "]":
            self.at += 1
            return out
        while True:
            out.append(self.value())
            if self._close("]"):
                return out

    def _mapping(self) -> dict[str, Any]:
        self.at += 1
        out: dict[str, Any] = {}
        self._space()
        if self.text[self.at:self.at + 1] == "}":
            self.at += 1
            return out
        while True:
            self._space()
            colon = self.text.find(": ", self.at)
            if colon < 0 or any(c in self.text[self.at:colon] for c in ",[]{}'\""):
                raise _error(self.line, f"{self.text!r}: an item of a flow mapping is "
                                        "`key: value`, the colon followed by a space")
            key = self.text[self.at:colon].strip()
            self.at = colon + 1
            _put(out, key, self.value(), self.line)
            if self._close("}"):
                return out


def _flow(text: str, line: int) -> Any:
    """A whole flow collection, which must end where the line's value ends."""
    flow = _Flow(text, line)
    value = flow.value()
    flow._space()
    if flow.at != len(text):
        raise _error(line, f"{text!r} has something after its flow collection, or does not close "
                           "on its line")
    return value


def _put(mapping: dict[str, Any], key: str, value: Any, line: int) -> None:
    if not _KEY.match(key):
        raise _error(line, f"{key!r} is not a key here (a letter or `_`, then letters, digits, "
                           "`_`)")
    if any(p.match(key) for p in _TYPED):
        raise _error(line, f"the key {key!r} is one a YAML reader would read as another type "
                           "than a string: name it otherwise")
    if key in mapping:
        raise _error(line, f"the key {key!r} is given twice in one mapping")
    mapping[key] = value


class _Lines:
    """The document's meaningful lines as (indent, text, line number)."""

    def __init__(self, text: str) -> None:
        self.rows: list[tuple[int, str, int]] = []
        for number, raw in enumerate(text.splitlines(), 1):
            body = _strip_comment(raw, number)
            if not body.strip():
                continue
            if body.strip() in ("---", "..."):
                raise _error(number, "a document marker: a manifest is one document")
            indent = len(body) - len(body.lstrip(" "))
            self.rows.append((indent, body.strip(), number))
        self.at = 0

    def peek(self) -> tuple[int, str, int] | None:
        return self.rows[self.at] if self.at < len(self.rows) else None


def _block(lines: _Lines, indent: int) -> Any:
    """The block that starts at the next line, which sits at `indent`."""
    row = lines.peek()
    assert row is not None
    if row[1] == "-" or row[1].startswith("- "):
        return _sequence(lines, indent)
    return _mapping(lines, indent)


def _value_after(lines: _Lines, rest: str, indent: int, line: int, seq_ok: bool) -> Any:
    """What follows `key:` or `-`: the rest of the line, or a block nested under it (deeper,
    or a sequence at the same indent after a key)."""
    if rest:
        return _scalar(rest, line)
    nxt = lines.peek()
    if nxt is not None and (nxt[0] > indent or (seq_ok and nxt[0] == indent and (
            nxt[1] == "-" or nxt[1].startswith("- ")))):
        return _block(lines, nxt[0])
    raise _error(line, "a key with no value (an empty value is null, which no manifest field "
                       "takes)")


def _entry(text: str, line: int) -> tuple[str, str]:
    """`key: rest` (or `key:`), split at the key's own colon."""
    if text.startswith(("'", '"', "?", "&", "*", "!", "{", "[")):
        raise _error(line, f"{text!r}: keys are plain words here, and anchors, aliases, tags and "
                           "complex keys are outside the subset")
    key, sep, rest = text.partition(":")
    if not sep or (rest and not rest.startswith(" ")):
        raise _error(line, f"{text!r} is not `key: value`")
    return key.strip(), rest.strip()


def _mapping(lines: _Lines, indent: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    while (row := lines.peek()) is not None and row[0] >= indent:
        at, text, line = row
        if at > indent:
            raise _error(line, "indented deeper than the mapping it is in")
        if text == "-" or text.startswith("- "):
            raise _error(line, "a sequence item where the mapping expected a key")
        lines.at += 1
        key, rest = _entry(text, line)
        if rest.startswith(("&", "*", "!", "|", ">")):
            raise _error(line, f"{rest!r}: anchors, aliases, tags and block scalars are outside "
                               "the subset")
        _put(out, key, _value_after(lines, rest, indent, line, seq_ok=True), line)
    return out


def _sequence(lines: _Lines, indent: int) -> list[Any]:
    out: list[Any] = []
    while (row := lines.peek()) is not None and row[0] >= indent:
        at, text, line = row
        if at > indent:
            raise _error(line, "indented deeper than the sequence it is in")
        if not (text == "-" or text.startswith("- ")):
            break
        lines.at += 1
        rest = text[1:].strip()
        if rest and not rest.startswith(("'", '"', "[", "{")) and re.match(r"^[^:\s]+:(?: |$)",
                                                                           rest):
            # `- key: value` opens a mapping whose further keys sit under the key's column
            inner = indent + (len(text) - len(rest))
            lines.rows[lines.at - 1] = (inner, rest, line)
            lines.at -= 1
            out.append(_mapping(lines, inner))
            continue
        out.append(_value_after(lines, rest, indent, line, seq_ok=False))
    return out


def loads(text: str) -> Any:
    """The document in `text`: a mapping or a sequence at the top, read whole."""
    lines = _Lines(text.removeprefix("\ufeff"))     # a BOM is the stream's, not the text's
    if lines.peek() is None:
        raise YamlError("the document is empty")
    first = lines.peek()
    assert first is not None
    if first[0] != 0:
        raise _error(first[2], "the document's first line is indented")
    try:
        value = _block(lines, 0)
    except RecursionError:          # the reader recurses once a level: past the interpreter's
        raise YamlError("the document is nested deeper than it is read") from None
    left = lines.peek()
    if left is not None:
        raise _error(left[2], "a line outside the document's top level (check its indent)")
    return value


# ------------------------------------------------------------------ the writer

def key(text: str) -> str:
    """`text` as a key this reader takes: every character outside `_KEY`'s set becomes `_`
    (a device tag `:sub:gfx1` names an asset `sub_gfx1`)."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", text.lstrip(":")) or "_"
    return out if not out[0].isdigit() else f"_{out}"


def _scalar_out(v: Any, hex_int: bool) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v:#x}" if hex_int and v >= 0 else str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _flow_out(v: Any, name: str, hex_keys: tuple[str, ...]) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_flow_out(x, k, hex_keys)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_flow_out(x, name, hex_keys) for x in v) + "]"
    return _scalar_out(v, name in hex_keys)


def _block_out(obj: dict[str, Any], indent: int, hex_keys: tuple[str, ...],
               flat_from: int) -> list[str]:
    out, pad = [], "  " * indent
    for k, v in obj.items():
        nested = isinstance(v, dict) and any(isinstance(x, (dict, list)) for x in v.values())
        if isinstance(v, dict) and (nested or indent < flat_from):
            out.append(f"{pad}{k}:")
            out += _block_out(v, indent + 1, hex_keys, flat_from)
        else:
            out.append(f"{pad}{k}: {_flow_out(v, k, hex_keys)}")
    return out


def dumps(doc: dict[str, Any], head: list[str], hex_keys: tuple[str, ...] = (),
          flat_from: int = 2) -> str:
    """`doc` in the subset `loads` reads: `head` as comment lines first, a mapping in block
    style, a mapping of scalars from depth `flat_from` on one line, lists always on one line,
    every string double-quoted, the integers of `hex_keys` in hex. A top-level mapping is set
    off by a blank line."""
    lines = [f"# {h}" for h in head]
    for k, v in doc.items():
        if isinstance(v, dict):
            lines += ["", f"{k}:"] + _block_out(v, 1, hex_keys, flat_from)
        else:
            lines.append(f"{k}: {_flow_out(v, k, hex_keys)}")
    return "\n".join(lines) + "\n"
