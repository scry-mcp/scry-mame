"""COMMENTS: a text at a place in the program, held as a declaration and shown in MAME's own pane.

The store (`mame_declarations`, kind `comment`) is the record and MAME's disassembly pane a view
of it, fed through the console's `comadd`. A view that fails is said (`unarmable`) and the record
is kept. Why the console and not Lua is REFERENCE.md's, Declarations. The pane is
`mame_comment_pane`'s, the file a project versions `mame_comment_file`'s.
"""

from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path
from typing import Any

from scry_core import fresh, prose
from scry_core import value_format as vf
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_arming as arming
import mame_clear as mclear
import mame_comment_file as cf
import mame_comment_pane as pane
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_read as read
import mame_running as running
import mame_state as st
from mame_state import STATE

# The operators and brackets of MAME's expressions; a name the cpu's table holds is a name
# whatever its characters (a symbol file can carry a C++ one).
_EXPRESSION = re.compile(r"[-+*/%&|^~!<>=()\[\],;]")

# The store is written first, so the change outlives a session that breaks after.
STORE_HELD = ("The declaration store already holds the change, written before the pane was fed, "
              "and the next `start` feeds the pane from it")

# A new comment file is versioned by a project; a file it replaces keeps its own mode.
NEW_FILE_MODE = 0o644


def check_comment_ref(ref: str) -> None:
    """A comment's `ref`: a symbol or a `0x` address as the file writes it, never a pointer."""
    inputs.check_ref(ref)
    text = ref.strip()
    if (fault := cf.ref_fault(text)) is not None:
        raise st.Invalid("bad_argument", f"ref={ref!r} {fault}: a comment's ref is a symbol or a "
                                         "`0x` address, which the comment file writes as it is")
    if vf.parse_pointer(text) is not None:
        raise st.Invalid("bad_argument",
                         f"ref={ref!r} is a pointer, whose target moves at run time: a comment "
                         "names a place, a symbol or a `0x` address")


def expression_fault(ref: str, table: dict[str, int]) -> str | None:
    """`ref` named as an expression, or None, against the table of the comment's cpu."""
    if _EXPRESSION.search(ref) is None or ref.strip().upper() in table:
        return None
    return (f"{ref!r} is an expression: a comment names a place, a symbol or a `0x` address, "
            "and stored as a name the expression would never resolve")


def check_text(text: str) -> None:
    """A comment's text against the comment file's rule."""
    if (fault := cf.text_fault(text)) is not None:
        raise st.Invalid("bad_argument", f"the text {fault}; nothing is stored")


def check_add_comment(ref: str = "", text: str = "", **_: Any) -> None:
    """The machine-independent half of `add`: the ref's shape and the text's rule."""
    check_comment_ref(ref)
    check_text(text)


def check_delete_comment(ref: str = "", **_: Any) -> None:
    """The machine-independent half of `delete`: the ref's shape."""
    check_comment_ref(ref)


def check_save_comments(dest: str = "", **_: Any) -> Path:
    """The machine-independent half of `save`: a file this server may write."""
    return inputs.writable_path("dest", dest)


def check_load_comments(path: str = "", **_: Any) -> None:
    """The machine-independent half of `load`: an absolute path."""
    inputs.absolute("path", path)


def _reached(at_place: list[dec.Declaration], by: str, ref: str) -> dec.Declaration | None:
    """The comment at one place that a call spelling `ref` of kind `by` reaches: the one whose own
    ref it spells, else the one the pane shows, else the first held. A stale row of the other
    kind is out of the last two: its place is another build's, so only its own spelling reaches
    it."""
    store = arming.store()
    own = next((c for c in at_place if store.matches(c, by, ref)), None)
    if own is not None:
        return own
    live = [c for c in at_place if c.by == by or not arming.stale(c)]
    return (next((c for c in live if pane.holds_text_to_clear(c)), None)
            or next(iter(live), None))


def _at_place(d: dec.Declaration) -> dec.Declaration | None:
    """The comment the store holds at `d`'s place, however spelled."""
    place = pane.place(d)
    return _reached([c for c in pane.comments() if pane.place(c) == place], d.by, d.ref)


def _store_fields() -> dict[str, Any]:
    """The store in `start`'s `declarations` shape; `path` alone names a file a tool wrote, so
    the store's own file sits one level down."""
    store = arming.store()
    return {"declarations": {"persistent": store.persistent,
                             "path": (unavailable(dec.SESSION_LIVED_WHY) if store.path is None
                                      else str(store.path))}}


def _apply(adds: list[dec.Declaration] | None = None,
           replaces: list[tuple[dec.Declaration, dec.Declaration]] | None = None,
           removes: list[dec.Declaration] | None = None) -> str | None:
    """The store changed in one write, or why it failed (the change is then held in memory only,
    answered `host_failed`)."""
    try:
        arming.store().apply(adds or [], replaces or [], removes or [])
    except (OSError, st.Invalid, dec.DeclarationError) as e:
        return f"the declaration store could not be written ({e}): the change is held in memory"
    return None


def _host_failed(why: str, note: dict[str, str], **fields: Any) -> dict[str, Any]:
    return menvelope.invalid("host_failed", why, held_in_memory=True, **_store_fields(), **fields,
                             **note)


def row(d: dec.Declaration) -> dict[str, Any]:
    """A comment as `comment_list` gives it: row, text, address once resolved, and state
    (`unresolved`, `stale`, else the last feed's `armed` or `unarmable` with why)."""
    item: dict[str, Any] = {**arming.decl_row(d), "text": d.text}
    res = arming.resolve_decl(d)
    if res.addr is not None:
        item["addr"] = st.hex_addr(res.addr)
    item.update(pane.state(d))
    return item


def _not_shown(item: dict[str, Any]) -> bool:
    return bool(item["state"] != "armed")


def rearm(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """`start`'s half for comments: every comment fed again and listed as `rearmed`, `stale`,
    `unresolved` or `unarmable` (with `why`). Comments sharing a place after a rebuild are all
    kept: the pane shows the first it can show, the others are `unarmable`."""
    out: dict[str, Any] = {key: [] for key in ("rearmed", "stale", "unresolved", "unarmable")}
    if STATE.store is None:
        return out
    places: dict[pane.Place, list[dec.Declaration]] = {}
    for d in pane.comments():
        if arming.resolve_decl(d).addr is None:
            out["unresolved"].append(arming.decl_row(d))
        elif arming.stale(d):
            out["stale"].append(arming.decl_row(d))
        else:
            places.setdefault(pane.place(d), []).append(d)
    notes = pane.feed_in_turn(ses, scratch, places)
    for rows in places.values():
        for d in rows:
            item = row(d)
            if _not_shown(item):
                out["unarmable"].append({**arming.decl_row(d), "why": item.get("why")})
            else:
                out["rearmed"].append(arming.decl_row(d))
    return st.add_note(out, *notes)


def _notes(*parts: str | None) -> dict[str, Any]:
    return st.add_note({}, *parts)


def _persistence_note() -> str | None:
    return None if arming.store().persistent else dec.SESSION_LIVED_WHY


def add_comment(ses: gs.Session, scratch: Path, ref: str, text: str,
                cpu: str = "") -> dict[str, Any]:
    """Body of `comment_write(method="add")`: `text` on `ref` of `cpu`, one comment per place."""
    check_add_comment(ref, text)
    on = cpus.acting(ses, cpu)
    typed = ref.strip()
    if (why := expression_fault(typed, STATE.table(on).table)) is not None:
        raise st.Invalid("bad_argument", f"ref={why}")
    by = arming.decide_by(typed, "auto", on, "comment")
    decl = arming.declare("comment", by, dec.canonical_ref(typed, by), on, text=text)
    res = arming.resolve_decl(decl)
    if res.state == "address" and res.addr is not None:
        read.space_bound(res.addr, 1, on)
    held = _at_place(decl)
    replaced: list[dict[str, Any]] = []
    shown: frozenset[pane.Place] = frozenset()
    if held is not None:
        # The place keeps the row's ref and `by`, so a symbol comment keeps following its symbol.
        replaced.append(row(held))
        shown = frozenset({pane.place(held)}) if pane.holds_text_to_clear(held) else frozenset()
        decl = dataclasses.replace(held, text=text, created_at=decl.created_at,
                                   origin=decl.origin, fingerprint=decl.fingerprint)
        failed = _apply(replaces=[(held, decl)])
    else:
        failed = _apply(adds=[decl])
    try:
        put_back = pane.feed(ses, scratch, [decl], shown)
        rivals = pane.rivals(decl)
        if (not pane.is_shown(decl) and rivals
                and all(not pane.is_shown(c) for c in rivals)):
            # As at `start`: a comment the pane cannot show gives the place to the others.
            place = pane.place(decl)
            put_back = st.join_notes(put_back, *pane.feed_in_turn(
                ses, scratch, {place: rivals},
                frozenset({place}) if pane.holds_text_to_clear(decl) else frozenset()))
    except gs.NotStopped:
        raise
    except gs.SessionError as e:
        return _broke_after_store(e, "comment_write", failed)
    item = row(decl)
    note = _notes(item.get("why") if _not_shown(item) else None, put_back,
                  _persistence_note())
    if failed:
        return _host_failed(failed, note, comment=item, replaced_comments=replaced, cpu=on)
    return menvelope.envelope({"comment": item, "replaced_comments": replaced, **_store_fields(),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY), **note})


def _broke_after_store(error: gs.SessionError, tool: str, failed: str | None) -> dict[str, Any]:
    """A session error after the store was written, saying where the change is: in the store, or,
    when its write `failed`, in memory only, gone at `close`."""
    said = STORE_HELD if failed is None else (
        f"{failed}, so the change lives in this session only and is gone at `close`")
    reply = running.session_error_reply(error, tool, tail=said)
    if reply["code"] != "session_broken":     # a latched reply already carries it in its tail
        reply["message"] = f"{reply['message']}. {said}"
    if failed is not None:
        reply["held_in_memory"] = True
    return reply


def comment_list(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """Body of `comment_list`: every comment, or `cpu`'s; it asks the machine nothing."""
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    rows = [row(d) for d in pane.comments() if only is None or d.cpu == only]
    reply: dict[str, Any] = {"comments": rows[:st.ROWS_SHOWN], "comments_total": len(rows),
                             "truncated": len(rows) > st.ROWS_SHOWN, **_store_fields(),
                             "cpu": or_unavailable(only, st.NO_CPU_NAMED_WHY)}
    if ses.running:
        reply["last_stop"] = STATE.as_of()
    return menvelope.envelope(reply)


def _target(ref: str, on: str) -> dec.Declaration | None:
    """The comment `ref` names on `on`: its own spelling first (so `beef` finds the comment a file
    made by that name on a build lacking it), else the one at the place it resolves to."""
    held = [d for d in pane.comments() if d.cpu == on]
    by = arming.decide_by(ref, "auto", on, "comment")
    own = next((d for d in held if arming.store().matches(d, by, ref)), None)
    if own is not None:
        return own
    place = pane.place(dec.Declaration("comment", by, dec.canonical_ref(ref, by), cpu=on, text="-"))
    return _reached([d for d in held if pane.place(d) == place], by, ref)


def delete_comment(ses: gs.Session, scratch: Path, ref: str, cpu: str = "") -> dict[str, Any]:
    """Body of `comment_write(method="delete")`: the store's removal is the fact; the pane is
    cleared after, or given to another comment at the same place."""
    check_delete_comment(ref)
    on = cpus.acting(ses, cpu)
    target = _target(ref.strip(), on)
    if target is None:
        held = mclear.nothing_matched(ref.strip(), "comment", f" on {on}",
                                      [repr(d.ref) for d in pane.comments() if d.cpu == on],
                                      "deleted")
        return menvelope.invalid("unknown_ref",
                                 f"{held} A comment is found by its own ref or by the place a ref "
                                 "names, in any spelling, and `comment_list` shows each one's "
                                 "`ref` and `addr`")
    gone = row(target)
    pane_holds_it = pane.holds_text_to_clear(target)
    shown_by_its_feed = pane.is_shown(target)
    others = pane.rivals(target)
    failed = _apply(removes=[target])
    pane.forget(target)
    try:
        notes = pane.clear_or_hand_over(ses, scratch, target, gone, on, pane_holds_it,
                                    shown_by_its_feed, others)
    except gs.NotStopped:
        raise
    except gs.SessionError as e:
        return _broke_after_store(e, "comment_write", failed)
    note = _notes(*notes, _persistence_note())
    if failed:
        return _host_failed(failed, note, deleted=gone, cpu=on)
    return menvelope.envelope({"deleted": gone, **_store_fields(),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY), **note})


def _old_rows(path: Path, dest: str) -> list[cf.Row] | None:
    """What `dest` holds now as a comment file, None when nothing is there; anything else is
    refused, since `save` replaces only a file of its own format."""
    if path.is_symlink():
        raise st.Invalid("bad_argument",
                         f"dest={dest!r} is a link: replacing it would put a file where the "
                         "link is; give the file it points at, or another path")
    if not path.exists():
        return None
    if path.is_dir():
        raise st.Invalid("bad_argument", f"dest={dest!r} is a directory")
    if not path.is_file():
        # Before any open: reading a FIFO would wait for a writer and hold the server.
        raise st.Invalid("bad_argument", f"dest={dest!r} is not a regular file (a FIFO, a device "
                                         "or a socket): `comment_write(method=\"save\")` replaces "
                                         "only a comment "
                                         "file")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise st.Invalid("bad_argument", f"dest={dest!r} exists and is not UTF-8 text ({e}): "
                                         "`comment_write(method=\"save\")` replaces only a comment "
                                         "file") from None
    except OSError as e:
        raise files.unreadable("file at dest", dest, e) from None
    if text.replace("\r\n", "\n").split("\n")[0] != cf.HEADER:
        raise st.Invalid("bad_argument",
                         f"dest={dest!r} exists and is not a comment file (its first line is "
                         f"not {cf.HEADER!r}): `comment_write(method=\"save\")` replaces only a "
                         "file of its own "
                         "format, and leaves this one as it is")
    try:
        return cf.parse(text, dest)
    except cf.CommentFileError as e:
        raise st.Invalid("bad_argument", f"{e}: `comment_write(method=\"save\")` replaces a "
                                         "comment file it can "
                                         "read, so the rows it drops can be named") from None


def _row_key(r: cf.Row) -> tuple[str, str]:
    """A row's (ref, cpu) spelled one way, so a re-save does not call a kept row dropped."""
    tags = [c["tag"] for c in (STATE.machine_map or {}).get("cpus", [])]
    try:
        cpu = cpus.match_tag(r.cpu, tags)
    except st.Invalid:
        cpu = r.cpu
    return inputs.match_key(r.ref, "address" if inputs.is_address(r.ref) else "symbol"), cpu


#: A dropped comment row the old file named no cpu for.
NO_ROW_CPU_WHY = "the row named no cpu"


def save_comments(dest: str) -> dict[str, Any]:
    """Body of `comment_write(method="save")`: every comment, every cpu, written to `dest`. A file
    there is replaced only when it is a comment file, and the rows it drops are named."""
    path = check_save_comments(dest)
    # The project's store too, whichever this session holds: a comment file there would refuse
    # every later start. Case folded: a volume may ignore case.
    stores = {os.path.realpath(p).casefold()
              for p in (arming.store().path, dec.default_path()) if p is not None}
    if os.path.realpath(path).casefold() in stores:
        raise st.Invalid("bad_argument", f"dest={dest!r} is the declaration store's own file, "
                                         "which the server reads at every `start`: give the "
                                         "comment file another path")
    old = _old_rows(path, dest)
    rows = [cf.Row(d.ref, d.cpu or "", str(d.created_at), d.text) for d in pane.comments()]
    try:
        text = cf.render(rows)
    except cf.CommentFileError as e:
        raise st.Invalid("host_failed", f"the store holds a comment the comment file cannot "
                                        f"hold ({e}), so nothing was written") from None
    fresh.replace(path, text.encode("utf-8"), "dest:", new_mode=NEW_FILE_MODE)
    kept = {_row_key(r) for r in rows}
    dropped = sorted({(r.ref, r.cpu) for r in old or [] if _row_key(r) not in kept},
                     key=lambda k: (k[1], k[0]))
    return menvelope.envelope({
        "path": str(path), "comments_total": len(rows),
        "dropped_comments": [{"ref": ref, "cpu": cpu or unavailable(NO_ROW_CPU_WHY)}
                             for ref, cpu in dropped[:st.ROWS_SHOWN]],
        "dropped_total": len(dropped), "truncated": len(dropped) > st.ROWS_SHOWN,
        **_notes(None if old is None else
                 f"{dest} held {prose.counted(len(old), 'comment')} and was replaced")})


def _loaded(r: cf.Row, ses: gs.Session, where: str) -> dec.Declaration:
    """A row of the file as a declaration, or the refusal naming its line. `0x` and hex is an
    address, anything else a symbol, so a saved `fade` never returns as `0xfade`."""
    if not r.cpu:
        raise st.Invalid("bad_argument", f"{where}: the cpu column is empty, and every comment "
                                         "here is on a cpu: write its tag (`:maincpu`)")
    try:
        on = cpus.named(ses, r.cpu)
    except st.Invalid as e:
        raise st.Invalid("bad_argument", f"{where}: {e}") from None
    if r.ref[:2].lower() == "0x":
        if not inputs.ADDRESS.fullmatch(r.ref):
            raise st.Invalid("bad_argument", f"{where}: {r.ref!r} starts like an address and is "
                                             "not one: an address in the file is `0x` and hex")
        by, ref = "address", dec.canonical_ref(r.ref, "address")
        try:
            read.space_bound(int(ref, 16), 1, on)
        except st.Invalid as e:
            raise st.Invalid("bad_argument", f"{where}: {e}") from None
    elif ":" in r.ref or vf.parse_pointer(r.ref) is not None:
        raise st.Invalid("bad_argument", f"{where}: {r.ref!r} is neither a symbol nor an "
                                         "address written `0x` and hex: a comment's ref names "
                                         "one place, never a pointer or a cpu-qualified name")
    elif (why := expression_fault(r.ref, STATE.table(on).table)) is not None:
        raise st.Invalid("bad_argument", f"{where}: {why}")
    else:
        by, ref = "symbol", r.ref
    return dec.Declaration("comment", by, ref, created_at=r.created_at,
                           origin=STATE.session_origin, fingerprint=STATE.fingerprint(on),
                           cpu=on, text=r.text)


def load_comments(ses: gs.Session, scratch: Path, path: str) -> dict[str, Any]:
    """Body of `comment_write(method="load")`: the file read into the store, all or nothing. The
    file wins at a place both comment; a place already holding its text is kept, brought to this
    build if stale and fed again if not shown; rows only the store holds stay."""
    check_load_comments(path)
    read = inputs.input_file("path", path, "comment file")
    try:
        # Bytes: a text read would turn a lone CR into a line break before the format refuses it.
        text = read.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise files.not_utf8(path, e) from None
    except OSError as e:
        raise files.unreadable("comment file", path, e) from None
    try:
        rows = cf.parse(text, path)
    except cf.CommentFileError as e:
        raise st.Invalid("bad_argument", f"{e}; nothing was loaded") from None
    decls: list[dec.Declaration] = []
    lines: dict[tuple[str | None, str, str], int] = {}
    for r in rows:
        where = f"{path}:{r.line}"
        d = _loaded(r, ses, where)
        # One row per comment in any spelling of its ref; two a rebuild put at one place both
        # come in, so what `save` writes of such a store reads back.
        key = (d.cpu, d.by, d.ref.upper() if d.by == "symbol" else d.ref)
        if key in lines:
            raise st.Invalid("bad_argument",
                             f"{where}: names the comment line {lines[key]} names ({d.ref} on "
                             f"{d.cpu}): one row per comment; nothing was loaded")
        lines[key] = r.line
        decls.append(d)
    adds: list[dec.Declaration] = []
    replaces: list[tuple[dec.Declaration, dec.Declaration]] = []
    replaced: list[dict[str, Any]] = []
    shown: set[pane.Place] = set()
    refed: list[dec.Declaration] = []
    replaced_owners: set[dec.Owner] = set()
    unchanged = 0
    for d in decls:
        held = _at_place(d)
        if held is None or held.owner in replaced_owners:
            # A row already replaced is not replaced twice: the next file row comes in beside it.
            adds.append(d)
            continue
        replaced_owners.add(held.owner)
        if pane.holds_text_to_clear(held):
            shown.add(pane.place(held))
        if held.text != d.text:
            replaced.append(row(held))
            replaces.append((held, d))
            pane.forget(held)
            continue
        unchanged += 1
        if arming.stale(held):
            # The file's row is trusted for this build, as an added one is.
            new = dataclasses.replace(held, fingerprint=STATE.fingerprint(held.cpu),
                                      origin=STATE.session_origin)
            replaces.append((held, new))
            refed.append(new)
        elif not pane.is_shown(held):
            refed.append(held)
    failed = _apply(adds=adds, replaces=replaces)
    loaded = [*adds, *(new for old, new in replaces if old.text != new.text), *refed]
    places: dict[pane.Place, list[dec.Declaration]] = {}
    for d in loaded:
        places.setdefault(pane.place(d), []).append(d)
    try:
        put_back = st.join_notes(*pane.feed_in_turn(ses, scratch, places, frozenset(shown)))
    except gs.NotStopped:
        raise
    except gs.SessionError as e:
        return _broke_after_store(e, "comment_write", failed)
    unfed = sum(1 for d in loaded if not pane.is_shown(d))
    note = _notes(f"{unfed} of the comments loaded are not shown in MAME's pane: "
                  "`comment_list` says why for each" if unfed else None, put_back,
                  _persistence_note())
    reply: dict[str, Any] = {
        "path": str(read), "parsed": len(rows), "added": len(adds),
        "replaced_comments": replaced[:st.ROWS_SHOWN], "replaced_total": len(replaced),
        "truncated": len(replaced) > st.ROWS_SHOWN, "unchanged": unchanged,
        "comments_total": len(pane.comments())}
    if failed:
        return _host_failed(failed, note, **reply)
    return menvelope.envelope({**reply, **_store_fields(), **note})
