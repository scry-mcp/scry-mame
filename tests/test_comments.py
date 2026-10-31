"""Comments: a text at a place, held as a declaration, fed to MAME's pane and kept in a file.

The pane double answers with the bytes MAME's console gave (`fixtures/comments/PROVENANCE.txt`):
an empty line for a `comadd`, the line `dasm` writes for a commented address, one comment per
address per cpu, and a comment hidden once the bytes under it change. Its fidelity to those
captures is the first case. Every expected file text is written here from the format, never read
back from the writer.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from scry_core import host_program
from scry_core.host_program import MODE_BITS
from scry_core.host_program import absolute as _abs
from server_support import _install  # noqa: E402
from session_doubles import (  # noqa: E402
    IDENTITY_KEYS,
    SessionFields,
    documented,
    refused,
    use_table,
)

from scry_mame import (
    arming,  # noqa: E402
    comments,  # noqa: E402
    launch,  # noqa: E402
    summaries,  # noqa: E402
)
from scry_mame import comment_file as cf  # noqa: E402
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

#: How the one refusal of a relative path begins (scry-core's judge).
R_ABS = "must be an absolute path"

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "comments"
MAIN, SUB = ":maincpu", ":subcpu"
STAMP = "2026-10-02T00:30:00+00:00"
HEAD = cf.HEADER + "\n"
# The instruction text each address decodes to, two of them captured (`dasm.*.txt`).
_DECODED = {0x400: "46FC 2700 move    #$2700, SR", 0x200000: "0000 0000 ori.b   #$0, D0"}


def captured(name: str) -> str:
    return (FIXTURES / name).read_text()


class _Pane(SessionFields):
    """A stopped two-cpu machine whose console holds comments as MAME's does: `comadd` lands on
    the VISIBLE cpu (it names none), a second one at an address replaces the text, `comdelete`
    removes nothing where the bytes moved, `dasm` writes ` // <text>` on a commented line, and the
    stub shows a cpu through `Hc` (`make_visible`) when it has the thread patch."""

    def __init__(self, scratch: Path, threads: bool = True) -> None:
        self.scratch = scratch
        self.threads: dict[int, str] = {1: MAIN, 2: SUB} if threads else {}
        self.visible = MAIN
        self.held: dict[tuple[str, int], str] = {}
        self.moved: set[tuple[str, int]] = set()
        self.commands: list[str] = []
        self.writes = 0
        self.running = False
        self.broken: str | None = None
        self.stop_count = None
        self.payload_chars = 4000
        self.refuse_next = False

    def poll_stop(self, timeout: float) -> None:
        """A running double never stops on its own."""

    def make_visible(self, thread: int) -> None:
        self.commands.append(f"Hc{thread}")
        self.visible = self.threads[thread]

    def console_packet(self, command: str) -> str:
        """The stub's own judge: the `qRcmd` packet, the command hex-encoded, against the
        payload, so a text of multi-byte characters weighs what it weighs on the wire."""
        packet = "qRcmd," + command.encode().hex()
        if len(packet) > self.payload_chars:
            raise gs.CommandTooLong(len(command.encode()), self.payload_chars)
        return packet

    def line(self, cpu: str, addr: int) -> str:
        text = self.held.get((cpu, addr)) if (cpu, addr) not in self.moved else None
        decoded = _DECODED.get(addr, "4E71       nop")
        return f"{addr:06X}: {decoded}" + (f" // {text}" if text is not None else "")

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        if command == "ignore":
            return "Not currently ignoring any devices"
        if command == "cpulist":
            return "\n".join(f"[{'*' if tag == self.visible else ''}{i}] {tag}"
                             for i, tag in enumerate((MAIN, SUB)))
        if m := re.fullmatch(r'comadd 0x([0-9a-f]+),"(.*)"', command):
            if self.refuse_next:
                self.refuse_next = False
                return captured("comadd.unbalanced.txt")
            self.held[self.visible, int(m.group(1), 16)] = m.group(2)
            return captured("comadd.ok.txt")
        if m := re.fullmatch(r"comdelete 0x([0-9a-f]+)", command):
            key = (self.visible, int(m.group(1), 16))
            if key not in self.moved:
                self.held.pop(key, None)
            return captured("comdelete.ok.txt")
        if command.startswith("dasm "):
            name, addr, _length, _flag, cpu = command[5:].split(",")
            (self.scratch / name).write_text(self.line(cpu, int(addr, 16)) + "\n",
                                             encoding="utf-8")       # MAME writes UTF-8
            return ""
        raise AssertionError(f"the double was sent {command!r}")

    def on(self, cpu: str) -> dict[int, str]:
        return {a: t for (c, a), t in self.held.items() if c == cpu}


def _pane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threads: bool = True,
          store: Path | None = None) -> _Pane:
    pane = _Pane(tmp_path, threads)
    _install(monkeypatch, pane, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", pane)
    monkeypatch.setattr(mstate.STATE, "machine_map", {
        "cpus": [{"tag": MAIN}, {"tag": SUB}],
        "spaces": [{"cpu": c, "space": "program", "address_mask": "ffffff"} for c in (MAIN, SUB)]})
    monkeypatch.setattr(mstate.STATE, "fingerprints", {MAIN: "fp-main", SUB: "fp-sub"})
    monkeypatch.setattr(mstate.STATE, "comment_feed", {})
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x400, "FADE": 0x900})
    use_table(monkeypatch, SUB, table={"SND_RESET": 0x400})
    if store is not None:
        monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("m68k-dual key", store))
    return pane


def _two_at_one_place(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Pane:
    """A comment by name and one by address, then a rebuild that moves the name onto the
    address, with the pane emptied as a new start finds it: two comments at one place."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="by name", cpu="maincpu")
    s.comment_write("add", ref="0x900", text="by address", cpu="maincpu")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900})
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    return pane


def _counted(rearm: dict[str, Any]) -> dict[str, Any]:
    """The comments' re-arm with each list of rows counted, its `note` kept."""
    return {k: (len(v) if isinstance(v, list) else v) for k, v in rearm.items()}


def held(cpu: str | None = None) -> list[dec.Declaration]:
    assert mstate.STATE.store is not None
    return [d for d in mstate.STATE.store.declarations()
            if d.kind == "comment" and (cpu is None or d.cpu == cpu)]


# ------------------------------------------------------------------------- the double


def test_the_double_writes_the_lines_mame_wrote(tmp_path: Path) -> None:
    pane = _Pane(tmp_path)
    assert pane.monitor('comadd 0x400,"plain"') == captured("comadd.ok.txt")
    assert pane.line(MAIN, 0x400) + "\n" == captured("dasm.commented.txt")
    assert pane.line(MAIN, 0x200000) + "\n" == captured("dasm.uncommented.txt")


# ------------------------------------------------------------------------------- comment_write add


def test_a_comment_by_symbol_is_stored_and_shown_in_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="irq_vblank", text="vblank: blits first", cpu="maincpu")
    assert out["status"] == "ok", out
    c = out["comment"]
    assert (c["ref"], c["by"], c["cpu"], c["addr"], c["text"], c["state"]) == (
        "irq_vblank", "symbol", MAIN, "0x00000400", "vblank: blits first", "armed"), c
    assert out["replaced_comments"] == [] and out["cpu"] == MAIN
    assert out["declarations"]["persistent"] is False, out
    assert out["declarations"]["path"]["available"] is False, out
    assert "persistent" not in out and "path" not in out, "the store sits under `declarations`"
    assert out["note"] == dec.SESSION_LIVED_WHY, "a session with no symbol file says so"
    assert pane.on(MAIN) == {0x400: "vblank: blits first"}
    assert 'comadd 0x400,"vblank: blits first"' in pane.commands
    assert out["session"]["altered"] is False
    assert out["summary"] == ("comment_write add: irq_vblank at :maincpu 0x00000400, stored, "
                              "dies at close")


def test_a_comment_on_a_cpu_that_is_not_visible_is_fed_there_and_the_visible_one_kept(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="0x400", text="sub reset", cpu="subcpu")
    assert out["comment"]["ref"] == "0x400" and out["comment"]["state"] == "armed", out
    assert pane.on(SUB) == {0x400: "sub reset"} and pane.on(MAIN) == {}
    assert pane.visible == MAIN
    hc = [c for c in pane.commands if c.startswith("Hc")]
    assert hc == ["Hc2", "Hc1"], pane.commands


def test_a_cpu_the_stub_cannot_show_keeps_the_comment_unarmable(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path, threads=False)
    out = s.comment_write("add", ref="0x400", text="sub reset", cpu="subcpu")
    assert out["status"] == "ok" and out["comment"]["state"] == "unarmable", out
    assert "thread patch" in out["comment"]["why"] and "thread patch" in out["note"]
    assert pane.on(SUB) == {} and len(held(SUB)) == 1


def test_one_comment_per_place_a_second_spelling_replaces_the_text_and_keeps_the_ref(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="first", cpu="maincpu")
    out = s.comment_write("add", ref="0x0400", text="second", cpu="maincpu")
    assert [(r["ref"], r["text"]) for r in out["replaced_comments"]] == [("irq_vblank", "first")]
    assert (out["comment"]["ref"], out["comment"]["by"], out["comment"]["text"]) == (
        "irq_vblank", "symbol", "second")
    assert [(d.ref, d.text) for d in held()] == [("irq_vblank", "second")]
    assert pane.on(MAIN) == {0x400: "second"}
    other = s.comment_write("add", ref="0x400", text="the sub's own", cpu="subcpu")
    assert other["replaced_comments"] == [], "the same address on another cpu is another place"


@pytest.mark.parametrize(("text", "why"), [
    ('say "hi"', "`\"`"), ("ends in \\", "ends with `\\`")])
def test_a_text_the_console_cannot_carry_is_stored_and_not_fed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str, why: str) -> None:
    pane = _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="fade", text=text, cpu="maincpu")
    assert out["status"] == "ok" and out["comment"]["state"] == "unarmable", out
    assert why in out["comment"]["why"] and why in out["note"]
    assert not any(c.startswith("comadd") for c in pane.commands)
    assert [d.text for d in held()] == [text]


@pytest.mark.parametrize("text", ["", "a\tb", " a", "a ", "y" * (cf.TEXT_MAX_BYTES + 1)])
def test_a_text_breaking_the_files_rule_is_refused_and_nothing_stored(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> None:
    pane = _pane(monkeypatch, tmp_path)
    out = refused("the text", s.comment_write("add", ref="fade", text=text, cpu="maincpu"))
    assert out["code"] == "bad_argument" and held() == [] and pane.commands == []


def test_a_text_of_exactly_the_bound_is_stored_and_shown(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="fade", text="y" * cf.TEXT_MAX_BYTES, cpu="maincpu")
    assert out["comment"]["state"] == "armed", out


@pytest.mark.parametrize(("ref", "words"), [
    ("1234:5678", "segment"), ("a b", "whitespace"), ("#x", "`#`"), ("[fade]+0x4", "pointer"),
    ("0x1000000", "address mask is 0xffffff")])
def test_a_ref_that_names_no_place_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str, words: str) -> None:
    _pane(monkeypatch, tmp_path)
    out = refused(re.escape(words), s.comment_write("add", ref=ref, text="t", cpu="maincpu"))
    assert out["code"] == "bad_argument" and held() == []


def test_a_name_this_build_lacks_is_kept_unresolved_and_not_fed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="zzz_nowhere", text="later", cpu="maincpu")
    assert out["status"] == "ok" and out["comment"]["state"] == "unresolved", out
    assert "addr" not in out["comment"] and "not a symbol" in out["note"]
    assert pane.on(MAIN) == {}


def test_a_console_that_answers_comadd_keeps_the_comment_unarmable_quoting_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    pane.refuse_next = True
    out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert out["comment"]["state"] == "unarmable" and "unbalanced quotes" in out["comment"]["why"]


def test_a_comadd_past_the_stubs_packet_is_not_sent(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    pane.payload_chars = 40
    out = s.comment_write("add", ref="fade", text="a longer text", cpu="maincpu")
    assert out["comment"]["state"] == "unarmable" and "packet" in out["comment"]["why"]
    assert not any(c.startswith("comadd") for c in pane.commands)


def test_a_pane_that_does_not_read_back_the_text_is_said(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    pane.moved.add((MAIN, 0x900))
    out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert out["comment"]["state"] == "unarmable" and "reads" in out["comment"]["why"], out


@MODE_BITS
def test_a_store_that_cannot_be_written_answers_host_failed_and_holds_the_comment(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    where = tmp_path / "store"
    where.mkdir()
    _pane(monkeypatch, tmp_path, store=where / "decl.json")
    os.chmod(where, 0o500)
    try:
        out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    finally:
        os.chmod(where, 0o700)
    refused("could not be written", out)
    assert out["code"] == "host_failed" and out["held_in_memory"] is True
    assert out["declarations"]["path"] == str(where / "decl.json")
    assert [d.text for d in held()] == ["t"], "held in memory for this session"


def test_a_persistent_store_keeps_the_comment_for_the_next_session(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "decl.json"
    _pane(monkeypatch, tmp_path, store=path)
    out = s.comment_write("add", ref="irq_vblank", text="kept", cpu="maincpu")
    assert out["declarations"] == {"persistent": True, "path": str(path)} and "note" not in out
    saved = json.loads(path.read_text())["m68k-dual key"]
    assert [(d["kind"], d["ref"], d["text"], d["cpu"]) for d in saved] == [
        ("comment", "irq_vblank", "kept", MAIN)]
    again = dec.DeclarationStore("m68k-dual key", path).declarations()
    assert [(d.ref, d.text) for d in again] == [("irq_vblank", "kept")]


# ------------------------------------------------------------------------------ comment_list


def test_the_list_gives_each_comment_with_its_state_by_cpu(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="main", cpu="maincpu")
    s.comment_write("add", ref="0x400", text="sub", cpu="subcpu")
    s.comment_write("add", ref="zzz", text="nowhere", cpu="maincpu")
    out = s.comment_list()
    assert [(c["ref"], c["cpu"], c["state"]) for c in out["comments"]] == [
        ("irq_vblank", MAIN, "armed"), ("0x400", SUB, "armed"), ("zzz", MAIN, "unresolved")]
    assert out["comments_total"] == 3 and out["truncated"] is False
    assert out["cpu"]["available"] is False, out
    sub = s.comment_list(cpu="subcpu")
    assert [c["text"] for c in sub["comments"]] == ["sub"] and sub["cpu"] == SUB
    assert out["summary"] == "comment_list: 3 comments"
    assert sub["summary"] == "comment_list: 1 comment on :subcpu"


def test_a_raw_address_over_another_build_is_listed_stale_and_not_fed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "another build")
    (only,) = s.comment_list()["comments"]
    assert only["state"] == "stale" and "another build" in only["why"]
    pane.held.clear()
    counts = _counted(comments.rearm(pane, tmp_path))  # type: ignore[arg-type]
    assert counts == {"rearmed": 0, "stale": 1, "unresolved": 0, "unarmable": 0}
    assert pane.held == {}


def test_a_re_armed_comment_row_names_whose_it_is_and_how_old(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The comments' half of `start`'s account gives each row the one `arming.decl_row` builds
    for ITS declaration: the one fed, the stale one and the one this build cannot place."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    s.comment_write("add", ref="0x904", text="u", cpu="maincpu")
    s.comment_write("add", ref="zzz", text="nowhere", cpu="maincpu")
    fed_d, stale_d, lacking_d = held()
    monkeypatch.setattr(arming, "stale", lambda d: d.ref == stale_d.ref)
    out = comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    for (row,), decl in ((out["rearmed"], fed_d), (out["stale"], stale_d),
                         (out["unresolved"], lacking_d)):
        assert {k: row[k] for k in IDENTITY_KEYS} == arming.decl_row(decl), row


def test_a_full_page_of_full_texts_stays_inside_the_reply_budget(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    for i in range(mstate.ROWS_SHOWN + 3):
        s.comment_write("add", ref=f"{0x1000 + 4 * i:#x}", text="ñ" * (cf.TEXT_MAX_BYTES // 2),
                        cpu="maincpu")
    out = s.comment_list()
    assert len(out["comments"]) == mstate.ROWS_SHOWN and out["truncated"] is True
    assert out["comments_total"] == mstate.ROWS_SHOWN + 3
    assert len(json.dumps(out)) < mstate.REPLY_BUDGET_CHARS


def test_the_list_answers_on_a_running_machine_without_asking_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="main", cpu="maincpu")
    pane.running, pane.commands = True, []
    out = s.comment_list(cpu="maincpu")
    every = s.comment_list()
    assert out["status"] == "ok" and "running" not in out and len(out["comments"]) == 1
    assert every["status"] == "ok" and every["comments_total"] == 1
    assert pane.commands == [], "the list reads the store and the last feed, not the machine"


@pytest.mark.parametrize("method", ["add", "delete", "load"])
def test_the_three_that_feed_the_pane_refuse_on_a_running_machine(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, method: str) -> None:
    pane = _pane(monkeypatch, tmp_path)
    (tmp_path / "f.tsv").write_text(HEAD)
    pane.running = True
    args = {"add": {"ref": "fade", "text": "t"}, "delete": {"ref": "fade"},
            "load": {"path": str(tmp_path / "f.tsv")}}[method]
    out = s.comment_write(method, **args)
    assert out["status"] == "INVALID" and out["code"] == "not_stopped", out


# ---------------------------------------------------------------------------- comment_write delete


def test_a_delete_removes_the_comment_at_the_place_however_it_was_spelled(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="snd_reset", text="sub", cpu="subcpu")
    pane.commands = []
    out = s.comment_write("delete", ref="0x0400", cpu="subcpu")
    assert out["status"] == "ok" and out["deleted"]["ref"] == "snd_reset", out
    assert held() == [] and pane.on(SUB) == {}
    assert [c for c in pane.commands if not c.startswith(("cpulist", "dasm"))] == [
        "Hc2", "comdelete 0x400", "Hc1"]
    assert out["summary"] == "comment_write delete: 0x0400 at :subcpu 0x00000400 deleted"


def test_a_delete_with_nothing_there_names_the_comments_held(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="main", cpu="maincpu")
    out = refused("'0x1234' matches no comment on :maincpu", s.comment_write("delete", ref="0x1234",
                                                                             cpu="maincpu"))
    assert out["code"] == "unknown_ref" and "'irq_vblank'" in out["message"]
    assert "`comment_list`" in out["message"], "the family names its own lister"
    assert len(held()) == 1


def test_a_comment_over_bytes_that_moved_stays_in_the_pane_and_the_delete_says_so(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    original = pane.monitor

    def keep(command: str, timeout: float = 10.0) -> str:
        # MAME's `comdelete` over bytes that changed since the `comadd` removes nothing
        if command.startswith("comdelete"):
            pane.commands.append(command)
            return captured("comdelete.ok.txt")
        return original(command, timeout)

    pane.monitor = keep  # type: ignore[method-assign]
    out = s.comment_write("delete", ref="fade", cpu="maincpu")
    assert out["status"] == "ok" and held() == []
    assert "still shows the text" in out["note"] and "until `close`" in out["note"]


# ------------------------------------------------------------------------------ comment_write save


def _three(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="main vblank", cpu="maincpu")
    s.comment_write("add", ref="0x400", text="sub reset", cpu="subcpu")
    s.comment_write("add", ref="0x500", text="clears the list", cpu="maincpu")


def _stamps() -> dict[str, str]:
    return {d.ref: str(d.created_at) for d in held()}


def test_save_writes_the_file_sorted_and_byte_exact(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    dest = tmp_path / "game.comments.tsv"
    out = s.comment_write("save", dest=str(dest))
    assert out["status"] == "ok" and out["comments_total"] == 3, out
    assert out["path"] == str(dest) and "dest" not in out, "the file written is `path`"
    t = _stamps()
    assert dest.read_bytes() == (HEAD + f"0x500\t:maincpu\t{t['0x500']}\tclears the list\n"
                                 f"irq_vblank\t:maincpu\t{t['irq_vblank']}\tmain vblank\n"
                                 f"0x400\t:subcpu\t{t['0x400']}\tsub reset\n").encode()
    assert out["dropped_comments"] == [] and out["dropped_total"] == 0 and "note" not in out
    assert out["summary"] == f"comment_write save: 3 comments to {dest}"


def test_save_replaces_its_own_file_and_names_the_rows_it_drops(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    dest = tmp_path / "game.comments.tsv"
    s.comment_write("save", dest=str(dest))
    s.comment_write("delete", ref="0x500", cpu="maincpu")
    out = s.comment_write("save", dest=str(dest))
    assert out["status"] == "ok" and out["comments_total"] == 2
    assert out["dropped_comments"] == [{"ref": "0x500", "cpu": MAIN}] and out["dropped_total"] == 1
    assert "held 3 comments" in out["note"]
    assert dest.read_text().count("\n") == 3


def test_save_refuses_a_file_that_is_not_a_comment_file_and_leaves_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    other = tmp_path / "notes.tsv"
    other.write_bytes(b"ref\tsomething else\n")
    refused("not a comment file", s.comment_write("save", dest=str(other)))
    assert other.read_bytes() == b"ref\tsomething else\n"
    link = tmp_path / "link.tsv"
    link.symlink_to(tmp_path / "nowhere.tsv")
    refused("is a link", s.comment_write("save", dest=str(link)))
    (tmp_path / "dir.tsv").mkdir()
    refused("is a directory", s.comment_write("save", dest=str(tmp_path / "dir.tsv")))


def test_save_judges_the_path_before_the_session(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    refused(R_ABS, s.comment_write("save", dest="relative.tsv"))
    assert s.comment_write("save", dest=str(tmp_path / "x.tsv"))["code"] == "no_session"
    refused(R_ABS, s.comment_write("load", path="relative.tsv"))
    refused("pointer", s.comment_write("add", ref="[fade]+0x4", text="t"))
    refused("ref='' is empty", s.comment_write("delete", ref=""))
    refused("the text", s.comment_write("add", ref="fade", text=""))
    assert s.comment_write("load", path=str(tmp_path / "x.tsv"))["code"] == "no_session"


def test_save_answers_on_a_running_machine(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    pane.running, pane.commands = True, []
    out = s.comment_write("save", dest=str(tmp_path / "r.tsv"))
    assert out["status"] == "ok" and out["comments_total"] == 1 and pane.commands == []


# ------------------------------------------------------------------------------ comment_write load


def test_load_into_an_empty_store_keeps_the_files_stamps_and_feeds_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"irq_vblank\t:maincpu\t{STAMP}\tmain\n0x0400\t:subcpu\t{STAMP}\tsub\n"
                   f"fade\t:maincpu\t{STAMP}\ta symbol, not 0xfade\n"
                   f"beef\t:maincpu\t{STAMP}\ta symbol this build lacks, not 0xbeef\n")
    out = s.comment_write("load", path=str(src))
    assert out["status"] == "ok", out
    assert out["path"] == str(src) and "source" not in out, "the file read is the reply's `path`"
    assert "added_total" not in out and "unchanged_total" not in out
    assert (out["parsed"], out["added"], out["unchanged"], out["replaced_total"],
            out["comments_total"]) == (4, 4, 0, 0, 4)
    assert {(d.ref, d.by, d.created_at, d.origin, d.fingerprint) for d in held()} == {
        ("irq_vblank", "symbol", STAMP, "s1", "fp-main"), ("0x400", "address", STAMP, "s1",
                                                            "fp-sub"),
        ("fade", "symbol", STAMP, "s1", "fp-main"), ("beef", "symbol", STAMP, "s1", "fp-main")}
    assert "1 of the comments loaded are not shown" in out["note"], "beef is unresolved"
    assert pane.on(MAIN) == {0x400: "main", 0x900: "a symbol, not 0xfade"}
    assert pane.on(SUB) == {0x400: "sub"}
    assert out["summary"] == "comment_write load: 4 read, 4 added, 0 replaced"


def test_load_lets_the_file_win_and_returns_each_row_it_replaced(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    dest = tmp_path / "game.comments.tsv"
    s.comment_write("save", dest=str(dest))
    s.comment_write("add", ref="irq_vblank", text="changed here", cpu="maincpu")
    s.comment_write("add", ref="0x600", text="only in the store", cpu="maincpu")
    out = s.comment_write("load", path=str(dest))
    assert [(r["ref"], r["text"]) for r in out["replaced_comments"]] == [
        ("irq_vblank", "changed here")]
    assert (out["added"], out["unchanged"], out["comments_total"]) == (0, 2, 4)
    assert {d.ref: d.text for d in held()}["irq_vblank"] == "main vblank"
    assert "0x600" in {d.ref for d in held()}, "a row only the store holds stays"


@pytest.mark.parametrize(("body", "words"), [
    ("# comments v2\n", ":1: the first line"),
    (HEAD + f"x\t:maincpu\t{STAMP}\n", ":2: a row is"),
    (HEAD + f"x\t:maincpu\t{STAMP}\ta\nx\t:maincpu\t{STAMP}\tb\n", ":3: 'x' on :maincpu again"),
    (HEAD + f"0x400\t:maincpu\t{STAMP}\ta\n0x0400\t:maincpu\t{STAMP}\tb\n",
     ":3: names the comment line 2 names"),
    (HEAD + f"main+4\t:maincpu\t{STAMP}\ta\n", ":2: 'main+4' is an expression"),
    (HEAD + f"x\t\t{STAMP}\ta\n", ":2: the cpu column is empty"),
    (HEAD + f"x\t:nocpu\t{STAMP}\ta\n", ":2: no cpu ':nocpu'"),
    (HEAD + f"0x1000000\t:maincpu\t{STAMP}\ta\n", ":2: 0x1 bytes from 0x1000000"),
    (HEAD + f"0xZZ\t:maincpu\t{STAMP}\ta\n", ":2: '0xZZ' starts like an address"),
])
def test_load_refuses_a_bad_file_whole_naming_the_line(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str, words: str) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="before", cpu="maincpu")
    src = tmp_path / "bad.tsv"
    src.write_text(body)
    out = s.comment_write("load", path=str(src))
    assert refused(re.escape(f"{src}{words}"), out)["code"] == "bad_argument"
    assert [(d.ref, d.text) for d in held()] == [("fade", "before")], "the store is unchanged"


def test_what_save_writes_load_reads_back_into_a_fresh_store(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    dest = tmp_path / "game.comments.tsv"
    s.comment_write("save", dest=str(dest))
    before = {(d.ref, d.cpu, d.created_at, d.text) for d in held()}
    _pane(monkeypatch, tmp_path)
    assert held() == []
    s.comment_write("load", path=str(dest))
    assert {(d.ref, d.cpu, d.created_at, d.text) for d in held()} == before


# ---------------------------------------------------------------------------- start's re-arm


def test_start_feeds_every_comment_again_and_counts_them(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="main", cpu="maincpu")
    s.comment_write("add", ref="0x400", text="sub", cpu="subcpu")
    s.comment_write("add", ref="zzz", text="nowhere", cpu="maincpu")
    s.comment_write("add", ref="fade", text='a "quote"', cpu="maincpu")
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    counts = _counted(comments.rearm(pane, tmp_path))  # type: ignore[arg-type]
    assert counts == {"rearmed": 2, "stale": 0, "unresolved": 1, "unarmable": 1}
    assert pane.on(MAIN) == {0x400: "main"} and pane.on(SUB) == {0x400: "sub"}
    assert pane.visible == MAIN


def test_two_comments_a_rebuild_put_at_one_place_are_kept_and_the_second_said(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _two_at_one_place(monkeypatch, tmp_path)
    counts = _counted(comments.rearm(pane, tmp_path))  # type: ignore[arg-type]
    assert counts == {"rearmed": 1, "stale": 0, "unresolved": 0, "unarmable": 1}
    rows = {c["ref"]: c for c in s.comment_list()["comments"]}
    assert rows["irq_vblank"]["state"] == "armed"
    assert rows["0x900"]["state"] == "unarmable" and "'irq_vblank'" in rows["0x900"]["why"]


def test_start_pins_the_comment_directory_in_the_scratch() -> None:
    """MAME writes the comments it holds into `comment_directory` on every exit of a `-debug`
    machine; pinned on the command line, an ini given through `inipath` cannot move that file
    where a later plain MAME would show a deleted comment again."""
    cmd = launch.build_command("mame", "m68k-dual", _abs("roms"), 1234, [], _abs("tmp", "scratch"),
                               inipath=_abs("ini"), state_dir=_abs("state"))
    i = cmd.index("-comment_directory")
    assert cmd[i + 1] == _abs("tmp", "scratch", "comments")
    assert i < cmd.index("-inipath"), "beside the other pinned directories"


# ------------------------------------------------------------------------------- summaries


def test_each_summary_reads_its_reply() -> None:
    add = {"comment": {"ref": "x", "cpu": MAIN, "addr": "0x00000400"},
           "declarations": {"persistent": True}}
    assert summaries.add_comment({"ref": "x"}, add) == (
        "x at :maincpu 0x00000400, stored, persistent")
    loose = {"comment": {"ref": "zzz", "cpu": MAIN}, "declarations": {"persistent": False}}
    assert summaries.add_comment({"ref": "zzz"}, loose) == (
        "zzz at :maincpu unresolved, stored, dies at close")
    assert summaries.load_comments({}, {"parsed": 4, "added": 1, "replaced_total": 2}) == (
        "4 read, 1 added, 2 replaced")


# ----------------------------------------------------- what the review of the tools found


def test_a_replacement_the_pane_cannot_show_clears_the_old_text_there(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The store says what the pane shows: a text replaced by one the console cannot carry must
    not leave the old text on MAME's line."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="old text", cpu="maincpu")
    out = s.comment_write("add", ref="fade", text='a "quote"', cpu="maincpu")
    assert out["comment"]["state"] == "unarmable"
    assert pane.on(MAIN) == {}, "the old text is cleared from the pane"


def test_deleting_a_comment_that_landed_unread_still_clears_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    real = pane.line
    monkeypatch.setattr(pane, "line", lambda cpu, addr: real(cpu, addr) + "?")
    out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert out["comment"]["state"] == "unarmable" and pane.on(MAIN) == {0x900: "t"}
    s.comment_write("delete", ref="fade", cpu="maincpu")
    assert pane.on(MAIN) == {}, "the comadd landed, so the delete clears it"


def test_deleting_the_second_comment_at_a_shared_place_leaves_the_first_in_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _two_at_one_place(monkeypatch, tmp_path)
    comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    pane.commands = []
    s.comment_write("delete", ref="0x900", cpu="maincpu")
    assert not any(c.startswith("comdelete") for c in pane.commands), pane.commands
    assert pane.on(MAIN) == {0x900: "by name"}


def test_an_unresolved_name_spelled_like_hex_is_deleted_by_its_name(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"beef\t:maincpu\t{STAMP}\ta symbol this build lacks\n")
    s.comment_write("load", path=str(src))
    out = s.comment_write("delete", ref="beef", cpu="maincpu")
    assert out["status"] == "ok" and out["deleted"]["ref"] == "beef", out
    assert held() == []


def test_a_comment_kept_by_a_name_that_became_ambiguous_is_still_deleted_by_that_name(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="snd_reset", text="sub", cpu="subcpu")
    names = gs.Names()
    for at in (0x400, 0x900):
        names.add("SND_RESET", at)
    monkeypatch.setitem(mstate.STATE.tables, SUB, gs.SymbolTable(names, {}, "yaml"))
    out = s.comment_write("delete", ref="snd_reset", cpu="subcpu")
    assert out["status"] == "ok" and out["deleted"]["ref"] == "snd_reset", out
    assert held() == []


def test_load_brings_a_stale_comment_back_for_this_build_and_feeds_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x900", text="same text", cpu="maincpu")
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "the new build")
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x900\t:maincpu\t{STAMP}\tsame text\n")
    out = s.comment_write("load", path=str(src))
    assert out["unchanged"] == 1 and out["added"] == 0
    (only,) = s.comment_list()["comments"]
    assert only["state"] == "armed" and pane.on(MAIN) == {0x900: "same text"}, only


def test_a_store_file_that_went_bad_answers_host_failed_rather_than_escaping(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "decl.json"
    _pane(monkeypatch, tmp_path, store=path)
    path.write_text("{")
    out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert out["code"] == "host_failed" and out["held_in_memory"] is True, out


@MODE_BITS
@pytest.mark.parametrize("tool", ["comment_write delete", "comment_write load"])
def test_delete_and_load_answer_host_failed_when_the_store_cannot_be_written(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str) -> None:
    where = tmp_path / "store"
    where.mkdir()
    _pane(monkeypatch, tmp_path, store=where / "decl.json")
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x904\t:maincpu\t{STAMP}\tu\n")
    os.chmod(where, 0o500)
    try:
        out = (s.comment_write("delete", ref="fade",
                               cpu="maincpu") if tool == "comment_write delete"
               else s.comment_write("load", path=str(src)))
    finally:
        os.chmod(where, 0o700)
    assert out["code"] == "host_failed" and out["held_in_memory"] is True, out


def test_a_symbol_spelled_0x_without_hex_is_refused_since_no_file_could_hold_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    out = refused("0x", s.comment_write("add", ref="0xzz", text="t", cpu="maincpu"))
    assert out["code"] == "bad_argument" and held() == []


def test_no_cpu_named_is_the_visible_one_and_none_visible_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    pane.visible = SUB
    out = s.comment_write("add", ref="0x400", text="on the visible")
    assert out["comment"]["cpu"] == SUB and pane.on(SUB) == {0x400: "on the visible"}
    assert s.comment_write("delete", ref="0x400")["deleted"]["cpu"] == SUB
    real = pane.monitor
    monkeypatch.setattr(pane, "monitor",
                        lambda c, timeout=10.0: "" if c == "cpulist" else real(c, timeout))
    out = s.comment_write("add", ref="0x400", text="t")
    assert out["code"] == "unexpected_answer" and held() == []


def test_a_cpu_the_machine_lacks_is_refused_by_name(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    for out in (s.comment_write("add", ref="0x400", text="t", cpu="nocpu"),
                s.comment_write("delete", ref="0x400", cpu="nocpu"), s.comment_list(cpu="nocpu")):
        assert out["code"] == "unknown_ref" and "nocpu" in out["message"], out


def test_a_sub_cpu_comment_held_first_still_lands_every_comment_on_its_own_cpu(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x400", text="sub first", cpu="subcpu")
    s.comment_write("add", ref="0x900", text="main second", cpu="maincpu")
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    assert pane.on(SUB) == {0x400: "sub first"} and pane.on(MAIN) == {0x900: "main second"}
    assert pane.visible == MAIN


def test_a_visible_cpu_that_cannot_be_put_back_is_said_and_the_comment_kept(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    real = pane.make_visible

    def back_refused(thread: int) -> None:
        if thread == 1 and pane.visible == SUB:
            raise gs.Refused("E01")
        real(thread)

    monkeypatch.setattr(pane, "make_visible", back_refused)
    out = s.comment_write("add", ref="0x400", text="sub", cpu="subcpu")
    assert out["status"] == "ok" and out["comment"]["state"] == "armed"
    assert "could not be made visible again" in out["note"] and ":subcpu" in out["note"]


def test_the_pages_of_dropped_and_replaced_rows_are_cut_and_counted(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    many = mstate.ROWS_SHOWN + 3
    dest = tmp_path / "many.tsv"
    dest.write_text(HEAD + "".join(f"0x{0x1000 + 4 * i:x}\t:maincpu\t{STAMP}\tt{i}\n"
                                   for i in range(many)))
    out = s.comment_write("save", dest=str(dest))
    assert (out["dropped_total"], out["truncated"], len(out["dropped_comments"])) == (
        many, True, mstate.ROWS_SHOWN)
    for i in range(many):
        s.comment_write("add", ref=f"{0x1000 + 4 * i:#x}", text=f"store {i}", cpu="maincpu")
    src = tmp_path / "back.tsv"
    src.write_text(HEAD + "".join(f"0x{0x1000 + 4 * i:x}\t:maincpu\t{STAMP}\tfile {i}\n"
                                  for i in range(many)))
    out = s.comment_write("load", path=str(src))
    assert (out["replaced_total"], out["truncated"], len(out["replaced_comments"])) == (
        many, True, mstate.ROWS_SHOWN)


def test_save_refuses_its_own_format_with_a_row_it_cannot_read(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    dest = tmp_path / "bad.tsv"
    dest.write_text(HEAD + "only one column\n")
    out = refused("2: a row is", s.comment_write("save", dest=str(dest)))
    assert out["code"] == "bad_argument" and dest.read_text() == HEAD + "only one column\n"
    latin = tmp_path / "latin.tsv"
    latin.write_bytes(HEAD.encode() + b"x\t:maincpu\t2026-10-02T00:30:00+00:00\t\xe9\n")
    refused(r"^dest: .*latin\.tsv is not UTF-8 text: byte \d+ \(b'.*'\) "
            r".*replaces only a comment file", s.comment_write("save", dest=str(latin)))


@MODE_BITS
def test_a_new_comment_file_is_readable_by_others_and_a_replaced_one_keeps_its_mode(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    fresh_file = tmp_path / "new.tsv"
    s.comment_write("save", dest=str(fresh_file))
    assert fresh_file.stat().st_mode & 0o777 == 0o644
    os.chmod(fresh_file, 0o640)
    s.comment_write("save", dest=str(fresh_file))
    assert fresh_file.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("ref", ["1234:5678", "[fade]+0x4"])
def test_load_refuses_a_row_that_is_neither_a_symbol_nor_an_address(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str) -> None:
    _pane(monkeypatch, tmp_path)
    src = tmp_path / "bad.tsv"
    src.write_text(HEAD + f"{ref}\t:maincpu\t{STAMP}\tt\n")
    out = refused("is neither a symbol nor an address written `0x` and hex: a comment's ref names "
                  "one place, never a pointer or a cpu-qualified name",
                  s.comment_write("load", path=str(src)))
    assert out["code"] == "bad_argument" and held() == []


def test_a_replaced_text_takes_this_sessions_stamp_and_an_unresolved_name_is_one_place(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="zzz", text="first", cpu="maincpu")
    (before,) = held()
    monkeypatch.setattr(mstate, "now", lambda: "2027-01-01T00:00:00+00:00")
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "rebuilt")
    out = s.comment_write("add", ref="ZZZ", text="second", cpu="maincpu")
    (after,) = held()
    assert len(out["replaced_comments"]) == 1 and after.ref == "zzz"
    assert (after.created_at, after.fingerprint) == ("2027-01-01T00:00:00+00:00", "rebuilt")
    assert before.created_at != after.created_at


def test_a_symbol_comment_follows_its_name_across_a_build_and_is_never_stale(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="follows", cpu="maincpu")
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "rebuilt")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x940})
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    assert _counted(comments.rearm(pane, tmp_path))["rearmed"] == 1  # type: ignore[arg-type]
    assert pane.on(MAIN) == {0x940: "follows"}


def test_start_says_how_many_comments_it_placed_again() -> None:
    reply = {"system": "m68k-dual", "binary": "/opt/mame/mame", "binary_origin": "argument",
             "rom_check": "OK", "symbols_total": 3, "pc": "0x0", "machine":
             {"cpus": 2, "screens": 1, "rom_files": 0, "regions": 0, "shares": 0},
             "declarations": {"comments": {"rearmed": [{"ref": "a", "cpu": MAIN}] * 2}},
             "start_retries": []}
    assert "2 comments re-placed" in summaries.start({}, reply)
    reply["declarations"] = {}
    assert "comment" not in summaries.start({}, reply)


def test_deleting_the_shown_comment_at_a_shared_place_shows_the_other(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _two_at_one_place(monkeypatch, tmp_path)
    comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "by address"}
    assert [c["state"] for c in s.comment_list()["comments"]] == ["armed"]


def test_load_feeds_again_a_comment_holding_the_files_text_that_the_pane_lacks(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    real = pane.line
    monkeypatch.setattr(pane, "line", lambda cpu, addr: real(cpu, addr) + "?")
    s.comment_write("add", ref="0x904", text="same", cpu="maincpu")
    monkeypatch.setattr(pane, "line", real)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x904\t:maincpu\t{STAMP}\tsame\n")
    out = s.comment_write("load", path=str(src))
    assert out["unchanged"] == 1
    assert s.comment_list()["comments"][0]["state"] == "armed"


@MODE_BITS
def test_a_store_that_cannot_be_written_keeps_the_notes_of_the_call(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    where = tmp_path / "store"
    where.mkdir()
    _pane(monkeypatch, tmp_path, store=where / "decl.json")
    os.chmod(where, 0o500)
    try:
        out = s.comment_write("add", ref="fade", text='a "quote"', cpu="maincpu")
    finally:
        os.chmod(where, 0o700)
    assert out["code"] == "host_failed" and "`\"`" in out["note"], out


# ------------------------------------------------- the failure paths the coverage pass found


def test_load_refuses_a_file_that_is_not_utf8(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    src = tmp_path / "latin.tsv"
    src.write_bytes(HEAD.encode() + b"x\t:maincpu\t2026-10-02T00:30:00+00:00\t\xe9\n")
    out = refused("not UTF-8", s.comment_write("load", path=str(src)))
    assert out["code"] == "bad_argument" and held() == []


def test_a_refusal_of_a_load_names_the_path_it_resolved_not_the_one_typed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "latin.tsv").write_bytes(
        HEAD.encode() + b"x\t:maincpu\t2026-10-02T00:30:00+00:00\t\xe9\n")
    out = s.comment_write("load", path="~/latin.tsv")
    assert out["code"] == "bad_argument" and (
        f"path: {tmp_path / 'latin.tsv'} is not UTF-8") in out["message"], out


def test_a_save_the_disk_refuses_answers_host_failed_and_leaves_no_temporary(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _three(monkeypatch, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def refused_replace(src: str, dst: str) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", refused_replace)
    out = s.comment_write("save", dest=str(out_dir / "c.tsv"))
    assert out["code"] == "host_failed" and "No space left" in out["message"], out
    assert list(out_dir.iterdir()) == [], "the temporary file is removed"


def test_a_stored_comment_the_file_cannot_hold_writes_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    assert mstate.STATE.store is not None
    mstate.STATE.store.apply(adds=[dec.Declaration("comment", "symbol", "fade", cpu=MAIN,
                                                    text="no stamp")])
    dest = tmp_path / "c.tsv"
    out = s.comment_write("save", dest=str(dest))
    assert out["code"] == "host_failed" and "created_at" in out["message"], out
    assert not dest.exists()


def test_a_pane_that_cannot_be_read_back_keeps_the_comment_unarmable_and_landed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    real = pane.monitor

    def no_listing(command: str, timeout: float = 10.0) -> str:
        return "" if command.startswith("dasm ") else real(command, timeout)

    monkeypatch.setattr(pane, "monitor", no_listing)
    out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert out["comment"]["state"] == "unarmable"
    assert "could not be read back" in out["comment"]["why"]
    monkeypatch.setattr(pane, "monitor", real)
    s.comment_write("delete", ref="fade", cpu="maincpu")
    assert pane.on(MAIN) == {}, "the comadd landed, so the delete clears it"


def test_a_delete_on_a_cpu_the_stub_cannot_show_says_the_pane_was_not_cleared(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x400", text="sub", cpu="subcpu")
    pane.threads = {}
    out = s.comment_write("delete", ref="0x400", cpu="subcpu")
    assert out["status"] == "ok" and held() == []
    assert "the pane could not be cleared" in out["note"], out


def test_a_start_with_no_store_counts_nothing(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "store", None)
    assert _counted(comments.rearm(pane, tmp_path)) == {  # type: ignore[arg-type]
        "rearmed": 0, "stale": 0, "unresolved": 0, "unarmable": 0}


# -------------------------------------- one comment per place, in the pane and in the list


def _stale_raw_under_a_moved_symbol(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                    raw_first: bool) -> _Pane:
    """A raw comment at 0x900 and one by name, then a rebuild that moves the name onto 0x900
    and changes the build, so the raw one is stale, with the pane as a new start leaves it."""
    pane = _pane(monkeypatch, tmp_path)
    rows = [("0x900", "old raw"), ("irq_vblank", "by name")]
    for ref, text in rows if raw_first else rows[::-1]:
        s.comment_write("add", ref=ref, text=text, cpu="maincpu")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900, "FADE": 0x904})
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "fp-main-rebuilt")
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    counts = _counted(comments.rearm(pane, tmp_path))  # type: ignore[arg-type]
    assert (counts["rearmed"], counts["stale"]) == (1, 1), counts
    assert pane.on(MAIN) == {0x900: "by name"}
    return pane


def _states() -> dict[str, tuple[str, str]]:
    return {c["ref"]: (c["state"], c["text"]) for c in s.comment_list()["comments"]}


def _rebuilt_onto_one_place(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, first: str,
                            second: str) -> tuple[_Pane, dict[str, Any]]:
    """`irq_vblank` commented `first` and `fade` `second`, then a rebuild that puts both names
    at 0x900, with the pane as a new start leaves it."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text=first, cpu="maincpu")
    s.comment_write("add", ref="fade", text=second, cpu="maincpu")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900, "FADE": 0x900})
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    return pane, _counted(comments.rearm(pane, tmp_path))  # type: ignore[arg-type]


def test_deleting_a_comment_never_feeds_a_stale_one_at_its_place_to_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _stale_raw_under_a_moved_symbol(monkeypatch, tmp_path, raw_first=False)
    out = s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert out["status"] == "ok", out
    assert _states() == {"0x900": ("stale", "old raw")}
    assert pane.on(MAIN) == {}, "a stale comment reached the pane"


def test_deleting_the_shown_comment_clears_it_when_the_other_there_cannot_be_shown(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane, _ = _rebuilt_onto_one_place(monkeypatch, tmp_path, "by name", 'says "hi"')
    assert pane.on(MAIN) == {0x900: "by name"}
    s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert pane.on(MAIN) == {}, "the deleted text is still in the pane"
    assert _states()["fade"][0] == "unarmable"


@pytest.mark.parametrize("raw_first", [True, False])
def test_an_add_where_a_rebuild_put_two_comments_leaves_armed_only_what_the_pane_shows(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw_first: bool) -> None:
    pane = _stale_raw_under_a_moved_symbol(monkeypatch, tmp_path, raw_first)
    s.comment_write("add", ref="0x900", text="N", cpu="maincpu")
    armed = {ref: text for ref, (state, text) in _states().items() if state == "armed"}
    assert armed == {"0x900": "N"} and pane.on(MAIN) == {0x900: "N"}, (armed, pane.on(MAIN))
    why = s.comment_list()["comments"]
    assert any(c["ref"] == "irq_vblank" and "'0x900'" in c["why"] for c in why), why


def test_a_start_shows_the_next_comment_at_a_place_when_the_first_cannot_be_shown(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane, counts = _rebuilt_onto_one_place(monkeypatch, tmp_path, 'q "x"', "plain")
    assert pane.on(MAIN) == {0x900: "plain"}
    assert _states() == {"irq_vblank": ("unarmable", 'q "x"'), "fade": ("armed", "plain")}
    assert (counts["rearmed"], counts["unarmable"]) == (1, 1), counts
    why = {c["ref"]: c["why"] for c in s.comment_list()["comments"] if "why" in c}
    assert "holds a `\"`" in why["irq_vblank"], "its own reason, which no rebuild will lift"


def test_a_replacement_the_stub_cannot_feed_leaves_the_old_text_for_the_delete_to_clear(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path, threads=False)
    s.comment_write("add", ref="fade", text="t1", cpu="maincpu")
    pane.visible = SUB      # a stop on the other cpu, and no thread patch to show main again
    out = s.comment_write("add", ref="fade", text="t2", cpu="maincpu")
    assert out["comment"]["state"] == "unarmable" and pane.on(MAIN) == {0x900: "t1"}
    pane.visible = MAIN
    s.comment_write("delete", ref="fade", cpu="maincpu")
    assert held() == [] and pane.on(MAIN) == {}, "the old text was left in the pane"


def test_resaving_a_loaded_file_spelled_otherwise_names_only_the_row_it_drops(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    f = tmp_path / "c.tsv"
    f.write_text(HEAD + f"0x0400\tmaincpu\t{STAMP}\tx\nFade\t:maincpu\t{STAMP}\ty\n")
    assert s.comment_write("load", path=str(f))["added"] == 2
    s.comment_write("delete", ref="fade", cpu="maincpu")
    out = s.comment_write("save", dest=str(f))
    assert out["dropped_comments"] == [{"ref": "Fade", "cpu": ":maincpu"}], out


def test_save_refuses_a_dest_that_is_not_a_regular_file_without_opening_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import threading
    _pane(monkeypatch, tmp_path)
    fifo = tmp_path / "pipe.tsv"
    host_program.fifo(fifo)
    box: dict[str, dict[str, object]] = {}
    t = threading.Thread(target=lambda: box.update(out=s.comment_write("save", dest=str(fifo))),
                         daemon=True)
    t.start()
    t.join(5)
    if t.is_alive():            # a writer releases the blocked reader so the thread ends
        host_program.release_fifo(fifo)
        t.join(5)
        pytest.fail("comment_write save blocked on a FIFO at dest")
    assert box["out"]["code"] == "bad_argument" and "regular file" in str(box["out"]), box


def test_save_refuses_the_shared_store_from_a_session_with_its_own(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A session whose store lives in its `state_dir` still may not write the shared store's
    file, absent or not: a comment file there refuses every later `start` without a
    `state_dir` until it is removed by hand."""
    _pane(monkeypatch, tmp_path, store=tmp_path / "own" / "declarations.json")
    shared = dec.default_path()
    shared.parent.mkdir(parents=True, exist_ok=True)
    out = s.comment_write("save", dest=str(shared))
    assert out.get("code") == "bad_argument", out
    assert "the declaration store's own file" in out["message"], out
    assert not shared.exists()


def test_save_refuses_the_declaration_stores_own_file(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    store = tmp_path / "declarations.json"
    _pane(monkeypatch, tmp_path, store=store)
    out = s.comment_write("save", dest=str(store))
    assert out.get("code") == "bad_argument", out
    assert "the declaration store's own file" in out["message"], out
    assert not store.exists()
    assert s.comment_write("add", ref="fade", text="x", cpu="maincpu")["status"] == "ok"


def test_the_add_description_says_bare_hex_naming_no_symbol_is_not_a_name_kept_unresolved(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import asyncio
    _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="cafe", text="x", cpu="maincpu")
    assert out["code"] == "unknown_ref" and "written 0xcafe" in out["message"], out
    comment = s.comment_write("add", ref="0xcafe", text="x", cpu="maincpu")["comment"]
    assert (comment["by"], comment["ref"], comment["state"]) == ("address", "0xcafe", "armed")
    tools = {t.name: t for t in asyncio.run(s.mcp.list_tools())}
    text = " ".join((tools["comment_write"].description or "").split())
    assert "a symbol or a linear `0x` address" in text, text
    assert "`unresolved` names a symbol this build lacks" in documented("comment_write")


def test_a_store_holding_a_comment_without_a_stamp_is_refused_when_read(
        tmp_path: Path) -> None:
    store = tmp_path / "declarations.json"
    row = {"kind": "comment", "by": "symbol", "ref": "fade", "cpu": MAIN, "text": "x"}
    for stamp in (None, "yesterday"):
        store.write_text(json.dumps({"k": [row if stamp is None
                                           else {**row, "created_at": stamp}]}))
        with pytest.raises(dec.DeclarationError, match="created_at"):
            dec.DeclarationStore("k", store)
    store.write_text(json.dumps({"k": [{**row, "created_at": STAMP}]}))
    assert [d.text for d in dec.DeclarationStore("k", store).declarations()] == ["x"]


# Each case below holds one line of the tools that no other case reaches.


@pytest.mark.parametrize("ref", ["0xzz", "0x12zz"])
def test_a_ref_with_hex_after_0x_and_more_after_it_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str) -> None:
    _pane(monkeypatch, tmp_path)
    assert s.comment_write("add", ref=ref, text="t", cpu="maincpu")["code"] == "bad_argument"
    assert held() == []


def test_a_comment_on_the_visible_cpu_moves_no_cpu(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    s.comment_write("delete", ref="fade", cpu="maincpu")
    assert not [c for c in pane.commands if c.startswith("Hc")], pane.commands


def test_load_clears_a_shown_text_it_replaces_with_one_the_pane_cannot_show(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="old", cpu="maincpu")
    f = tmp_path / "c.tsv"
    f.write_text(HEAD + f'fade\t:maincpu\t{STAMP}\tsays "new"\n')
    assert s.comment_write("load", path=str(f))["replaced_total"] == 1
    assert pane.on(MAIN) == {}, "the replaced text stayed in the pane"


def test_no_reply_carries_the_feeds_own_bookkeeping(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert "landed" not in out["comment"]
    assert all("landed" not in c for c in s.comment_list()["comments"])


def test_load_over_a_stale_row_with_the_same_text_keeps_that_rows_stamp(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x900", text="same", cpu="maincpu")
    (before,) = held()
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "the new build")
    f = tmp_path / "c.tsv"
    f.write_text(HEAD + f"0x900\t:maincpu\t{STAMP}\tsame\n")
    s.comment_write("load", path=str(f))
    (after,) = held()
    assert after.created_at == before.created_at != STAMP
    assert after.fingerprint == "the new build"


def test_the_dropped_rows_are_named_by_cpu_then_ref(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    f = tmp_path / "c.tsv"
    f.write_text(HEAD + f"0x600\t:maincpu\t{STAMP}\tm\n0x500\t:subcpu\t{STAMP}\ts\n")
    out = s.comment_write("save", dest=str(f))
    assert [(d["ref"], d["cpu"]) for d in out["dropped_comments"]] == [
        ("0x600", MAIN), ("0x500", SUB)], out


def _put_back_refused(monkeypatch: pytest.MonkeyPatch, pane: _Pane) -> None:
    real = pane.make_visible

    def back_refused(thread: int) -> None:
        if thread == 1 and pane.visible == SUB:
            raise gs.Refused("E01")
        real(thread)

    monkeypatch.setattr(pane, "make_visible", back_refused)


def test_a_delete_says_when_the_visible_cpu_could_not_be_put_back(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x400", text="sub", cpu="subcpu")
    _put_back_refused(monkeypatch, pane)
    out = s.comment_write("delete", ref="0x400", cpu="subcpu")
    assert out["status"] == "ok" and pane.on(SUB) == {}
    assert "could not be made visible again" in out["note"], out


def test_a_start_says_when_the_visible_cpu_could_not_be_put_back(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x400", text="sub", cpu="subcpu")
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    _put_back_refused(monkeypatch, pane)
    counts = _counted(comments.rearm(pane, tmp_path))  # type: ignore[arg-type]
    assert counts["rearmed"] == 1 and "could not be made visible again" in counts["note"]


def test_a_replacement_the_console_answers_leaves_the_old_text_for_the_delete_to_clear(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="t1", cpu="maincpu")
    pane.refuse_next = True
    assert s.comment_write("add", ref="fade", text="t2",
                           cpu="maincpu")["comment"]["state"] == "unarmable"
    assert pane.on(MAIN) == {0x900: "t1"}
    s.comment_write("delete", ref="fade", cpu="maincpu")
    assert held() == [] and pane.on(MAIN) == {}, "the old text was left in the pane"


def test_a_delete_says_when_no_other_comment_at_the_place_could_take_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _two_at_one_place(monkeypatch, tmp_path)
    comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    pane.threads, pane.visible = {}, SUB     # a stop on the sub cpu, no thread patch
    out = s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert out["status"] == "ok" and pane.on(MAIN) == {0x900: "by name"}
    assert "no other comment at 0x00000900 on :maincpu could take its place" in out["note"], out


def test_a_ref_that_spells_neither_comment_at_a_place_reaches_the_one_the_pane_shows(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _rebuilt_onto_one_place(monkeypatch, tmp_path, 'q "x"', "plain")
    assert s.comment_write("add", ref="0x900", text="N", cpu="maincpu")["comment"]["ref"] == "fade"
    assert _states() == {"irq_vblank": ("unarmable", 'q "x"'), "fade": ("armed", "N")}
    assert s.comment_write("delete", ref="0x900", cpu="maincpu")["deleted"]["ref"] == "fade"


def test_a_delete_by_a_name_in_another_case_reaches_the_comment_the_pane_shows(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stale_raw_under_a_moved_symbol(monkeypatch, tmp_path, raw_first=True)
    out = s.comment_write("delete", ref="IRQ_VBLANK", cpu="maincpu")
    assert out["deleted"]["ref"] == "irq_vblank", out
    assert _states() == {"0x900": ("stale", "old raw")}


def test_save_refuses_the_stores_file_in_another_case_and_a_link_that_loops(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "declarations.json"
    _pane(monkeypatch, tmp_path, store=store)
    out = s.comment_write("save", dest=str(tmp_path / "DECLARATIONS.json"))
    assert out.get("code") == "bad_argument", out
    assert "the declaration store's own file" in out["message"], out
    loop = tmp_path / "loop.tsv"
    loop.symlink_to(loop)
    out = s.comment_write("save", dest=str(loop))
    assert out["code"] == "bad_argument" and "link" in out["message"], out


def test_save_names_a_row_on_a_cpu_this_machine_lacks_as_dropped(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    f = tmp_path / "c.tsv"
    f.write_text(HEAD + f"0x500\t:nocpu\t{STAMP}\telsewhere\n")
    out = s.comment_write("save", dest=str(f))
    assert out["status"] == "ok" and out["dropped_comments"] == [
        {"ref": "0x500", "cpu": ":nocpu"}], out



# ------------------------------------------------- the pane case by case, and the store first

def _shared(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rival: str = "by address") -> _Pane:
    """Two comments at one place after a rebuild and a start: `irq_vblank`'s shown, the raw
    `0x900`'s (`rival`) displaced."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="irq_vblank", text="by name", cpu="maincpu")
    s.comment_write("add", ref="0x900", text=rival, cpu="maincpu")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900})
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    assert pane.on(MAIN) == {0x900: "by name"}
    return pane


def test_a_shown_comment_replaced_by_a_text_the_pane_cannot_show_gives_the_place_to_its_rival(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The pane shows the first comment at a place it CAN show: a replacement it cannot show
    clears the old text, and the rival the old one displaced is tried, never left out with a
    why naming a comment that no longer holds the pane."""
    pane = _shared(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="irq_vblank", text='say "hi"', cpu="maincpu")
    assert out["comment"]["state"] == "unarmable", out
    assert pane.on(MAIN) == {0x900: "by address"}, pane.held
    rows = {r["ref"]: r for r in s.comment_list()["comments"]}
    assert rows["0x900"]["state"] == "armed", rows
    s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "by address"}
    assert s.comment_list()["comments"][0]["state"] == "armed"


def test_a_text_the_console_answered_hands_the_place_to_its_rival_which_keeps_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The console answers the new text with words, so the pane does not show it: the rival is
    fed at once, and the delete of the comment the pane no longer shows leaves the rival there."""
    pane = _shared(monkeypatch, tmp_path, rival="the rival")
    pane.refuse_next = True                       # the next comadd is answered with words
    s.comment_write("add", ref="irq_vblank", text="refused text", cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "the rival"}, pane.held
    pane.commands = []
    s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "the rival"}, pane.held
    assert not any(c.startswith(("comadd", "comdelete")) for c in pane.commands), pane.commands


def test_a_delete_of_a_comment_the_pane_did_not_show_leaves_the_shown_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Three at one place, the second shown (fed last): deleting the third, never shown, changes
    nothing in the pane, rather than feeding the first over the one it shows."""
    pane = _pane(monkeypatch, tmp_path)
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x400, "THIRD": 0x800})
    s.comment_write("add", ref="irq_vblank", text="by name", cpu="maincpu")
    s.comment_write("add", ref="0x900", text="by address", cpu="maincpu")
    s.comment_write("add", ref="third", text="third", cpu="maincpu")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900, "THIRD": 0x900})
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    s.comment_write("add", ref="0x900", text="by address 2",
                    cpu="maincpu")   # fed last, it is shown
    assert pane.on(MAIN) == {0x900: "by address 2"}, pane.held
    pane.commands = []
    s.comment_write("delete", ref="third", cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "by address 2"}, pane.held
    assert not any(c.startswith("comadd") for c in pane.commands), pane.commands


def test_a_store_write_that_failed_is_said_when_the_session_then_breaks(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The store could not be written and the pane's command then broke the session: the reply
    says the change lives in this session only, never that the store holds it."""
    pane = _pane(monkeypatch, tmp_path)
    monkeypatch.setattr(comments, "_apply", lambda **_: "the declaration store could not be "
                        "written (disk full): the change is held in memory")

    def breaks(command: str, timeout: float = 10.0) -> str:
        raise gs.SessionError("the stub stopped answering")
    monkeypatch.setattr(pane, "monitor", breaks)
    out = s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    assert out["code"] == "session_broken" and out["held_in_memory"] is True, out
    assert comments.STORE_HELD not in out["message"] and "gone at `close`" in out["message"]


def test_a_refusal_after_the_store_write_says_the_store_holds_the_change_once(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    real = pane.monitor

    def refuses(command: str, timeout: float = 10.0) -> str:
        if command.startswith("comadd"):
            raise gs.Refused("E01")
        return real(command, timeout)
    monkeypatch.setattr(pane, "monitor", refuses)
    out = s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    assert out["code"] == "readback_refused" and out["message"].count(comments.STORE_HELD) == 1
    assert pane.broken is None and [d.ref for d in held()] == ["0x900"]


@pytest.mark.parametrize("tool", ["add", "delete", "load"])
def test_a_machine_running_again_under_a_comment_call_is_not_stopped_and_latches_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str) -> None:
    pane = _pane(monkeypatch, tmp_path)
    if tool == "delete":
        s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x900\t:maincpu\t{STAMP}\tt\n")
    real = pane.monitor

    def runs(command: str, timeout: float = 10.0) -> str:
        if command.startswith(("comadd", "comdelete")):
            raise gs.NotStopped("the machine runs")
        return real(command, timeout)
    monkeypatch.setattr(pane, "monitor", runs)
    out = (s.comment_write("add", ref="0x900", text="t", cpu="maincpu") if tool == "add" else
           s.comment_write("delete", ref="0x900", cpu="maincpu") if tool == "delete" else
           s.comment_write("load", path=str(src)))
    assert out["code"] == "not_stopped" and pane.broken is None, out


def test_a_delete_the_pane_never_showed_with_no_rival_it_can_show_claims_nothing_of_the_pane(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Neither the deleted comment nor its rival is shown: the note says no rival could take the
    place, and says nothing of a deleted text the pane never held."""
    pane = _shared(monkeypatch, tmp_path, rival='a "quoted" rival')
    s.comment_write("add", ref="irq_vblank", text='now "quoted" too', cpu="maincpu")
    assert pane.on(MAIN) == {}, pane.held
    out = s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert "could take its place in MAME's pane:" in out.get("note", ""), out.get("note")
    assert "still shows" not in out["note"] and "cleared" not in out["note"], out["note"]


def test_the_delete_note_says_the_pane_was_cleared_when_it_was(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No rival can take the place, and the text the pane could not carry cleared it: the note
    never says the pane may still show the deleted text."""
    pane = _shared(monkeypatch, tmp_path, rival='a "quoted" rival')
    out = s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert pane.on(MAIN) == {}, pane.held
    assert "still show" not in out.get("note", ""), out.get("note")
    assert "cleared" in out.get("note", ""), out.get("note")


def test_the_delete_note_says_the_pane_still_shows_the_text_when_it_does(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _shared(monkeypatch, tmp_path, rival="the rival")
    pane.refuse_next = True                       # the rival's comadd is answered with words
    out = s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "by name"}, pane.held
    assert "still shows the deleted text" in out.get("note", ""), out.get("note")


def test_a_delete_over_bytes_that_changed_says_mame_keeps_the_text_hidden(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """MAME keys a comment by its address and the bytes under it, and `comdelete` removes the
    one keyed by the bytes there now: once they changed, MAME keeps the old one, hidden, and the
    delete says so."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x900", text="over code that moves", cpu="maincpu")
    pane.moved.add((MAIN, 0x900))
    out = s.comment_write("delete", ref="0x900", cpu="maincpu")
    assert out["status"] == "ok" and held() == [], out
    assert "hidden" in out.get("note", "") and "close" in out.get("note", ""), out.get("note")


def test_a_comment_file_two_rows_of_which_a_rebuild_put_at_one_place_loads_whole(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Saved before the rebuild, read after it: both comments come in, as the store would have
    kept them through the rebuild, and the pane shows the first; so what
    `comment_write(method="save")` writes
    of a store holding two at one place, `comment_write(method="load")` reads back."""
    pane = _pane(monkeypatch, tmp_path)
    src = tmp_path / "before.tsv"
    src.write_text(HEAD + f"irq_vblank\t:maincpu\t{STAMP}\tby name\n"
                          f"0x900\t:maincpu\t{STAMP}\tby address\n")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900})
    out = s.comment_write("load", path=str(src))
    assert out["status"] == "ok" and out["added"] == 2, out
    assert pane.on(MAIN) == {0x900: "by name"}, pane.held
    states = {r["ref"]: r["state"] for r in s.comment_list()["comments"]}
    assert states == {"irq_vblank": "armed", "0x900": "unarmable"}, states
    again = tmp_path / "again.tsv"
    s.comment_write("save", dest=str(again))
    s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    s.comment_write("delete", ref="0x900", cpu="maincpu")
    assert s.comment_write("load", path=str(again))["added"] == 2


def test_a_file_row_at_a_place_the_store_comments_replaces_it_once(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two rows of the file at a place the store comments under a third ref: the first file row
    the place reaches replaces it, the second is added beside it, never a second replacement of
    the same row."""
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="the store's", cpu="maincpu")
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x900\t:maincpu\t{STAMP}\tfirst\n"
                          f"second_name\t:maincpu\t{STAMP}\tsecond\n")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x400, "FADE": 0x900,
                                        "SECOND_NAME": 0x900})
    out = s.comment_write("load", path=str(src))
    assert out["status"] == "ok", out
    assert (out["replaced_total"], out["added"]) == (1, 1), out
    assert sorted((d.ref, d.text) for d in held()) == [("0x900", "first"),
                                                      ("second_name", "second")]


@pytest.mark.parametrize("ref", ["main+4", "fade-2", "(fade)", "fade*2", "a/b", "a%b", "a&b",
                                 "a|b", "a^b", "~a", "!a", "a<b", "a>b", "a=b", "a,b", "a;b",
                                 "a[1]"])
def test_an_expression_in_a_comment_ref_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str) -> None:
    """A comment names a place, a symbol or a `0x` address; an expression is neither, and stored
    as a symbol it would never resolve."""
    _pane(monkeypatch, tmp_path)
    out = s.comment_write("add", ref=ref, text="t", cpu="maincpu")
    assert refused("expression", out)["code"] == "bad_argument"
    assert held() == []


@pytest.mark.parametrize("tool", ["add", "delete", "load"])
def test_a_session_broken_after_the_store_write_says_the_store_holds_the_change(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str) -> None:
    """The store is the record and is written first, so it survives a session that breaks while
    the pane is fed, and the next `start` feeds the pane from it: the refusal says the change
    is in the store, never that nothing was handed back."""
    pane = _pane(monkeypatch, tmp_path)
    if tool == "delete":
        s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    real = pane.monitor

    def breaks(command: str, timeout: float = 10.0) -> str:
        if command.startswith(("comadd", "comdelete")):
            raise gs.SessionError("the stub stopped answering")
        return real(command, timeout)

    monkeypatch.setattr(pane, "monitor", breaks)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x900\t:maincpu\t{STAMP}\tt\n")
    out = (s.comment_write("add", ref="0x900", text="t", cpu="maincpu") if tool == "add" else
           s.comment_write("delete", ref="0x900", cpu="maincpu") if tool == "delete" else
           s.comment_write("load", path=str(src)))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert comments.STORE_HELD in out["message"], out["message"]
    assert "Nothing this call read" not in out["message"], out["message"]
    assert [d.ref for d in held()] == ([] if tool == "delete" else ["0x900"])


# ----------------------------------------------- each guard the comment code keeps, by its case

def test_a_rival_replaced_by_a_text_the_pane_cannot_show_leaves_the_shown_one_alone(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only a place whose pane showed the replaced text is cleared: the displaced rival's new
    text cannot be shown, and the comment the pane shows stays, with no `comdelete` sent."""
    pane = _shared(monkeypatch, tmp_path)
    pane.commands = []
    s.comment_write("add", ref="0x900", text='a "quoted" rival', cpu="maincpu")
    assert pane.on(MAIN) == {0x900: "by name"}, pane.held
    assert not any(c.startswith("comdelete") for c in pane.commands), pane.commands


def test_a_load_replacing_a_rival_with_a_text_the_pane_cannot_show_clears_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _shared(monkeypatch, tmp_path)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f'0x900\t:maincpu\t{STAMP}\ta "quoted" rival\n')
    pane.commands = []
    out = s.comment_write("load", path=str(src))
    assert out["status"] == "ok" and out["replaced_total"] == 1, out
    assert pane.on(MAIN) == {0x900: "by name"}, pane.held
    assert not any(c.startswith("comdelete") for c in pane.commands), pane.commands


def test_a_load_says_when_the_visible_cpu_could_not_be_put_back(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    real = pane.make_visible

    def back_refused(thread: int) -> None:
        if thread == 1 and pane.visible == SUB:
            raise gs.Refused("E01")
        real(thread)

    monkeypatch.setattr(pane, "make_visible", back_refused)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0x400\t:subcpu\t{STAMP}\tsub\n")
    out = s.comment_write("load", path=str(src))
    assert out["status"] == "ok" and "could not be made visible again" in out["note"], out


def test_a_console_answer_to_comadd_is_quoted_on_one_line(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pane = _pane(monkeypatch, tmp_path)
    pane.refuse_next = True
    out = s.comment_write("add", ref="0x900", text="t", cpu="maincpu")
    said = " ".join(captured("comadd.unbalanced.txt").strip().split())
    assert out["comment"]["why"] == f"the console answered `comadd` with {said!r}", out


def test_a_resave_does_not_call_a_symbol_spelled_in_another_case_dropped(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    dest = tmp_path / "out.tsv"
    dest.write_text(HEAD + f"FADE\t:maincpu\t{STAMP}\tt\n")
    out = s.comment_write("save", dest=str(dest))
    assert out["dropped_total"] == 0, out


def test_a_file_address_written_with_a_capital_x_is_an_address(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + f"0X900\t:maincpu\t{STAMP}\tt\n")
    assert s.comment_write("load", path=str(src))["status"] == "ok"
    assert [(d.by, d.ref) for d in held()] == [("address", "0x900")]


def test_a_delete_on_a_cpu_with_no_comment_says_none_is_held(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    out = s.comment_write("delete", ref="0x900", cpu="maincpu")
    assert refused("The comments held on :maincpu: none at all", out)["code"] == "unknown_ref"


def test_a_dropped_row_with_no_cpu_says_why_it_names_none(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    dest = tmp_path / "out.tsv"
    dest.write_text(HEAD + f"0x777\t\t{STAMP}\tgone\n")
    out = s.comment_write("save", dest=str(dest))
    (row,) = out["dropped_comments"]
    assert row["ref"] == "0x777" and row["cpu"]["available"] is False, out


def test_a_replaced_comment_carries_the_origin_of_the_session_that_replaced_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _pane(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "session_origin", "the first session")
    s.comment_write("add", ref="fade", text="first", cpu="maincpu")
    monkeypatch.setattr(mstate.STATE, "session_origin", "the second session")
    s.comment_write("add", ref="fade", text="second", cpu="maincpu")
    assert [(d.text, d.origin) for d in held()] == [("second", "the second session")]


def test_save_refuses_the_stores_own_file_once_the_store_has_written_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The store's file is refused as itself, never as "not a comment file", whether or not the
    store has written it yet."""
    store = tmp_path / "declarations.json"
    _pane(monkeypatch, tmp_path, store=store)
    s.comment_write("add", ref="fade", text="t", cpu="maincpu")
    assert store.is_file()
    out = s.comment_write("save", dest=str(store))
    assert refused("the declaration store's own file", out)["code"] == "bad_argument"


def test_a_name_the_table_holds_is_a_name_whatever_its_characters(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A symbol file can carry a name with operator characters (a C++ one): the table holding it
    makes it a name, so only what the table does not name is read as an expression."""
    _pane(monkeypatch, tmp_path)
    use_table(monkeypatch, MAIN, table={"OPERATOR+(INT)": 0x900})
    out = s.comment_write("add", ref="operator+(int)", text="t", cpu="maincpu")
    assert out["status"] == "ok" and out["comment"]["addr"] == "0x00000900", out



@pytest.mark.parametrize(("rows", "refused_at"), [
    (["fade", "FADE"], 3), (["fade\t:maincpu", "fade\t:subcpu"], None)])
def test_a_comment_row_named_twice_is_one_comment_on_one_cpu(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: list[str],
        refused_at: int | None) -> None:
    """A symbol in two cases is one comment; the same ref on two cpus is two."""
    _pane(monkeypatch, tmp_path)
    use_table(monkeypatch, SUB, table={"FADE": 0x900})
    body = "".join(f"{r if chr(9) in r else r + chr(9) + ':maincpu'}\t{STAMP}\tt{n}\n"
                   for n, r in enumerate(rows))
    src = tmp_path / "in.tsv"
    src.write_text(HEAD + body)
    out = s.comment_write("load", path=str(src))
    if refused_at is None:
        assert out["status"] == "ok" and out["added"] == 2, out
    else:
        refused(re.escape(f"{src}:{refused_at}: names the comment line"), out)
