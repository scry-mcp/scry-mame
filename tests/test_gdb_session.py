"""Gate for the pure parts of the gdbstub client."""

import dataclasses
import json
import re
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scry_core.reply_contract import Invalid
from session_doubles import reading_session  # noqa: E402

from scry_mame import gdb_session as g  # noqa: E402


@pytest.mark.parametrize("body", ["0* ", "00ff*\"00", "*", "<reg name=\"a*\"/>"])
def test_a_run_length_marker_in_a_reply_is_refused_by_name(body: str) -> None:
    """MAME's stub never compresses, so a literal `*` in a reply is refused by name, not decoded."""
    ses, _wire = _wired([body])
    at = body.index("*")
    with pytest.raises(g.SessionError, match=rf"run-length marker `\*` at position {at} of"):
        ses.request("m0,4")
    with pytest.raises(g.SessionError, match="never compresses"):
        _wired([body])[0]._receive()


def test_a_reply_without_the_marker_is_read_as_it_came() -> None:
    """THE CONTROL for the case above."""
    ses, _wire = _wired(["46fc2700"])
    assert ses.request("m0,4") == "46fc2700"


def test_checksum() -> None:
    assert g._checksum("qSupported") == f"{sum(b'qSupported') & 0xFF:02x}"


def test_reads_the_projects_symbols(tmp_path: Path) -> None:
    y = tmp_path / "symbols.yaml"
    y.write_text(
        "images:\n"
        "  wheelfir_maincpu:\n"
        "  - addr: 642778\n"
        "    name: wf_pal_blast\n"
        "    description: ignored\n"
        "  - addr: 0x1234\n"
        "    nombre: other_symbol\n",
        encoding="utf-8",
    )
    t = g.symbols(str(y))
    assert t.table["WF_PAL_BLAST"] == 0x9CEDA
    assert t.table["OTHER_SYMBOL"] == 0x1234
    assert t.format == "yaml"
    assert t.by_class == {}, "a YAML file carries runtime addresses and no classes"


def test_a_name_given_twice_loads_and_is_refused_as_ambiguous_when_looked_up(
        tmp_path: Path) -> None:
    y = tmp_path / "s.yaml"
    y.write_text("- addr: 16\n  name: count\n- addr: 32\n  name: other\n- addr: 48\n"
                 "  name: Count\n", encoding="utf-8")
    t = g.symbols(str(y))
    assert "COUNT" in t.table and len(t.table) == 2 and g.rows_of(t.table) == [
        ("COUNT", 16), ("OTHER", 32), ("COUNT", 48)]
    assert t.table["OTHER"] == 32 and t.shown("COUNT") == "count"
    lookups: list[Callable[[], object]] = [lambda: t.table["COUNT"], lambda: t.table.get("COUNT")]
    for lookup in lookups:
        with pytest.raises(Invalid, match=r"'COUNT' names 2 symbols.*0x10.*0x30") as e:
            lookup()
        assert e.value.code == "ambiguous_ref"
    assert t.table.get("MISSING") is None


def test_a_repeated_row_at_the_same_address_is_one_symbol_and_not_an_ambiguity() -> None:
    names = g.Names()
    for key, at in (("FOO", 0x100), ("FOO", 0x100), ("BAR", 0x200), ("BAR", 0x300)):
        names.add(key, at)
    assert names["FOO"] == 0x100 and names.ambiguous == {"BAR": [0x200, 0x300]}


def test_a_description_is_not_mistaken_for_a_name(tmp_path: Path) -> None:
    """Only the FIRST name key after an `addr` counts."""
    y = tmp_path / "s.yaml"
    y.write_text("- addr: 16\n  name: first\n  name_long: second\n", encoding="utf-8")
    t = g.symbols(str(y))
    assert t.table == {"FIRST": 16}



V30_MAP = (
    "# v30tool symbol map\n"
    "# columns: name\\tlinear_hex\\tseg_name\\toffset_hex\\tclass\n"
    "_start\tED000\t_TEXT\t0\tCODE\n"
    "draw_iblock\tED27E\t_TEXT\t27E\tCODE\n"
    "\n"
    "demo_count\t2A007\t_DATA\tA007\tDATA\n"
)


def test_a_tsv_map_loads_every_row_by_class(tmp_path: Path) -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    m = tmp_path / "game.map"
    m.write_text(V30_MAP, encoding="utf-8")
    t = g.symbols(str(m), bases={"DATA": 0x400})
    assert t.format == "tsv"
    assert len(t.table) == 3
    assert t.table["_START"] == 0xED000
    assert t.table["DRAW_IBLOCK"] == 0xED27E
    assert t.table["DEMO_COUNT"] == 0x400 + 0xA007
    assert t.by_class == {"CODE": 2, "DATA": 1}


def test_the_map_header_is_accepted_and_not_required(tmp_path: Path) -> None:
    """Detection is by the SHAPE of the rows, so any comment header, or none, loads."""
    m = tmp_path / "game.map"
    m.write_text("_start\tED000\t_TEXT\t0\tCODE\n", encoding="utf-8")
    t = g.symbols(str(m))
    assert t.table == {"_START": 0xED000}
    assert t.format == "tsv"
    m.write_text("# another tool, another header\n_start\tED000\t_TEXT\t0\tCODE\n")
    assert g.symbols(str(m)).table == {"_START": 0xED000}


def test_a_rows_class_and_name_are_normalised(tmp_path: Path) -> None:
    """The file's own class column may be lower-case or padded."""
    m = tmp_path / "game.map"
    m.write_text("foo \t1\t_TEXT\t1\tcode \n", encoding="utf-8")
    t = g.symbols(str(m))
    assert t.table == {"FOO": 0x1}
    assert t.by_class == {"CODE": 1}


def test_a_name_repeated_in_a_map_keeps_every_row_and_its_first_address(tmp_path: Path) -> None:
    """A linker map repeats the statics of different modules: both rows stay for placing an
    address, and the name is refused when looked up."""
    m = tmp_path / "game.map"
    m.write_text("count\tED000\t_TEXT\t0\tCODE\nCount\tED100\t_TEXT\t100\tCODE\n")
    t = g.symbols(str(m))
    assert g.rows_of(t.table) == [("COUNT", 0xED000), ("COUNT", 0xED100)]
    assert isinstance(t.table, g.Names) and t.table.ambiguous == {"COUNT": [0xED000, 0xED100]}
    assert dict.__getitem__(t.table, "COUNT") == 0xED000


def test_a_table_keeps_the_spelling_the_file_gave_beside_its_folded_key(tmp_path: Path) -> None:
    m = tmp_path / "game.map"
    m.write_text("irq_Vblank\tED000\t_TEXT\t0\tCODE\n")
    y = tmp_path / "game.yaml"
    y.write_text("- addr: 0x400\n  name: irq_Vblank\n")
    for path in (m, y):
        assert g.symbols(str(path)).spelled == {"IRQ_VBLANK": "irq_Vblank"}, path


def test_a_base_for_a_class_no_row_carries_is_refused(tmp_path: Path) -> None:
    """A parameter honoured by nothing is refused, not ignored."""
    m = tmp_path / "game.map"
    m.write_text("_start\tED000\t_TEXT\t0\tCODE\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"DTA") as e:
        g.symbols(str(m), bases={"DTA": 0x400})
    assert "CODE" in str(e.value), "the refusal lists the classes the file does have"


def test_a_row_that_is_not_hex_is_refused_with_its_line(tmp_path: Path) -> None:
    m = tmp_path / "game.map"
    m.write_text("_start\tZZZZ\t_TEXT\t0\tCODE\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":1\b.*not a hex"):
        g.symbols(str(m))


def test_a_map_whose_tabs_became_spaces_is_refused_not_emptied(tmp_path: Path) -> None:
    """An editor that expands tabs turns a map into a file that matches neither shape."""
    m = tmp_path / "game.map"
    m.write_text(V30_MAP.replace("\t", "    "), encoding="utf-8")
    with pytest.raises(ValueError, match=r"ZERO symbols"):
        g.symbols(str(m))


def test_a_tab_inside_a_yaml_file_is_still_yaml(tmp_path: Path) -> None:
    """A tab is legal YAML text and does not make a file a map."""
    y = tmp_path / "s.yaml"
    y.write_text("\t- addr: 16\n\tname: first\n\tdescription: a\tb\n", encoding="utf-8")
    t = g.symbols(str(y))
    assert t.table == {"FIRST": 16}
    assert t.format == "yaml"


def test_an_explicit_base_wins_over_the_code_default(tmp_path: Path) -> None:
    """A parameter that silently does nothing is the class of defect this server hunts."""
    m = tmp_path / "game.map"
    m.write_text("_start\tED000\t_TEXT\t10\tCODE\n", encoding="utf-8")
    t = g.symbols(str(m), bases={"code": 0x1000})
    assert t.table == {"_START": 0x1010}


def test_a_rom_resident_class_is_declared_and_keeps_the_maps_linear_address(tmp_path: Path) -> None:
    """A class that lives in ROM (a tile sheet the locator placed) runs where the map says."""
    m = tmp_path / "game.map"
    m.write_text(V30_MAP + "juke_tiles\t60000\tJUKE\t0\tV30_JUKEBOX\n", encoding="utf-8")
    t = g.symbols(str(m), bases={"DATA": 0x400, "V30_JUKEBOX": None})
    assert t.table["JUKE_TILES"] == 0x60000, "resident: the linear address, no arithmetic"
    assert t.table["DEMO_COUNT"] == 0x400 + 0xA007, "a based class is still relocated"
    assert t.by_class["V30_JUKEBOX"] == 1


def test_a_class_with_no_base_refuses_and_names_the_row(tmp_path: Path) -> None:
    """A class nobody located is refused, not read at the linker's image address."""
    m = tmp_path / "game.map"
    m.write_text(
        V30_MAP + "stack_top\t2B000\t_STACK\t0\tSTACK\nstack_bot\t2B100\t_STACK\t100\tSTACK\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"STACK") as e:
        g.symbols(str(m), bases={"DATA": 0x400})
    assert "stack_top" in str(e.value), "the refusal must name the FIRST row with that class"
    assert "stack_bot" not in str(e.value), "and only the first: one row is enough to act on"
    assert "bases" in str(e.value), "the refusal must name the parameter that fixes it"


def test_a_tsv_map_with_no_bases_refuses_on_its_first_data_row(tmp_path: Path) -> None:
    """The control for the case above, on the class that produced the rule."""
    m = tmp_path / "game.map"
    m.write_text(V30_MAP, encoding="utf-8")
    with pytest.raises(ValueError, match=r"DATA"):
        g.symbols(str(m))


def test_a_file_holding_both_shapes_is_refused(tmp_path: Path) -> None:
    """Half YAML and half TSV is a file whose addresses mean two different things."""
    m = tmp_path / "mixed.txt"
    m.write_text("- addr: 16\n  name: first\n_start\tED000\t_TEXT\t0\tCODE\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"both"):
        g.symbols(str(m))


def test_bases_given_with_a_yaml_file_are_refused(tmp_path: Path) -> None:
    """`bases` with a YAML file is refused: it has no classes to apply it to."""
    y = tmp_path / "s.yaml"
    y.write_text("- addr: 16\n  name: first\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"YAML|yaml"):
        g.symbols(str(y), bases={"DATA": 0x400})


@pytest.mark.parametrize("text", ["", "# only a comment\n\n# and another\n"])
def test_a_file_with_nothing_in_it_given_with_bases_is_refused_for_its_emptiness(
    tmp_path: Path, text: str,
) -> None:
    """An empty or comment-only file is refused for its ZERO symbols."""
    f = tmp_path / "s.yaml"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=r"ZERO symbols") as e:
        g.symbols(str(f), bases={"DATA": 0x400})
    assert "YAML symbol file" not in str(e.value)
    with pytest.raises(ValueError, match=r"ZERO symbols"):
        g.symbols(str(f))


def test_a_malformed_row_in_a_map_is_refused_with_its_line(tmp_path: Path) -> None:
    """In a file that IS a map, a tabbed line that is not five fields is a broken row."""
    m = tmp_path / "game.map"
    m.write_text("_start\tED000\t_TEXT\t0\tCODE\nbroken\tED100\t_TEXT\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":2\b.*3 TAB"):
        g.symbols(str(m))





def test_self_check_slices_the_reference_image_from_its_base() -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    image = bytes(range(64))
    ses = reading_session(image, 0x20000)
    ses.self_check(image, 0x20010, n=16, base=0x20000, thread=1)
    ses.self_check(image, 0x20030, n=16, base=0x20000, thread=1)
    ses.self_check(image, 0x20038, n=8, base=0x20000, thread=1)
    cpu_space = bytes(0x20000) + image
    ses.self_check(cpu_space, 0x20010, n=16, thread=1)


def test_an_address_outside_the_reference_image_is_not_a_lie() -> None:
    """Below the base, or past the end, the file has no opinion."""
    image = bytes(range(64))
    ses = reading_session(image, 0x20000)
    for addr, n in ((0x1FFFF, 16), (0x20031, 16), (0x20038, 16)):
        with pytest.raises(g.SessionError, match=r"OUTSIDE") as e:
            ses.self_check(image, addr, n=n, base=0x20000, thread=1)
        assert "LIES" not in str(e.value)
        assert "64" in str(e.value) and "0x20000" in str(e.value), (
            "the refusal names the image's length and its base"
        )
        assert "0x2003f" in str(e.value), "and its LAST byte, inclusive, not one past it"


def test_the_port_probe_does_not_consume_the_gdbstub_connection() -> None:
    """Regression."""
    import socket as _s

    from scry_mame.launch import port_is_free

    with _s.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        assert not port_is_free(port), "reported as free a port that is taken"

        listener.settimeout(0.2)
        try:
            conn, _ = listener.accept()
            conn.close()
            raise AssertionError("the probe CONNECTED: it ate the gdbstub's connection")
        except TimeoutError:
            pass


def test_the_port_probe_sees_a_session_the_stub_is_still_serving() -> None:
    """MAME's shape after it accepts."""
    import socket as _s

    from scry_mame.launch import port_is_free

    listener = _s.socket()
    listener.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = _s.create_connection(("127.0.0.1", port))
    served, _ = listener.accept()
    listener.close()
    try:
        assert not port_is_free(port), "a session still being served was called free"
        with _s.socket() as reuse:
            reuse.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
            reuse.bind(("127.0.0.1", port))
    finally:
        served.close()
        client.close()


def test_the_boot_harness_reaches_the_mame_command_line() -> None:
    """The missing flag, and why it is tested here instead of by looking at the process."""
    from scry_mame.launch import build_command

    cmd = build_command("/bin/mame", "m68k-dual", "/roms", 23946, ["-window"],
                        "/scratch/mame-mcp-t", boot_lua="/tmp/harness.lua")

    assert "-autoboot_script" in cmd
    assert cmd[cmd.index("-autoboot_script") + 1] == "/tmp/harness.lua"
    assert cmd[cmd.index("-autoboot_delay") + 1] == "0"


def test_without_a_harness_no_autoboot_slips_through() -> None:
    """The negative case."""
    from scry_mame.launch import build_command

    cmd = build_command("/bin/mame", "m68k-dual", "/roms", 23946, ["-window"],
                        "/scratch/mame-mcp-t")

    assert "-autoboot_script" not in cmd
    assert "-autoboot_delay" not in cmd


def test_the_gdbstub_and_its_port_always_go() -> None:
    """What makes the session EXIST must not depend on any optional parameter."""
    from scry_mame.launch import build_command

    cmd = build_command(
        "/bin/mame", "m68k-dual", "/roms", 23947, ["-window"], "/scratch/mame-mcp-t", inipath="/ini"
    )

    assert cmd[:2] == ["/bin/mame", "m68k-dual"]
    assert "-debug" in cmd and "gdbstub" in cmd
    assert cmd[cmd.index("-debugger_port") + 1] == "23947"
    assert cmd[cmd.index("-inipath") + 1] == "/ini"




def _session_with(xml: str, endianness: str = "") -> g.Session:
    """A Session whose register map came from THIS target description and nothing else."""

    def canned(cmd: str, timeout: float | None = None) -> str:
        return ("l" + xml) if cmd.startswith("qXfer") else ""

    ses = g.Session()
    ses.request = canned  # type: ignore[method-assign]
    ses.layout(1)
    if endianness:
        ses.know_endianness({1: endianness})
    return ses


M68K = """<target><architecture>m68k</architecture>\n<feature name="org.gnu.gdb.m68k.core">
<reg name="d0" bitsize="32" type="int"/><reg name="fp" bitsize="32" type="int"/>
<reg name="sp" bitsize="32" type="int"/><reg name="ps" bitsize="32" type="int"/>
<reg name="pc" bitsize="32" type="code_ptr"/></feature></target>"""

I386 = """<target><architecture>i386</architecture>\n<feature name="org.gnu.gdb.i386.core">
<reg name="eax" bitsize="32" type="int"/><reg name="esp" bitsize="32" type="data_ptr"/>
<reg name="eip" bitsize="32" type="code_ptr"/><reg name="cs" bitsize="32" type="int"/>
</feature></target>"""


def test_a_registers_width_is_the_one_the_description_declares() -> None:
    """The display must not pad every value to eight hex digits whatever the cpu says."""
    narrow = """<target><architecture>i386</architecture>
    <feature name="org.gnu.gdb.i386.core"><reg name="eax" bitsize="16" type="int"/>
    <reg name="eip" bitsize="16" type="code_ptr"/></feature></target>"""
    assert _session_with(narrow).layout(1).register_bits == {"EAX": 16, "EIP": 16}
    wide = _session_with(M68K).layout(1).register_bits
    assert set(wide.values()) == {32}
    assert "A7" not in wide, "an alias has no width of its own to report"


def test_the_program_counter_is_found_on_a_68000() -> None:
    """The spelling GDB's m68k feature mandates."""
    assert _session_with(M68K).layout(1).pc_name == "PC"


def test_the_program_counter_is_found_on_an_x86() -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    assert _session_with(I386).layout(1).pc_name == "EIP"


def test_the_program_counter_is_found_on_an_amd64() -> None:
    """`rip`, the third spelling the standard features define."""
    xml = I386.replace('name="eip"', 'name="rip"')
    assert _session_with(xml).layout(1).pc_name == "RIP"


def test_a_second_code_ptr_does_not_steal_the_program_counter() -> None:
    """Keying on the TYPE alone is the tempting wrong answer."""
    xml = M68K.replace("</feature>", '<reg name="lr" bitsize="32" type="code_ptr"/></feature>')
    assert _session_with(xml).layout(1).pc_name == "PC"


def test_an_unfamiliar_name_falls_back_to_a_lone_code_ptr() -> None:
    """A cpu whose feature GDB does not standardise still resolves, when it is unambiguous."""
    xml = """<target><feature name="x"><reg name="acc" bitsize="16" type="int"/>
    <reg name="iar" bitsize="16" type="code_ptr"/></feature></target>"""
    assert _session_with(xml).layout(1).pc_name == "IAR"


def test_an_unresolvable_program_counter_is_refused_not_guessed() -> None:
    """Two candidates and no standard name."""
    xml = """<target><feature name="x"><reg name="acc" bitsize="16" type="int"/>
    <reg name="iar" bitsize="16" type="code_ptr"/>
    <reg name="lr" bitsize="16" type="code_ptr"/></feature></target>"""
    ses = _session_with(xml)
    try:
        resolved = ses.layout(1).pc_name
    except g.SessionError as e:
        assert "IAR" in str(e) and "LR" in str(e), f"the refusal must name what it saw: {e}"
    else:
        raise AssertionError(f"it guessed {resolved!r} instead of refusing")




def test_an_x86_target_decodes_little_endian() -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    assert _session_with(I386, "little").layout(1).byte_order == "little"


def test_a_68000_target_decodes_big_endian() -> None:
    assert _session_with(M68K, "big").layout(1).byte_order == "big"


def _refused(ses: g.Session) -> str:
    try:
        order = ses.layout(1).byte_order
    except g.UnknownByteOrder as e:
        return str(e)
    raise AssertionError(f"it decoded in {order!r} where it had to refuse")


def test_a_cpu_whose_endianness_mame_did_not_give_refuses_whatever_its_row() -> None:
    """The order is MAME's."""
    assert "MAME" in _refused(_session_with(I386)) and "i386" in _refused(_session_with(I386))


def test_mame_disagreeing_with_a_measured_row_refuses_naming_both() -> None:
    """A row is a measurement."""
    why = _refused(_session_with(M68K, "little"))
    assert "little" in why and "big" in why and "m68k" in why, why


def test_an_architecture_with_no_row_is_decoded_in_mames_order() -> None:
    """`mips` gets no row, ever."""
    xml = M68K.replace("m68k.core", "mips.core")
    xml = xml.replace("<target>", "<target><architecture>mips</architecture>")
    assert _session_with(xml, "little").layout(1).byte_order == "little"
    assert _session_with(xml, "big").layout(1).byte_order == "big"
    assert "mips" in _refused(_session_with(xml)), "no word from MAME is still a refusal"


@pytest.mark.parametrize(("arch", "order"), [
    ("m6502", "little"), ("z80", "little"), ("m6809", "big"), ("arm", "little"),
    ("powerpc:common", "big"), ("score7", "little"), ("nios2", "little")])
def test_the_architectures_measured_have_their_order(arch: str, order: str) -> None:
    """Each recorded row."""
    assert g.Layout({}, 0, arch, [], mame_order=order).byte_order == order
    other = "big" if order == "little" else "little"
    with pytest.raises(g.UnknownByteOrder):
        _ = g.Layout({}, 0, arch, [], mame_order=other).byte_order


def test_a_description_with_no_architecture_takes_mames_order_and_no_more() -> None:
    """Absence is not a default."""
    xml = M68K.replace("<architecture>m68k</architecture>", "")
    assert _session_with(xml, "big").layout(1).byte_order == "big"
    assert "none declared" in _refused(_session_with(xml))


def test_mames_word_reaches_a_layout_read_before_it_and_one_read_after() -> None:
    """`start` reads the first description during the boot."""
    ses = _session_with(M68K)
    kept = ses.layout(1)
    ses.know_endianness({1: "big"})
    assert ses.layout(1).byte_order == "big" and kept.mame_order == ""




def test_quit_schedules_through_the_console_and_then_lets_the_machine_run() -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    sent: list[str] = []

    def request(cmd: str, timeout: float | None = None) -> str:
        sent.append(cmd)
        return "0a"

    def send(cmd: str) -> None:
        sent.append(cmd)

    ses = g.Session()
    ses.request = request  # type: ignore[method-assign]
    ses._send = send  # type: ignore[method-assign]
    ses.quit()
    assert sent == ["qRcmd," + b"quit".hex(), "c"], sent




class _Wire:
    """A socket that answers from a scripted list of PACKETS, one `recv` per packet."""

    def __init__(self, packets: list[str], send_error: OSError | None = None) -> None:
        self.packets = [f"${p}#{g._checksum(p)}".encode() for p in packets]
        self.sent: list[bytes] = []
        self.send_error = send_error
        self.closed = False

    def sendall(self, data: bytes) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True

    def settimeout(self, seconds: float) -> None:
        pass

    def recv(self, n: int) -> bytes:
        if not self.packets:
            raise TimeoutError
        return self.packets.pop(0)


def _wired(packets: list[str]) -> tuple[g.Session, _Wire]:
    wire = _Wire(packets)
    ses = g.Session(timeout=0.2)
    ses._sock = wire  # type: ignore[assignment]
    return ses, wire


def test_a_stop_reply_is_told_from_an_answer() -> None:
    for packet in ("T050e:00000000;", "T05", "T0b"):
        assert g._is_stop_reply(packet), packet
    for packet in ("OK", "46fc2700", "E01", "", "l<target/>", "5468"):
        assert not g._is_stop_reply(packet), packet


_NEVER_SENT = ["S05", "S0B", "W00", "X09"]


@pytest.mark.parametrize("packet", _NEVER_SENT)
def test_a_stop_shape_the_stub_never_sends_is_refused_by_name(packet: str) -> None:
    """The protocol also defines `S`, `W` and `X` stop replies, and MAME's stub builds `T` only."""
    with pytest.raises(g.SessionError, match="a stop reply of a shape MAME's stub never sends"):
        g._is_stop_reply(packet)


@pytest.mark.parametrize("packet", _NEVER_SENT)
@pytest.mark.parametrize("wait", ["poll_stop", "resume", "interrupt", "step", "request"])
def test_every_wait_for_a_stop_refuses_the_shapes_the_stub_never_sends(
    wait: str, packet: str,
) -> None:
    ses, _wire = _wired([packet])
    if wait in ("poll_stop", "interrupt", "request"):
        ses.go()
    asks: dict[str, Callable[[], object]] = {
        "poll_stop": lambda: ses.poll_stop(0.0), "resume": lambda: ses.resume(0.2),
        "interrupt": lambda: ses.interrupt(0.2), "step": ses.step,
        "request": lambda: ses.request("Z0,4a0,2")}
    with pytest.raises(g.SessionError, match="never sends"):
        asks[wait]()
    assert ses.stop_count == 0, "a refused shape is not counted as a stop"


def test_a_stop_packet_landing_in_front_of_an_answer_is_read_as_the_stop() -> None:
    """A `Z0` sent to a running machine can be answered BEHIND the stop it just reached."""
    ses, wire = _wired(["T050e:00000000;0f:00200fea;11:000004a0;", "OK"])
    ses.go()
    before = (ses.running, ses.stop_count)
    assert before == (True, 0) and wire.sent[-1] == b"$c#63"
    assert ses.request("Z0,4a0,2") == "OK"
    after = (ses.running, ses.stop_count)
    assert after == (False, 1)
    assert ses.last_stop_packet.startswith("T05")


STUB_UNSUPPORTED = ""
STUB_SILENT_CONSOLE = "0A"


def test_an_empty_reply_is_the_stubs_unsupported_and_never_a_success() -> None:
    """`request` must refuse more than `E` followed by two digits."""
    for cmd in ("P0=deadbeef", "M4a0,1:00", "Z0,4a0,2", "qFooUnsupported"):
        ses, wire = _wired([STUB_UNSUPPORTED])
        with pytest.raises(g.SessionError, match="does not support"):
            ses.request(cmd)
        assert wire.sent[-2].startswith(b"$" + cmd.encode()), wire.sent
    ses, _wire = _wired([STUB_UNSUPPORTED])
    with pytest.raises(g.SessionError, match="does not support"):
        ses.write(0x4A0, b"\x00", thread=1)
    assert ses.writes == 1
    ses, _wire = _wired(["E01"])
    with pytest.raises(g.SessionError, match="refused"):
        ses.request("P0=deadbeef")
    ses, _wire = _wired(["OK"])
    assert ses.request("Z0,4a0,2") == "OK"
    ses, _wire = _wired([STUB_SILENT_CONSOLE])
    assert ses.monitor("quit") == "\n", "a silent console command is an answer, not unsupported"


def test_poll_stop_answers_false_on_a_running_machine_with_no_stop_yet() -> None:
    ses, _wire = _wired([])
    ses.go()
    assert ses.poll_stop(0.0) is False and ses.running
    ses2, _wire2 = _wired(["T05"])
    ses2.go()
    assert ses2.poll_stop(0.0) is True and not ses2.running and ses2.stop_count == 1
    assert ses2.poll_stop(0.0) is True, "a stopped machine answers without the socket"


def test_something_other_than_a_stop_while_running_is_a_distrusted_session() -> None:
    ses, _wire = _wired(["46fc2700"])
    ses.go()
    with pytest.raises(g.SessionError, match="not a stop reply"):
        ses.poll_stop(0.0)


def test_interrupt_sends_nothing_to_a_stopped_machine() -> None:
    """A 0x03 to a machine already stopped in the debugger is answered with NOTHING."""
    ses, wire = _wired([])
    ses.last_stop_packet = "T05"
    assert ses.interrupt() == "T05"
    assert wire.sent == []
    ses.go()
    wire.packets = [f"$T05#{g._checksum('T05')}".encode()]
    assert ses.interrupt().startswith("T05") and not ses.running
    assert wire.sent[-2:] == [b"\x03", b"+"], "the interrupt, then the ack of its reply"


def test_halt_sends_the_interrupt_and_waits_for_nothing() -> None:
    """A run the CONSOLE started (`gtime`) sends no stop packet."""
    ses, wire = _wired([])
    ses.halt()
    assert wire.sent == [b"\x03"]


def test_a_watch_stop_arrives_as_its_own_packet_and_is_noted_as_any_stop() -> None:
    """A watchpoint's stop arrives as `T05watch:<addr>;`, read and noted like any other stop."""
    ses, _wire = _wired(["T05watch:2031fc;0e:00000000;11:000025f6;"])
    ses.go()
    assert ses.poll_stop(0.0) is True and ses.last_stop_packet.startswith("T05watch:2031fc;")
    assert ses.writes == 0 and ses.stop_count == 1


def test_a_timeout_is_its_own_exception_type_and_poll_stop_reads_the_type_not_the_words() -> None:
    """`poll_stop` told a timeout from a broken session by a SUBSTRING of the message."""
    ses, _wire = _wired([])
    with pytest.raises(g.Timeout):
        ses._receive(0.0)
    assert issubclass(g.Timeout, g.SessionError)
    ses.go()
    assert ses.poll_stop(0.0) is False

    class _Closing:
        def sendall(self, data: bytes) -> None:
            pass

        def settimeout(self, seconds: float) -> None:
            pass

        def recv(self, n: int) -> bytes:
            raise ConnectionResetError("no answer within the stub's lifetime")

    broken, _wire = _wired([])
    broken._sock = _Closing()  # type: ignore[assignment]
    broken.go()
    with pytest.raises(g.SessionError, match="the connection failed") as raised:
        broken.poll_stop(0.0)
    assert raised.type is g.ConnectionFailed, "a failed connection is never a wait that ran out"




@pytest.mark.parametrize("release", ["resume", "interrupt", "step"])
@pytest.mark.parametrize("packet", ["OK", "46fc2700"])
def test_a_release_that_reads_something_other_than_a_stop_raises_as_poll_stop_does(
    release: str, packet: str,
) -> None:
    """A stray packet is never handed back in silence."""
    ses, _wire = _wired([packet])
    if release == "interrupt":
        ses.go()
    asks: dict[str, Callable[[], object]] = {
        "resume": lambda: ses.resume(0.2), "interrupt": lambda: ses.interrupt(0.2),
        "step": ses.step}
    with pytest.raises(g.SessionError) as raised:
        asks[release]()
    assert str(raised.value) == (f"the stub sent {packet!r} while the machine ran, which is "
                                 "not a stop reply: the session cannot be trusted")
    assert ses.stop_count == 0 and ses.running is True


@pytest.mark.parametrize("release", ["resume", "interrupt", "step"])
def test_a_release_still_hands_back_the_stop_packet_it_read(release: str) -> None:
    ses, _wire = _wired(["T050e:00000000;"])
    if release == "interrupt":
        ses.go()
    asks: dict[str, Callable[[], str]] = {
        "resume": lambda: ses.resume(0.2), "interrupt": lambda: ses.interrupt(0.2),
        "step": ses.step}
    assert asks[release]() == "T050e:00000000;"
    assert (ses.running, ses.stop_count) == (False, 1)




class _FailingWire(_Wire):
    """A wire whose `recv`, or `sendall` of one payload, raises a dead connection's `OSError`."""

    def __init__(self, packets: list[str], error: OSError, on_recv: bool = False,
                 on_send: bytes | None = None, on_settimeout: bool = False) -> None:
        super().__init__(packets)
        self.error, self.on_recv, self.on_send = error, on_recv, on_send
        self.on_settimeout = on_settimeout

    def sendall(self, data: bytes) -> None:
        if self.on_send is not None and data.startswith(self.on_send):
            raise self.error
        super().sendall(data)

    def settimeout(self, seconds: float) -> None:
        if self.on_settimeout:
            raise self.error

    def recv(self, n: int) -> bytes:
        if self.on_recv:
            raise self.error
        return super().recv(n)


def _failing(packets: list[str], error: OSError, on_recv: bool = False,
             on_send: bytes | None = None, on_settimeout: bool = False) -> g.Session:
    ses = g.Session(timeout=0.2)
    ses._sock = _FailingWire(packets, error, on_recv, on_send,  # type: ignore[assignment]
                             on_settimeout)
    return ses


_DEAD = [ConnectionResetError(54, "Connection reset by peer"), BrokenPipeError(32, "Broken pipe")]


@pytest.mark.parametrize("error", _DEAD)
@pytest.mark.parametrize("site", ["send", "recv", "settimeout", "ack", "halt", "interrupt"])
def test_a_connection_that_failed_is_a_session_error_at_every_site_that_touches_the_socket(
    site: str, error: OSError,
) -> None:
    """Every handler above the packet layer catches `SessionError` and nothing else."""
    asks: dict[str, tuple[g.Session, Callable[[g.Session], object]]] = {
        "send": (_failing([], error, on_send=b"$"), lambda ses: ses.request("m0,4")),
        "recv": (_failing([], error, on_recv=True), lambda ses: ses.request("m0,4")),
        "settimeout": (_failing([], error, on_settimeout=True),
                       lambda ses: ses.request("m0,4")),
        "ack": (_failing(["OK"], error, on_send=b"+"), lambda ses: ses.request("m0,4")),
        "halt": (_failing([], error, on_send=b"\x03"), lambda ses: ses.halt()),
        "interrupt": (_failing([], error, on_send=b"\x03"), lambda ses: ses.interrupt(0.2)),
    }
    ses, ask = asks[site]
    ses.running = site == "interrupt"
    with pytest.raises(g.SessionError) as raised:
        ask(ses)
    assert str(raised.value) == f"the connection failed: {error}"
    assert raised.type is g.ConnectionFailed and issubclass(g.ConnectionFailed, g.SessionError)


def test_a_connection_the_stub_closed_is_a_failed_connection_too() -> None:
    class _Closed(_Wire):
        def recv(self, n: int) -> bytes:
            return b""

    ses = g.Session(timeout=0.2)
    ses._sock = _Closed([])  # type: ignore[assignment]
    with pytest.raises(g.ConnectionFailed, match="the stub closed the connection"):
        ses.request("m0,4")


def test_a_wait_that_ran_out_is_still_a_timeout_and_never_a_failed_connection() -> None:
    """`TimeoutError` IS an `OSError`."""
    assert issubclass(TimeoutError, OSError)
    ses = _failing([], TimeoutError("timed out"), on_recv=True)
    with pytest.raises(g.Timeout):
        ses._receive(0.0)
    ses.go()
    assert ses.poll_stop(0.0) is False and ses.running


def test_the_register_file_is_read_in_one_g_packet_at_the_stubs_own_widths() -> None:
    """A stop survey reads the register file in one `g`, not one `p` per register."""
    narrow = """<target><architecture>i386</architecture>
    <feature name="org.gnu.gdb.i386.core"><reg name="eax" bitsize="16" type="int"/>
    <reg name="eip" bitsize="16" type="code_ptr"/><reg name="fl" bitsize="8" type="int"/>
    </feature></target>"""
    ses = _session_with(narrow, "little")
    asked: list[str] = []

    def request(cmd: str, timeout: float | None = None) -> str:
        asked.append(cmd)
        return "568b" "0002" "a5"

    ses.request = request  # type: ignore[method-assign]
    assert ses.registers(thread=1) == {"EAX": 0x8B56, "EIP": 0x0200, "FL": 0xA5}
    assert asked == ["g"], "one round trip for the whole file"
    ses.request = lambda cmd, timeout=None: "568b00"  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="6 hex digits"):
        ses.registers(thread=1)
    m68k = _session_with(M68K, "big")
    m68k.request = lambda cmd, timeout=None: "".join(  # type: ignore[method-assign]
        f"{v:08x}" for v in (0x1111, 0x2222, 0x3333, 0x4444, 0x5555))
    assert m68k.registers(thread=1) == {"D0": 0x1111, "FP": 0x2222, "SP": 0x3333, "PS": 0x4444,
                                "PC": 0x5555}


def test_an_alias_answers_the_width_of_the_register_it_aliases() -> None:
    """`register_bits` lists the description's own file and no alias, on purpose."""
    narrow = """<target><architecture>m68k</architecture>
    <feature name="org.gnu.gdb.m68k.core"><reg name="d0" bitsize="16" type="int"/>
    <reg name="sp" bitsize="16" type="data_ptr"/><reg name="pc" bitsize="32" type="code_ptr"/>
    </feature></target>"""
    ses = _session_with(narrow, "little")
    assert ses.layout(1).register_width("A7") == 16 and ses.layout(1).register_width("sp") == 16
    assert ses.layout(1).register_width("PC") == 32
    with pytest.raises(g.SessionError, match="unknown register"):
        ses.layout(1).register_width("EAX")


def test_a_soft_reset_is_scheduled_stepped_into_and_counted_as_a_write() -> None:
    """The console's `softreset` is a timer that fires when the machine next runs."""
    ses = g.Session()
    sent: list[str] = []

    def monitor(command: str, timeout: float = 10.0) -> str:
        sent.append(command)
        return ""

    def step() -> str:
        sent.append("s")
        return "T05thread:1;"

    ses.monitor = monitor  # type: ignore[method-assign]
    ses.step = step  # type: ignore[method-assign]
    ses.current_pc = lambda: 0xF2034  # type: ignore[method-assign]
    assert ses.reset() == 0xF2034
    assert sent == ["softreset", "s"] and ses.writes == 1


def test_a_16_bit_register_answers_to_its_short_name_and_a_32_bit_one_does_not() -> None:
    """A register a map serves 16 bits wide under an `E`-prefixed name answers to its short name."""
    narrow = """<target><architecture>i386</architecture>
    <feature name="org.gnu.gdb.i386.core"><reg name="eax" bitsize="16" type="int"/>
    <reg name="eip" bitsize="16" type="code_ptr"/></feature></target>"""
    ses = _session_with(narrow, "little")
    lay = ses.layout(1)
    assert lay.register_name("ax") == "EAX" and lay.register_name("EIP") == "EIP"
    assert lay.register_width("ip") == 16
    asked: list[str] = []

    def request(cmd: str, timeout: float | None = None) -> str:
        asked.append(cmd)
        return "3412"

    ses.request = request  # type: ignore[method-assign]
    assert ses.reg("ax", thread=1) == 0x1234 and asked == ["p0"]
    wide = """<target><architecture>i386</architecture>
    <feature name="org.gnu.gdb.i386.core"><reg name="eax" bitsize="32" type="int"/>
    </feature></target>"""
    with pytest.raises(g.SessionError, match="unknown register 'ax'"):
        _session_with(wide).layout(1).register_name("ax")


NEC = (Path(__file__).resolve().parent / "fixtures" / "stub-nec" / "target.xml").read_text()
"""CAPTURED from MAME's own stub on a V30 board (`qXfer:features:read:target.xml`), never
typed: the map it describes is MAME's `gdb_register_map_nec`."""


TWO_CPUS = Path(__file__).resolve().parent / "fixtures" / "stub-two-cpus"


def _two_cpus() -> g.Session:
    """The captured description of a board whose stub appends another device's state."""
    return _session_with((TWO_CPUS / "target.xml").read_text(), "big")


def test_another_devices_appended_state_is_not_a_register_of_this_cpu() -> None:
    """The stub appends other devices' state after the main cpu's registers."""
    ses = _two_cpus()
    names = ses.layout(1).register_names
    assert names[:2] == ["D0", "D1"] and names[-1] == "PC" and len(names) == 18, names
    assert "IR" not in names and "CURPC" not in names
    assert ses.layout(1).regs["D0"].number == 0 and ses.layout(1).regs["PC"].number == 17


def test_the_g_reply_of_a_stub_that_appends_other_devices_is_cut_at_this_cpus_registers() -> None:
    """`g` carries every register the description declares, the appended ones included."""
    ses = _two_cpus()
    reply = (TWO_CPUS / "g.reply").read_text()
    by_p = json.loads((TWO_CPUS / "p.json").read_text())
    ses.request = lambda cmd, timeout=None: reply if cmd == "g" else ""  # type: ignore[method-assign]
    got = ses.registers(thread=1)
    assert list(got) == ses.layout(1).register_names
    assert got == {n.upper(): int(v, 16) for n, v in by_p.items()}, got
    assert got["PC"] != 0, "a parked 68000 has a program counter; all zeros is no control"
    ses.request = lambda cmd, timeout=None: reply[:-1] if cmd == "g" else ""  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="hex digits"):
        ses.registers(thread=1)


def test_a_feature_named_mame_without_the_slash_is_still_this_cpus() -> None:
    """Only `mame./<tag>` is another device."""
    xml = """<target><architecture>z80</architecture><feature name="mame.z80">
    <reg name="af" bitsize="16" type="int"/><reg name="pc" bitsize="16" type="code_ptr"/>
    </feature></target>"""
    assert _session_with(xml).layout(1).register_names == ["AF", "PC"]


def test_another_devices_state_numbered_before_this_cpus_is_refused_not_misread() -> None:
    """The `g` reply is cut from its start at this cpu's widths."""
    xml = """<target><architecture>m68k</architecture>
    <feature name="mame./subcpu"><reg name="X" bitsize="32" type="int"/></feature>
    <feature name="org.gnu.gdb.m68k.core"><reg name="d0" bitsize="32" type="int"/>
    <reg name="pc" bitsize="32" type="code_ptr"/></feature></target>"""
    with pytest.raises(g.SessionError, match="before this cpu"):
        _session_with(xml)


def test_a_16_bit_x86_target_decodes_little_endian() -> None:
    """The stub serves the NEC family as `i8086` once it can."""
    assert _session_with(NEC, "little").layout(1).byte_order == "little"


def test_a_pointer_is_as_wide_as_the_stack_pointer_not_the_program_counter() -> None:
    """`eip` is a 32-bit linear address on the V30, wider than a near pointer."""
    ses = _session_with(NEC, "little")
    assert ses.layout(1).register_width("EIP") == 32, "the case only discriminates if eip is wider"
    assert ses.layout(1).pointer_width == 2
    assert _session_with(M68K).layout(1).pointer_width == 4


def test_the_stack_pointer_is_found_by_name_not_by_position_or_type() -> None:
    """A description whose FIRST register is a wide `data_ptr`."""
    xml = """<target><architecture>m68k</architecture><feature name="org.gnu.gdb.m68k.core">
    <reg name="fp" bitsize="32" type="data_ptr"/><reg name="d0" bitsize="32" type="int"/>
    <reg name="sp" bitsize="16" type="int"/><reg name="pc" bitsize="32" type="code_ptr"/>
    </feature></target>"""
    assert _session_with(xml).layout(1).pointer_width == 2


def test_a_description_with_no_stack_pointer_falls_back_to_the_program_counter() -> None:
    only_pc = """<target><architecture>m68k</architecture><feature name="org.gnu.gdb.m68k.core">
    <reg name="d0" bitsize="32" type="int"/><reg name="pc" bitsize="16" type="code_ptr"/>
    </feature></target>"""
    assert _session_with(only_pc).layout(1).pointer_width == 2


def test_the_register_file_is_cut_at_each_declared_width() -> None:
    """Each V30 register prints at its declared width."""
    ses = _session_with(NEC, "little")
    widths = [ses.layout(1).register_bits[n] for n in ses.layout(1).register_names]
    assert len(widths) == 32 and 80 in widths and 16 in widths and 32 in widths
    values = {n: (i + 1) * 0x11 for i, n in enumerate(ses.layout(1).register_names)}
    file = "".join(values[n].to_bytes(ses.layout(1).register_bits[n] // 8, "little").hex()
                   for n in ses.layout(1).register_names)
    ses.request = lambda cmd, timeout=None: file if cmd == "g" else ""  # type: ignore[method-assign]
    assert ses.registers(thread=1) == values
    short = file[:-2]
    ses.request = lambda cmd, timeout=None: short if cmd == "g" else ""  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="hex digits"):
        ses.registers(thread=1)


def test_the_packet_size_the_stub_advertises_is_read_off_qsupported() -> None:
    """A packet longer than the stub's advertised `PacketSize` is never sent."""
    assert g.packet_size("PacketSize=4000;qXfer:features:read+") == 0x4000
    assert g.packet_size("qXfer:features:read+;PacketSize=400") == 0x400
    assert g.packet_size("qXfer:features:read+") is None
    assert g.packet_size("") is None


_PATCHED_THREADS = {"qfThreadInfo": "m1,2", "qsThreadInfo": "l",
                    "qThreadExtraInfo,1": b":maincpu".hex(),
                    "qThreadExtraInfo,2": b":subcpu".hex()}
_UNPATCHED_THREADS = {"qfThreadInfo": "m1", "qsThreadInfo": "l", "qThreadExtraInfo,1": ""}


@pytest.mark.parametrize(("answers", "threads"), [
    (_PATCHED_THREADS, {1: ":maincpu", 2: ":subcpu"}),
    (_UNPATCHED_THREADS, {}),
    ({"qfThreadInfo": "m1", "qsThreadInfo": ["m2", "l"],
      "qThreadExtraInfo,1": b":maincpu".hex(),
      "qThreadExtraInfo,2": b":subcpu".hex()}, {1: ":maincpu", 2: ":subcpu"}),
], ids=["patched", "unpatched", "paged"])
def test_the_threads_are_read_off_the_stub_and_a_stub_with_none_serves_the_first_cpu(
        answers: dict[str, Any], threads: dict[int, str]) -> None:
    """Which thread is which cpu is the stub's own answer, read once at `connect`."""
    pages = {k: list(v) if isinstance(v, list) else [v] for k, v in answers.items()}

    def canned(cmd: str, timeout: float | None = None) -> str:
        r = str(pages[cmd].pop(0) if len(pages[cmd]) > 1 else pages[cmd][0])
        if r == "":
            raise g.Unsupported(f"the stub does not support `{cmd}`")
        return r

    ses = g.Session()
    ses.request = canned  # type: ignore[method-assign]
    assert ses._read_threads() == threads


def test_connect_reads_the_threads_after_the_register_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handshake asks the stub its threads once, after the register map."""
    wire = _Wire(["PacketSize=4000", "l" + M68K, *(_PATCHED_THREADS[k] for k in (
        "qfThreadInfo", "qsThreadInfo", "qThreadExtraInfo,1", "qThreadExtraInfo,2"))])
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: wire)
    ses = g.Session(timeout=0.2)
    ses.dial()
    ses.handshake()
    assert ses.threads == {1: ":maincpu", 2: ":subcpu"}
    assert _packets(wire)[-4:] == ["qfThreadInfo", "qsThreadInfo", "qThreadExtraInfo,1",
                                   "qThreadExtraInfo,2"]


def test_a_description_with_no_register_and_one_that_is_not_xml_are_their_own_errors() -> None:
    """A well-formed `<target>` that declares no `reg` is `NoRegisters`."""
    with pytest.raises(g.NoRegisters, match="declares no registers"):
        _session_with("<target><architecture>m68k</architecture></target>")
    with pytest.raises(g.BadTargetXml, match="not a well-formed"):
        _session_with("")
    for reg in ('<reg name="d0" bitsize="x"/>', '<reg name="d0" regnum="zz" bitsize="32"/>'):
        with pytest.raises(g.BadTargetXml, match="not a number"):
            _session_with(f"<target><architecture>m68k</architecture>{reg}</target>")


def test_a_packet_size_that_is_not_hex_is_a_session_error_of_the_handshake() -> None:
    """A garbled `qSupported` is the stub's failure, marked with its phase."""
    ses, _wire = _wired(["PacketSize=zz"])
    with pytest.raises(g.SessionError, match="PacketSize") as got:
        ses.handshake()
    assert got.value.phase == "qSupported"


_NO_REGS = "<target><architecture>m68k</architecture></target>"


@pytest.mark.parametrize(("packets", "error", "phase", "reply"), [
    (["E01"], g.Refused, "qSupported", "E01"),
    (["PacketSize=4000", "E01"], g.Refused, "target.xml", "E01"),
    (["PacketSize=4000", "l" + _NO_REGS], g.NoRegisters, "target.xml", _NO_REGS),
    (["PacketSize=4000", "l<target><arch"], g.BadTargetXml, "target.xml", "<target><arch"),
    (["PacketSize=4000", "l" + M68K, "E01"], g.Refused, "threads", "E01"),
    (["PacketSize=4000"], g.Timeout, "target.xml", ""),
    (["PacketSize=4000", "l" + M68K, "mzz"], g.SessionError, "threads", ""),
], ids=["qsupported-refused", "xml-refused", "no-registers", "bad-xml", "threads-refused",
        "xml-timeout", "threads-not-hex"])
def test_a_handshake_failure_says_where_it_failed_and_what_the_stub_answered(
        packets: list[str], error: type[g.SessionError], phase: str, reply: str) -> None:
    """Which of the handshake's three questions failed, and the stub's own answer to it."""
    ses, _wire = _wired(packets)
    with pytest.raises(error) as got:
        ses.handshake()
    assert (got.value.phase, got.value.reply) == (phase, reply)


def test_the_answer_a_handshake_failure_keeps_is_cut_to_two_hundred_characters() -> None:
    """The reply rides on a refusal and into `start_retries`."""
    doc = "<target><architecture>" + "x" * 300 + "</architecture></target>"
    ses, _wire = _wired(["PacketSize=4000", "l" + doc])
    with pytest.raises(g.NoRegisters) as got:
        ses.handshake()
    assert got.value.reply == doc[:g.REPLY_KEPT_CHARS] and len(doc) > g.REPLY_KEPT_CHARS


class _Endless(_Wire):
    """A stub that never sends the closing `l` and falls silent after `ENDLESS_CHUNKS`."""

    ENDLESS_CHUNKS = 500
    CHUNK_EVERY_S = 0.01

    def __init__(self, packets: list[str], page: str = "m<a>") -> None:
        super().__init__(packets)
        self.page = f"${page}#{g._checksum(page)}".encode()

    def recv(self, n: int) -> bytes:
        if self.packets:
            return self.packets.pop(0)
        if len(self.sent) > self.ENDLESS_CHUNKS:
            raise TimeoutError
        time.sleep(self.CHUNK_EVERY_S)
        return self.page


def test_a_description_that_never_ends_stops_at_the_handshakes_deadline() -> None:
    """The description is read in chunks until one starts with `l`."""
    wire = _Endless(["PacketSize=4000"])
    ses = g.Session(timeout=0.2)
    ses._sock = wire  # type: ignore[assignment]
    began = time.monotonic()
    with pytest.raises(g.Timeout, match="target.xml") as got:
        ses.handshake(0.1)
    assert got.value.phase == "target.xml" and time.monotonic() - began < 1.0
    assert 2 < len(_packets(wire)) < _Endless.ENDLESS_CHUNKS, "it stopped at the deadline"


def test_a_thread_list_that_never_ends_stops_at_the_handshakes_deadline() -> None:
    """The thread list is paged the same way, until a page that is not `m`."""
    wire = _Endless(["PacketSize=4000", "l" + M68K, "m1"], page="m1")
    ses = g.Session(timeout=0.2)
    ses._sock = wire  # type: ignore[assignment]
    began = time.monotonic()
    with pytest.raises(g.Timeout, match="thread list") as got:
        ses.handshake(0.1)
    assert got.value.phase == "threads" and time.monotonic() - began < 1.0
    assert 3 < len(_packets(wire)) < _Endless.ENDLESS_CHUNKS, "it stopped at the deadline"


def test_a_dial_whose_first_byte_fails_closes_its_socket_and_says_so(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The kernel completed the connection and the `+` could not go out on it."""
    wire = _Wire([], send_error=ConnectionResetError(54, "Connection reset by peer"))
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: wire)
    ses = g.Session(timeout=0.2)
    with pytest.raises(g.DialFailed, match="Connection reset by peer"):
        ses.dial()
    assert wire.closed and ses._sock is None


def test_a_stop_on_another_thread_is_undone_before_the_next_register_or_memory_packet() -> None:
    """The patched stub makes the stopped thread the one `g` and `m` serve, as gdbserver does."""
    ses, wire = _wired(["OK", "00000400", "00000400"])
    ses._note_stop("T05thread:2;0e:0000083b;11:00000542;")
    ses.read(0x4, 4, thread=1)
    ses.read(0x4, 4, thread=1)
    assert _packets(wire) == ["Hg1", "m4,4", "m4,4"]
    for stop in ("T05thread:1;11:00000b90;", "T05watch:2031fc;thread:1;", "T05"):
        ses, wire = _wired(["00000400"])
        ses._note_stop(stop)
        ses.read(0x4, 4, thread=1)
        assert _packets(wire) == ["m4,4"], stop
    ses, wire = _wired(["OK", "00000400"])
    ses._note_stop("T05watch:2031fc;thread:2;")
    ses.read(0x4, 4, thread=1)
    assert _packets(wire) == ["Hg1", "m4,4"], "the thread after a watch field is read too"


def test_a_threads_block_selects_it_once_and_the_first_cpu_is_put_back_after() -> None:
    """`register_block` reads one thread's whole `g` reply with that thread selected."""
    block = "00600080000031bf"
    ses, wire = _wired(["OK", block, block, "OK", "OK", "00000400"])
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    ses.know_endianness({1: "big", 2: "big"})
    assert ses.register_block(2) == block and ses.register_block(2) == block
    ses.make_visible(2)
    ses.read(0x4, 4, thread=1)
    assert _packets(wire) == ["Hg2", "g", "g", "Hc2", "Hg1", "m4,4"]


_THREAD_PACKETS = [
    ("read", lambda s, t: s.read(0x4, 4, thread=t), "m4,4", "00000401"),
    ("write", lambda s, t: s.write(0x4, b"\x01", thread=t), "M4,1:01", "OK"),
    ("reg", lambda s, t: s.reg("d0", thread=t), "p0", "00001111"),
    ("set_reg", lambda s, t: s.set_reg("d0", 1, thread=t), "P0=00000001", "OK"),
    ("registers", lambda s, t: s.registers(thread=t), "g",
     "0000111100002222000033330000444400005555"),
]


@pytest.mark.parametrize(("call", "packet", "reply"), [p[1:] for p in _THREAD_PACKETS],
                         ids=[p[0] for p in _THREAD_PACKETS])
def test_every_register_and_memory_packet_goes_to_the_thread_it_names(
        call: Any, packet: str, reply: str) -> None:
    """The session owns the stub's one selection."""
    ses, wire = _wired(["l" + M68K, "OK", reply, reply, "OK", reply])
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    ses.know_endianness({1: "big", 2: "big"})
    ses._layouts[2] = ses.layout(1)
    call(ses, 2)
    call(ses, 2)
    call(ses, 1)
    assert _packets(wire)[1:] == ["Hg2", packet, packet, "Hg1", packet]


def test_a_stub_without_threads_is_asked_for_thread_one_alone() -> None:
    """A build without the thread patch serves its first cpu, thread 1."""
    ses, wire = _wired(["00000400"])
    assert ses.read(0x4, 4, thread=1) == bytes.fromhex("00000400")
    with pytest.raises(ValueError, match=r"thread 2 is not one this stub serves \(\[1\]\)"):
        ses.read(0x4, 4, thread=2)
    assert _packets(wire) == ["m4,4"]


def test_the_stopped_thread_is_read_off_the_question_and_moves_the_selection_as_a_stop_does(
) -> None:
    """`?` answers the stop reply of the last stop, which selects its thread for `g`."""
    ses, wire = _wired(["T05thread:2;0e:0000083a;0f:00201000;11:00000542;", "OK", "00000400"])
    assert ses.stopped_thread() == 2
    ses.read(0x4, 4, thread=1)
    assert _packets(wire) == ["?", "Hg1", "m4,4"]
    ses, wire = _wired(["T05", "00000400"])
    assert ses.stopped_thread() is None
    ses.read(0x4, 4, thread=1)
    assert _packets(wire) == ["?", "m4,4"]


def test_the_empty_reply_is_its_own_error_and_still_a_session_error() -> None:
    """`Unsupported` lets a caller tell "the stub has no such packet" from a timeout."""
    ses, _wire = _wired([""])
    with pytest.raises(g.Unsupported):
        ses.request("qThreadExtraInfo,1")
    assert issubclass(g.Unsupported, g.SessionError) and ses.broken is None


def test_a_thread_name_that_is_not_hex_is_refused_rather_than_read() -> None:
    """A stub answering `qThreadExtraInfo` with something that is not hex has not named its cpu."""
    def canned(cmd: str, timeout: float | None = None) -> str:
        return {"qfThreadInfo": "m1", "qsThreadInfo": "l"}.get(cmd, "maincpu")

    ses = g.Session()
    ses.request = canned  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="not hex"):
        ses._read_threads()


def _packets(wire: _Wire) -> list[str]:
    return [p.decode()[1:].split("#")[0] for p in wire.sent if p != b"+"]


@pytest.mark.parametrize("addr", [0x200000, 0x20000])
def test_a_write_longer_than_one_packet_goes_out_in_packets_that_fit(addr: int) -> None:
    """An `M` packet carries two hex digits per byte."""
    data = bytes(range(100))
    ses, wire = _wired(["OK"] * 10)
    ses.packet_size = 0x40
    ses.write(addr, data, thread=1)
    sent = _packets(wire)
    assert len(sent) > 1, sent
    assert 0x40 - 1 <= max(len(p) for p in sent) <= 0x40, [len(p) for p in sent]
    got, at = b"", addr
    for p in sent:
        head, payload = p.split(":")
        start, n = (int(x, 16) for x in head[1:].split(","))
        assert start == at and len(payload) == 2 * n
        got, at = got + bytes.fromhex(payload), at + n
    assert got == data and ses.writes == 1
    ses, wire = _wired(["OK"])
    ses.write(addr, data, thread=1)
    assert len(_packets(wire)) == 1


def test_a_packet_too_small_for_one_byte_is_refused_and_writes_nothing() -> None:
    """A size that cannot carry the header and one byte would otherwise send empty packets."""
    ses, wire = _wired(["OK"] * 4)
    ses.packet_size = 8
    with pytest.raises(g.SessionError, match="cannot carry"):
        ses.write(0x200000, b"\x01\x02", thread=1)
    assert wire.sent == [] and ses.writes == 0
    ses.packet_size = None
    ses.write(0x200000, b"", thread=1)
    assert wire.sent == [] and ses.writes == 0, "no bytes: no packet and no write counted"


def test_a_console_command_past_the_packet_size_is_refused_before_a_byte_goes_out() -> None:
    """`qRcmd` carries the command as two hex digits per character."""
    size = 0x40
    limit = (size - len("qRcmd,")) // 2
    ses, wire = _wired([])
    ses.packet_size = size
    with pytest.raises(g.CommandTooLong) as refused:
        ses.monitor("x" * (limit + 1))
    assert wire.sent == [], wire.sent
    assert (refused.value.command_chars, refused.value.limit_chars) == (limit + 1, limit)
    assert isinstance(refused.value, g.SessionError)
    ses, wire = _wired(["4f4b"])
    ses.packet_size = size
    assert ses.monitor("x" * limit) == "OK"
    assert _packets(wire) == ["qRcmd," + ("x" * limit).encode().hex()]
    assert ses.max_payload() == size
    assert len(_packets(wire)[0]) == size
    ses, wire = _wired(["4f4b"])
    ses.packet_size = 0x41
    at = (0x41 - len("qRcmd,")) // 2
    assert len("qRcmd," + ("x" * at).encode().hex()) == 0x41 - 1
    assert ses.monitor("x" * at) == "OK"
    with pytest.raises(g.CommandTooLong):
        ses.monitor("x" * (at + 1))
    ses, wire = _wired([])
    ses.packet_size = 4
    with pytest.raises(g.CommandTooLong) as tiny:
        ses.monitor("x")
    assert tiny.value.limit_chars == 0 and wire.sent == []
    ses, wire = _wired(["4f4b"])
    assert ses.max_payload() is None and ses.monitor("x" * 4 * limit) == "OK"



CONSOLE = Path(__file__).parent / "fixtures" / "console"
ROW_START = re.compile(r"^(?:[ D][ 0-9A-F]{3}[0-9A-F] @ |Device )")


def _zeros_cond(row: str) -> str:
    return row.split(" if ", 1)[1]


def test_unwrap_console_rebuilds_a_row_cut_at_the_space_after_if() -> None:
    """Captured at one short of, at, and one past the console's wrap column."""
    for name, index, zeros in (("row249", 1, 224), ("row250", 2, 225), ("row251", 3, 226)):
        cond = "d0==0x" + "0" * zeros + "1"
        text = (CONSOLE / f"bplist.{name}.txt").read_text()
        assert g.unwrap_console(text, ROW_START) == [
            "Device ':maincpu' breakpoints:", f"    {index} @ 000400 if {cond}"], name
        assert len(f"    {index} @ 000400 if {cond}") == int(name[3:]), "the fixture's own size"


def test_unwrap_console_joins_a_hard_cut_with_nothing_and_a_space_cut_with_a_space() -> None:
    text = (CONSOLE / "bplist.at-limit.txt").read_text()
    pieces = [p for p in text.split("\n") if p]
    assert any(len(p) == g.CONSOLE_WRAP_COLS for p in pieces), "the capture holds hard cuts"
    lines = g.unwrap_console(text, ROW_START)
    assert lines == ["Device ':maincpu' breakpoints:", "    4 @ 000400 if " + "".join(pieces[2:])]
    early = g.unwrap_console((CONSOLE / "bplist.space-early.txt").read_text(), ROW_START)
    assert _zeros_cond(early[1]) == "d0==0x1 || d1==0x" + "0" * 300 + "1"
    late = g.unwrap_console((CONSOLE / "bplist.space-late.txt").read_text(), ROW_START)
    assert _zeros_cond(late[1]) == "d0==0x" + "0" * 220 + "1 || d1==0x1"


def _space_cut(head: str, tail: str) -> str:
    """A line MAME cut at the space after `head`."""
    return head + "\n" + tail


def test_unwrap_console_joins_only_what_the_wrap_could_have_cut() -> None:
    head = "    9 @ 000400 do " + "a" * 226
    cont = "Device online"
    assert g.unwrap_console(_space_cut(head, cont) + "\n\n", ROW_START) == [head + " " + cont], \
        "a continuation that happens to start like a header is still the row's"
    assert g.unwrap_console("    1 @ 000400 if d0==1\n5 things happened\n\n", ROW_START) == [
        "    1 @ 000400 if d0==1", "5 things happened"], "a short line was never cut, so " \
        "what follows it is a line of its own"
    assert g.unwrap_console("A\nb\n\nc\n", ROW_START) == ["A", "b", "c"]
    assert g.unwrap_console("", ROW_START) == []


def test_unwrap_console_breaks_the_one_ambiguous_tie_with_the_callers_starts() -> None:
    """A piece one short of the column is a whole line or one ending in a dropped space."""
    head = "    1 @ 000400 if " + "x" * 231
    assert len(head) == g.CONSOLE_WRAP_COLS - 1
    assert g.unwrap_console(head + "\n    2 @ 000404\n\n", ROW_START) == [head, "    2 @ 000404"]
    assert g.unwrap_console(head + "\nx==1\n\n", ROW_START) == [head + " x==1"]



STOP_PARKED = b"$T050e:00000000;0f:00201000;11:000f2034;#67"
STOP_AT_4A0 = b"$T050e:00200fd8;0f:00200fb6;11:000004a0;#3e"


class _ByteWire:
    """A socket that answers from scripted CHUNKS of bytes; a `TimeoutError` entry reads nothing."""

    def __init__(self, chunks: list[bytes | type[TimeoutError]]) -> None:
        self.chunks = list(chunks)
        self.sent: list[bytes] = []
        self.bounds: list[float | None] = []
        self.sizes: list[int] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def settimeout(self, seconds: float | None) -> None:
        self.bounds.append(seconds)

    def recv(self, n: int) -> bytes:
        self.sizes.append(n)
        if not self.chunks:
            raise TimeoutError
        chunk = self.chunks.pop(0)
        if isinstance(chunk, bytes):
            return chunk
        raise chunk


def _on_bytes(chunks: list[bytes | type[TimeoutError]], timeout: float = 0.2) -> tuple[
        g.Session, _ByteWire]:
    wire = _ByteWire(chunks)
    ses = g.Session(timeout=timeout)
    ses._sock = wire  # type: ignore[assignment]
    return ses, wire


def test_a_reply_is_cut_at_its_own_checksum_however_the_bytes_arrive() -> None:
    ses, wire = _on_bytes([b"+", b"$OK#9a", b"+" + STOP_PARKED, b"$O", b"K#", b"9a",
                           b"$OK#9a" + STOP_AT_4A0])
    assert ses._receive() == "OK", "the ack alone, then the packet"
    assert ses._receive() == STOP_PARKED[1:-3].decode(), "the ack glued to the packet"
    assert ses._receive() == "OK", "a packet in three reads, the last one inside its checksum"
    assert ses._receive() == "OK" and ses._buf == STOP_AT_4A0, "two packets in one read"
    assert ses._receive() == STOP_AT_4A0[1:-3].decode()
    assert wire.sent == [b"+"] * 5, "one ack per packet taken"
    ses, _ = _on_bytes([b"$X09#00"])
    assert ses._receive() == "X09", "only the frame's own `$` is taken off the front"
    ses, _ = _on_bytes([b"$\xff#ff"])
    assert ses._receive() == "�", "bytes that are not UTF-8 are replaced, never raised on"


def test_a_read_is_bounded_by_the_time_it_was_given_and_by_nothing_else() -> None:
    ses, wire = _on_bytes([TimeoutError, b"$OK#9a"], timeout=30.0)
    assert ses._receive(0.5) == "OK", "a read that found nothing is asked again inside the bound"
    assert all(b is not None and 0.0 <= b <= 0.5 for b in wire.bounds) and len(wire.bounds) == 2
    assert wire.sizes == [65536, 65536]
    ses, wire = _on_bytes([], timeout=30.0)
    began = time.monotonic()
    with pytest.raises(g.Timeout, match="no answer within 0.05 s"):
        ses._receive(0.05)
    assert time.monotonic() - began < 5.0, "the bound is the call's, not the session's"
    ses, wire = _on_bytes([], timeout=0.05)
    with pytest.raises(g.Timeout, match="no answer within 0.05 s"):
        ses._receive()
    ses, _ = _on_bytes([b""])
    with pytest.raises(g.SessionError, match="the stub closed the connection"):
        ses._receive()


def test_a_stop_reply_is_an_answer_when_the_machine_was_not_running() -> None:
    """`?` on a parked machine is answered with a stop reply, and that IS the answer."""
    ses, _ = _on_bytes([b"+" + STOP_PARKED])
    assert ses.request("?") == STOP_PARKED[1:-3].decode()
    assert (ses.running, ses.stop_count, ses.last_stop_packet) == (False, 0, "")


def test_a_read_that_starts_with_an_e_is_data_and_three_characters_of_it_are_a_refusal() -> None:
    ses, _ = _on_bytes([b"$e0ff1234#00", b"$E0FF#00", b"$E01#a6"])
    assert ses.request("m0,4") == "e0ff1234"
    assert ses.request("m0,2") == "E0FF", "four characters that start with E are two bytes"
    with pytest.raises(g.SessionError, match="the stub refused `P0=00`: E01"):
        ses.request("P0=00")


def _bounds_seen(ses: g.Session, packets: list[str]) -> list[float | None]:
    seen: list[float | None] = []

    def receive(timeout: float | None = None) -> str:
        seen.append(timeout)
        return packets.pop(0)

    ses._receive = receive  # type: ignore[method-assign]
    return seen


def test_every_wait_of_the_session_hands_its_own_bound_to_the_read() -> None:
    ses, _ = _on_bytes([])
    seen = _bounds_seen(ses, ["T05", "OK"])
    ses.running = True
    assert ses.request("Z0,4a0,2", timeout=0.3) == "OK" and seen == [0.3, 0.3]
    ses.running = True
    seen = _bounds_seen(ses, ["T05", "T05", "T05watch:200fd4;", "T05"])
    assert ses.poll_stop() is True and seen == [0.0], "with no bound it only looks"
    ses.running = True
    assert ses.poll_stop(0.2) is True and seen == [0.0, 0.2]
    ses.running = True
    assert ses.interrupt(timeout=0.4) == "T05watch:200fd4;" and seen[-1] == 0.4
    assert ses.last_stop_packet == "T05watch:200fd4;" and ses.running is False
    ses.running = True
    ses.interrupt()
    assert seen[-1] == 5.0, "the bound `stop` gets, which passes none"


def test_a_session_with_no_socket_says_so_before_it_interrupts_anything() -> None:
    for ask in (g.Session().halt, g.Session().interrupt):
        with pytest.raises(g.SessionError, match="the session is not connected"):
            ask()


def test_a_wrapped_piece_one_character_short_of_two_continues_by_what_it_carried() -> None:
    """A piece two short of the column carried ONE character past the dropped space."""
    starts = re.compile("ab")
    assert g._continues("x" * (g.CONSOLE_WRAP_COLS - 2), "ab cd", starts) is True
    assert g._continues("x" * (g.CONSOLE_WRAP_COLS - 2), " b cd", starts) is False




def test_a_stop_shape_never_sent_is_refused_in_lower_case_hex_and_quoted_short() -> None:
    with pytest.raises(g.SessionError, match="never sends"):
        g._is_stop_reply("S0b")
    long = "S05" + "0123456789" * 4
    with pytest.raises(g.SessionError) as raised:
        g._is_stop_reply(long)
    assert repr(long[:32]) in str(raised.value) and repr(long[:33]) not in str(raised.value)


def test_a_run_length_refusal_names_the_first_marker_and_the_packets_own_tail() -> None:
    body = "ab*cd*" + "0123456789" * 4
    with pytest.raises(g.SessionError) as raised:
        g._refuse_run_length(body)
    said = str(raised.value)
    assert "`*` at position 2 of a 46-character packet" in said
    assert f"(ends {body[-32:]!r})" in said


def test_the_packet_size_is_the_feature_of_that_name_and_no_other() -> None:
    assert g.packet_size("swbreak=1;PacketSize=400") == 0x400
    assert g.packet_size("swbreak=1;hwbreak=2") is None


def test_unwrap_console_opens_with_no_piece_and_a_blank_line_leaves_none() -> None:
    """A first line, or one after a blank, continues nothing however long and spaceless it is."""
    solid = "x" * (g.CONSOLE_WRAP_COLS - 1)
    starts = re.compile("never")
    assert g.unwrap_console(solid, starts) == [solid]
    assert g.unwrap_console(f"head\n\n{solid}", starts) == ["head", solid]


def test_a_step_is_the_stubs_s_and_every_stop_is_counted() -> None:
    ses, wire = _wired(["T05", "T05"])
    ses.step()
    ses.step()
    assert _packets(wire) == ["s", "s"] and ses.stop_count == 2


def test_every_write_is_counted_on_top_of_the_ones_before_it() -> None:
    ses, _wire = _wired(["OK", "OK"])
    ses.write(0x200000, b"\x01", thread=1)
    ses.write(0x200000, b"\x02", thread=1)
    assert ses.writes == 2
    ses.monitor = lambda command, timeout=10.0: ""  # type: ignore[method-assign]
    ses.step = lambda: "T05"  # type: ignore[method-assign]
    ses.current_pc = lambda: 0  # type: ignore[method-assign]
    ses.reset()
    assert ses.writes == 3


def _console(text: str) -> str:
    return text.encode().hex()


@pytest.mark.parametrize(("answer", "seconds"), [
    ("1.000003437\n", 1.000003437), ("12\n", 12.0), ("-0.5", -0.5),
    ("Unknown command: time\n", None)])
def test_the_emulated_clock_is_the_consoles_time_or_none(answer: str,
                                                         seconds: float | None) -> None:
    ses, wire = _wired([_console(answer)])
    assert ses.emulated_seconds() == seconds
    assert _packets(wire) == ["qRcmd," + _console("time")]


def test_the_console_answers_text_with_bytes_that_are_not_utf8_replaced() -> None:
    ses, _wire = _wired(["ff0a", "OK"])
    assert ses.monitor("print 1") == "�\n"
    assert ses.monitor("print 1") == "OK", "an answer that is not hex is handed back as it came"


def test_the_console_and_a_resume_wait_their_own_bound_and_not_the_sessions() -> None:
    ses, _ = _on_bytes([], timeout=7.0)
    ses.running = False
    seen = _bounds_seen(ses, ["0a", "0a", "T05", "T05"])
    ses.monitor("time")
    ses.monitor("time", timeout=0.3)
    assert seen == [10.0, 0.3]
    ses.resume()
    ses.resume(0.4)
    assert seen[2:] == [30.0, 0.4]


def test_self_check_compares_sixteen_bytes_unless_told_and_says_what_differed() -> None:
    image = bytes(range(64))
    ses = reading_session(image, 0)
    asked: list[int] = []
    real = ses.read

    def read(addr: int, n: int, *, thread: int) -> bytes:
        asked.append(n)
        return real(addr, n, thread=thread)

    ses.read = read  # type: ignore[method-assign]
    ses.self_check(image, 0, thread=1)
    assert asked == [16]
    with pytest.raises(g.SessionError) as raised:
        ses.self_check(bytes(64), 0x10, n=2, thread=1)
    assert "at 0x10 it returns 1011 and the ROM on disk holds 0000" in str(raised.value)


def _cpu_on(xml: str, arch: str, packets: list[str]) -> tuple[g.Session, _Wire]:
    ses, wire = _wired(packets)
    ses._layouts[1] = dataclasses.replace(_session_with(xml).layout(1), arch=arch,
                                          mame_order=g._BYTE_ORDER[arch])
    return ses, wire


def test_a_forced_register_goes_out_at_its_width_in_the_targets_order_and_is_counted() -> None:
    ses, wire = _cpu_on(M68K, "m68k", ["OK", "OK"])
    ses.set_reg("d0", 0x1234, thread=1)
    ses.set_reg("A7", 0x200FD6, thread=1)
    assert _packets(wire) == ["P0=00001234", "P2=00200fd6"] and ses.writes == 2
    ses, wire = _cpu_on(I386, "i386", ["OK"])
    ses.set_reg("eax", 0x1234, thread=1)
    assert _packets(wire) == ["P0=34120000"], "an x86 register travels little-endian"


def test_a_value_too_wide_for_its_register_is_refused_before_anything_is_sent() -> None:
    ses, wire = _cpu_on(M68K, "m68k", [])
    with pytest.raises(g.SessionError) as raised:
        ses.set_reg("d0", 0x1FFFFFFFF, thread=1)
    assert str(raised.value) == "D0 is 32 bits on this cpu and 0x1ffffffff does not fit it"
    assert wire.sent == [] and ses.writes == 0




def _late(reply: str) -> list[bytes | type[TimeoutError]]:
    """The wire of a stub that answers `reply` only after the read's deadline has passed."""
    return [TimeoutError, f"${reply}#{g._checksum(reply)}".encode()]


def _two_cpus_on(wire: _ByteWire) -> g.Session:
    """The captured two-cpu description, its `request` the REAL one again, over `wire`."""
    ses = _two_cpus()
    del ses.request
    ses._sock = wire  # type: ignore[assignment]
    ses.timeout = 0.05
    return ses


def test_each_threads_registers_are_cut_by_its_own_description() -> None:
    """KNOWN ANSWER, m68k-dual on the patched stub."""
    xml2 = (TWO_CPUS / "target.thread2.xml").read_text()
    g1, g2 = ((TWO_CPUS / f"g.thread{t}.reply").read_text() for t in (1, 2))
    ses, wire = _wired(["l" + (TWO_CPUS / "target.xml").read_text(), g1,
                        "OK", "l" + xml2, g2, g2])
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    ses.know_endianness({1: "big", 2: "big"})
    assert ses.registers(thread=1)["PC"] == 0xB90
    assert ses.registers(thread=2)["PC"] == 0x542
    assert ses.registers(thread=2)["PC"] == 0x542
    xfer = "qXfer:features:read:target.xml:0,400"
    assert _packets(wire) == [xfer, "g", "Hg2", xfer, "g", "g"], "each description once"
    assert ses.layout(2) is not ses.layout(1), "thread 2 appends :maincpu, thread 1 :subcpu"


def test_two_cpus_of_different_architectures_are_each_decoded_as_their_own() -> None:
    """A board whose second cpu is another architecture."""
    ses, wire = _wired(["l" + M68K, "OK", "l" + I386, "34120000" + "fc0f2000" + "00020000"
                        + "08000000"])
    ses.threads = {1: ":maincpu", 2: ":audiocpu"}
    ses.know_endianness({1: "big", 2: "little"})
    assert ses.layout(1).byte_order == "big" and ses.layout(2).byte_order == "little"
    assert ses.registers(thread=2) == {"EAX": 0x1234, "ESP": 0x200FFC, "EIP": 0x200, "CS": 8}
    assert ses.layout(2).pc_name == "EIP" and ses.layout(1).pc_name == "PC"


def test_a_request_that_ran_out_latches_the_session_and_its_late_answer_is_never_paired() -> None:
    """Nothing in the protocol numbers a reply."""
    by_p = json.loads((TWO_CPUS / "p.json").read_text())
    wire = _ByteWire(_late(by_p["pc"]))
    ses = _two_cpus_on(wire)
    regs = ses.layout(1).regs
    pc, d0 = regs["PC"].number, regs["D0"].number
    with pytest.raises(g.Timeout, match=rf"`p{pc:x}` got no answer within 0.0 s"):
        ses.request(f"p{pc:x}", timeout=0.0)
    assert ses.broken is not None and "paired" in ses.broken, ses.broken
    sent = list(wire.sent)
    with pytest.raises(g.SessionError, match="asked nothing more") as refused:
        ses.request(f"p{d0:x}")
    assert type(refused.value) is g.SessionError, "a refusal, not a second wait that ran out"
    assert wire.sent == sent, "the refused request put nothing on the wire"
    assert by_p["pc"] != by_p["d0"], "the two captured answers differ, so a pairing would show"


def test_a_console_command_that_ran_out_is_named_by_its_words_not_its_hex() -> None:
    ses = _two_cpus_on(_ByteWire([TimeoutError]))
    with pytest.raises(g.Timeout, match=r"`over` got no answer"):
        ses.monitor("over", timeout=0.0)
    assert ses.broken is not None and "`over`" in ses.broken and "6f766572" not in ses.broken


@pytest.mark.parametrize("wait", ["resume", "step", "poll"])
def test_a_wait_for_a_stop_that_ran_out_keeps_its_own_handling_and_latches_nothing(
    wait: str,
) -> None:
    """A stop packet says what it is, so a stop wait that ran out is not a reply left owed."""
    ses = _two_cpus_on(_ByteWire([]))
    if wait == "poll":
        ses.go()
        assert ses.poll_stop(0.0) is False
    else:
        with pytest.raises(g.Timeout):
            ses.resume(timeout=0.0) if wait == "resume" else ses.step()
    assert ses.broken is None and ses.running is True


def test_a_session_broken_by_anything_sends_no_further_request() -> None:
    """The guard reads the latch, not the words of one cause."""
    ses, wire = _wired(["OK"])
    ses.broken = "the stub sent 'OK' while the machine ran, which is not a stop reply"
    with pytest.raises(g.SessionError, match="asked nothing more: the stub sent 'OK'"):
        ses.request("g")
    assert wire.sent == [], "nothing went out"


@pytest.mark.parametrize("packet, label", [("qRcmd,6f766572", "over"), ("qRcmd,", ""),
                                           ("qRcmd,zz", "qRcmd,zz"), ("p11", "p11")])
def test_a_packet_is_labelled_by_its_console_words_else_as_sent(packet: str, label: str) -> None:
    assert g._label(packet) == label


def test_every_capture_is_taken_through_the_screen_alone_unless_a_view_is_named() -> None:
    """`-snapview` always reaches the command line."""
    from scry_mame.launch import build_command

    plain = build_command("/bin/mame", "gridlee", "/roms", 23946, [], "/scratch/mame-mcp-t")
    named = build_command("/bin/mame", "gridlee", "/roms", 23946, [], "/scratch/mame-mcp-t",
                          view="Shifter-R")
    assert plain[plain.index("-snapview") + 1] == "native"
    assert named[named.index("-snapview") + 1] == "Shifter-R"


def _packet(reply: str) -> bytes:
    return f"${reply}#{g._checksum(reply)}".encode()


def test_an_owed_request_that_ran_out_latches_nothing_and_the_next_one_collects_its_answer(
) -> None:
    """A request that may run out without breaking the session (the presence's repaint)."""
    by_p = json.loads((TWO_CPUS / "p.json").read_text())
    wire = _ByteWire([TimeoutError, _packet("300a"), _packet(by_p["d0"])])
    ses = _two_cpus_on(wire)
    d0 = ses.layout(1).regs["D0"].number
    with pytest.raises(g.Timeout, match="no answer within 0.0 s"):
        ses.monitor_owed("print 0", timeout=0.0)
    assert ses.broken is None, ses.broken
    assert ses.request(f"p{d0:x}") == by_p["d0"]


def test_an_owed_answer_is_collected_before_a_step_and_a_stop_ahead_of_it_is_noted() -> None:
    """Whatever goes out next collects what the owed request was still owed."""
    wire = _ByteWire([TimeoutError, _packet("300a"), _packet("T05thread:01;")])
    ses = _two_cpus_on(wire)
    with pytest.raises(g.Timeout):
        ses.monitor_owed("print 0", timeout=0.0)
    assert ses.step().startswith("T05"), ses.broken
    assert ses.broken is None, ses.broken
    running = _two_cpus_on(_ByteWire([TimeoutError, _packet("T05thread:01;"), _packet("300a")]))
    with pytest.raises(g.Timeout):
        running.monitor_owed("print 0", timeout=0.0)
    running.running = True
    assert running.poll_stop(0.0) is True and running.broken is None, running.broken


def test_an_owed_answer_that_never_comes_latches_the_request_that_waited_for_it() -> None:
    ses = _two_cpus_on(_ByteWire([TimeoutError]))
    with pytest.raises(g.Timeout):
        ses.monitor_owed("print 0", timeout=0.0)
    assert ses.broken is None
    with pytest.raises(g.Timeout, match="`print 0` was still owed"):
        ses.request("g")
    assert "owed" in str(ses.broken), ses.broken


def test_a_second_owed_request_while_one_is_owed_is_not_sent_and_latches_nothing() -> None:
    """Two repaints in a row with the console silent."""
    ses = _two_cpus_on(_ByteWire([TimeoutError, TimeoutError]))
    ses.timeout = 0.05
    with pytest.raises(g.Timeout):
        ses.monitor_owed("print 0", timeout=0.0)
    with pytest.raises(g.Timeout, match="still owed its answer"):
        ses.monitor_owed("print 0", timeout=0.0)
    assert ses.broken is None, ses.broken
