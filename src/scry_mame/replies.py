"""THE REPLY MODELS, one per tool: the fields each tool's reply names beside the envelope
every reply carries, published as its `outputSchema` (each field its value or `unavailable`,
the always-present ones required) and held to every reply the battery builds
(`scry_core.reply_schema`). Named from the replies the battery and the live runs built, so a
branch none of them reached is unnamed until one does: a field a reply grows is named here in
the same change. The file tools' models are the core's (`scry_core.media_replies`)."""

from __future__ import annotations

from typing import Annotated, Any, Required

from scry_core import media_replies, tool_replies
from scry_core import promote as core_promote
from scry_core import sequence_account as account
from scry_core.instruction import StopInstruction
from scry_core.reply_contract import OmitEmpty, When
from scry_core.reply_schema import RunEnvelope


class MameEnvelope(RunEnvelope, total=False):
    """What this server's shared paths add to any reply: the stop a call met or
    applied, the refusal's context."""

    broken: str
    cause: str
    #: The machine's cpus by tag: what a refusal of a cpu offers, and `status`'s list. A row
    #: per cpu is `cpus`, `cpu_info`'s and `machine_map`'s.
    cpu_tags: list[str]


class MameConsoleAccount(MameEnvelope, total=False):
    """The account of a call the console evaluated (a Lua line, a read, a recording): what
    ran, how the reader fared, and the stop the machine is at."""

    console_reruns: int
    cpu: str
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: int
    pc: str
    regs: dict[str, Any]
    resent: Annotated[int, OmitEmpty]
    stop_seq: int
    thread_errors: int


#: What `record` and `audio_record` share: the frame window a recording ran over.
class MameRecordingRun(MameConsoleAccount, total=False):
    emulated_after_s: float | dict[str, Any]
    emulated_before_s: float | dict[str, Any]
    ended: Annotated[bool, When("once answered")]
    frame_after: int
    frame_before: int
    frame_begin: int | dict[str, Any]
    frame_begin_planned: int
    frame_end: int
    frame_end_planned: int
    frames: int
    instructions_completed: int
    lines_ahead: int
    mode: str
    path: Annotated[str, When("once answered")]
    pending: Annotated[bool, When("without an answer")]
    polls: int
    reader_steps: Annotated[int, OmitEmpty]
    recording_after: bool | dict[str, Any]
    regpoint_hit: dict[str, Any]


class AudioRecordReply(MameRecordingRun, total=False):
    began: Annotated[bool, When("once answered")]
    bytes: Annotated[int | dict[str, Any], When("once answered")]
    channels: Annotated[int | dict[str, Any], When("once answered")]
    cycles: int
    drain_steps: Annotated[int, OmitEmpty]
    emulated_s: Annotated[float | dict[str, Any], When("once answered")]
    sample_max: Annotated[int | dict[str, Any], When("once answered")]
    sample_min: Annotated[int | dict[str, Any], When("once answered")]
    sample_rate_hz: Annotated[int | dict[str, Any], When("once answered")]
    samples: Annotated[int | dict[str, Any], When("once answered")]
    tagged_lines: list[Any]
    verdict: Annotated[str, When("once answered")]
    watch_hit: dict[str, Any]
    watches: list[Any]


class BreakpointAtReply(MameEnvelope, total=False):
    addr: Annotated[str, When("once `ref` resolves")]
    already_stored: Annotated[bool, OmitEmpty]
    armed: Required[bool]
    by: str
    command_chars: int
    condition: str
    condition_typed: str
    cpu: str
    entry: Annotated[str, When("once armed")]
    limit_chars: int
    ref: str
    role: str
    state: Required[str]
    stored: Required[bool]
    temp: Annotated[str, When("a control")]
    visible_cpu: str
    while_running: bool


class CapturesReply(MameEnvelope, media_replies.CapturesFields, total=False):
    pass


class CloseReply(MameEnvelope, total=False):
    draft: Annotated[list[str], OmitEmpty]
    average_speed: Annotated[dict[str, Any], When("while a `resume` run was open")]
    cfg: Required[dict[str, Any]]
    closed: Required[bool]
    console_drained: int
    console_pending_before: int
    ended_by: Required[str]
    errorlog_tail: Annotated[str, When("not a clean")]
    cfg_written: Required[bool | dict[str, Any]]
    stdout_tail: Annotated[str, When("not a clean")]


class CommentListReply(MameEnvelope, total=False):
    comments: Required[list[Any]]
    comments_total: Required[int]
    cpu: str | dict[str, Any]
    declarations: Required[dict[str, Any]]
    truncated: Required[bool]


class CpuInfoReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    cpus: Required[list[Any]]


class DebugReply(MameEnvelope, total=False):
    clipped: Required[bool]
    command: str
    command_chars: Annotated[int, When("on refusal")]
    ignored: Annotated[list[Any] | dict[str, Any], When("a line that sets cpus")]
    limit_chars: Annotated[int, When("on refusal")]
    mutates: Required[bool]
    not_run: Annotated[list[Any], When("on refusal")]
    output: Required[str]
    output_chars: int
    output_path: str
    refused: Annotated[list[Any], When("on refusal")]
    refused_total: Annotated[int, When("on refusal")]
    visible_cpu: Annotated[str | dict[str, Any], When("a line that sets cpus")]


class DisassembleReply(MameEnvelope, total=False):
    addr: Required[str]
    cpu: str | dict[str, Any]
    flow: Required[list[Any]]
    flow_source: Required[str]
    length: int
    lines: Required[list[Any]]
    resolved: Annotated[list[Any], When("relocated board")]


class DriveReply(MameEnvelope, total=False):
    act: dict[str, Any]
    looked: Required[dict[str, Any]]
    operations: list[Any]
    verify: Required[dict[str, Any]]


class FindReply(MameEnvelope, total=False):
    addr: Required[str]
    cpu: str | dict[str, Any]
    hits: Required[list[Any]]
    hits_total: Required[int]
    length: int
    span: Required[dict[str, Any]]
    symbol_class: str
    truncated: Required[bool]


class FocusReply(MameEnvelope, total=False):
    cause: str
    cpu: str
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: Annotated[int | dict[str, Any], When("stub")]
    ignored: Annotated[list[Any], When("console")]
    machine_ran: Required[bool]
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    unchanged: Annotated[list[Any], When("stub")]
    unread: Annotated[list[Any], When("stub")]
    via: Required[str]
    was: Required[str | dict[str, Any]]
    watch_hit: dict[str, Any]
    watches: list[Any]


class GfxBlitSourceReply(MameConsoleAccount, total=False):
    asset: Required[str]
    blit_pc: Required[str]
    blit_symbol: str
    blits_in_frame: int
    box: Required[list[Any]]
    call: str
    callback_errors: dict[str, Any]
    data: Annotated[dict[str, Any], When("with `margin` above 0")]
    destination: dict[str, Any]
    draw_command: str
    entries: int
    evaluated_by: str
    format: Required[str]
    frame_blit: Required[int]
    image: Required[dict[str, Any]]
    index: int
    indexes: list[Any]
    lines_ahead: int
    margin: int
    n: int
    not_proved: Required[list[Any]]
    palette: Required[str]
    palettes: list[Any]
    pc_before: str
    pen_base: int
    reader_steps: Annotated[int, OmitEmpty]
    reads_source: Required[bool]
    rect: Required[dict[str, Any]]
    source_tile: int
    tag: str
    tile_height: int
    tile_width: int
    tiles_available: int
    watches: list[Any]
    wrap: Required[bool]


class GfxBlitsReply(MameConsoleAccount, total=False):
    area: list[Any]
    blits: Annotated[list[Any], When("with `area` or `detail`")]
    blits_in_frame: Required[int]
    by_plane: Required[list[Any]]
    call: str
    callback_errors: dict[str, Any]
    colors_repeat: bool
    commands: list[Any]
    covering: Annotated[int, When("with `area`")]
    declare: str
    draw_command: str
    evaluated_by: str
    frame_blit: Required[int]
    frame_complete: bool
    frame_screen: int
    frames_with_blits: dict[str, Any]
    height: int
    image: Required[dict[str, Any]]
    legend: Required[list[Any]]
    lines_ahead: int
    listed: Annotated[dict[str, Any], When("with `area` or `detail`")]
    listed_of: int
    next_first: Annotated[int, When("more blits remain")]
    not_proved: Required[list[Any]]
    overflow_rows: int
    pc_before: str
    reader_steps: Annotated[int, OmitEmpty]
    rows_cut: Required[bool]
    rows_kept: int
    rows_path: str
    screen: str
    tally_id: str
    topmost: Annotated[dict[str, Any], When("with `area`")]
    watches: list[Any]
    width: int


class GfxDraftReply(MameEnvelope, total=False):
    asset_names: Required[list[Any]]
    chose: Annotated[dict[str, Any], When("with `choose`")]
    command_fields: Required[dict[str, Any]]
    confirm: Required[str]
    draft: str
    evidence: Required[dict[str, Any]]
    formats: Required[dict[str, Any]]
    manifest: Required[dict[str, Any]]
    marker: str
    not_proved: Required[list[Any]]
    not_proved_more: int
    report: Required[dict[str, Any]]


class GfxFilmReply(MameConsoleAccount, total=False):
    animation: dict[str, Any]
    armed_now: Annotated[bool, When("arm")]
    baseline_value: str | dict[str, Any]
    call: str
    callback_errors: dict[str, Any]
    cells: Annotated[list[Any], When("once frames are kept")]
    cleared: bool
    cost: dict[str, Any]
    cpus_with_io: list[Any]
    dropped_frames: list[Any] | dict[str, Any]
    dropped_total: int
    evaluated_by: str
    files_kept: str
    film: Annotated[dict[str, Any], When("arm", "read")]
    frame_as_of: int
    frame_baseline: int | dict[str, Any]
    height: int
    image: Annotated[dict[str, Any], When("once frames are kept")]
    install_call: str
    install_lines_ahead: int
    install_resent: Annotated[int, OmitEmpty]
    installed: bool
    judged: Annotated[int, When("once the film has dumped")]
    judged_frames: list[Any] | dict[str, Any]
    kept: Annotated[int, When("once the film has dumped")]
    lines_ahead: int
    listed: dict[str, Any]
    listing_path: str
    lost: dict[str, Any]
    met: Annotated[int, When("once the film has dumped")]
    next_first: Annotated[int, When("more kept frames remain")]
    nothing_kept: str
    pc_before: str
    pending: bool
    pending_picture: bool
    reader_steps: Annotated[int, OmitEmpty]
    refused: int
    refused_frames: list[Any]
    removal: str
    state: Annotated[str, When("read")]
    superseded: bool
    tally_id: str
    trigger_maps_to: str
    watches: list[Any]
    why: str
    width: int


class GfxLoadReply(MameEnvelope, total=False):
    assets: Required[dict[str, Any]]
    commands: Required[dict[str, Any]]
    draft: Required[bool]
    formats: Required[dict[str, Any]]
    loaded: Required[bool]
    palette_ports: Required[dict[str, Any]]
    path: str
    replaced_path: Required[str | dict[str, Any]]
    sha256: str
    status_counts: Required[dict[str, Any]]
    still_loaded: str | dict[str, Any]
    system: str
    systems: list[Any]


class GfxLocateReply(MameConsoleAccount, total=False):
    addr: str
    addr_cpu: str
    ambiguous: Required[bool]
    ambiguous_windows: int
    bytewidth: int
    call: str
    candidates: Required[list[Any]]
    endianness: str
    evaluated_by: str
    evidence: Required[dict[str, Any]]
    flips: list[Any]
    frame_screen: int
    height: int
    kind: str
    lines_ahead: int
    matched: Required[bool]
    matches: Required[list[Any]]
    matches_total: Required[int]
    nearest: Annotated[dict[str, Any], When("nothing matched")]
    offset: int
    palette: str
    patch: list[Any]
    pc_before: str
    pen_map: Required[dict[str, Any]]
    pending: bool
    reader_steps: Annotated[int, OmitEmpty]
    screen: str
    screen_type: str
    screens: list[Any]
    seen_bytes: int
    size: int
    tag: str
    tiles_available: int
    transparent: int | dict[str, Any]
    watches: list[Any]
    width: int


class GfxSweepReply(MameConsoleAccount, total=False):
    addr: str
    addr_cpu: str
    bytewidth: int
    call: str
    candidates: Required[int | list[Any]]
    cell_scale: Required[int]
    count: int
    endianness: str
    entries: int
    evaluated_by: str
    image: Required[dict[str, Any]]
    kind: str
    lines_ahead: int
    next: Required[str]
    offset: int
    palette: str
    palettes: list[Any]
    pc_before: str
    pen_base: int
    pending: bool
    reader_steps: Annotated[int, OmitEmpty]
    real_colors: bool
    seen_bytes: int
    size: int
    sweep: Required[int]
    tag: str


class GfxViewReply(MameConsoleAccount, total=False):
    addr: str
    addr_cpu: str
    bytewidth: int
    call: str
    columns: int
    count: int
    endianness: str
    entries: int
    evaluated_by: str
    first: int
    formats: list[Any]
    image: Required[dict[str, Any]]
    kind: str
    layout: dict[str, Any]
    lines_ahead: int
    offset: int
    palette: str
    palettes: list[Any]
    pc_before: str
    pen_base: int
    pending: bool
    reader_steps: Annotated[int, OmitEmpty]
    real_colors: Required[bool]
    seen_bytes: int
    size: int
    tag: str
    tags: dict[str, Any]
    tiles_available: Required[int]


class HistoryReply(MameEnvelope, total=False):
    asked: Required[int]
    cpu: str | dict[str, Any]
    lines: Required[list[Any]]


class InputReply(MameConsoleAccount, total=False):
    emulated_after_s: float | dict[str, Any]
    emulated_before_s: float | dict[str, Any]
    active: Annotated[bool | dict[str, Any], When("once answered")]
    cycles: int
    defvalue: str
    drain_steps: Annotated[int, OmitEmpty]
    field: str
    frame_after: Annotated[int, When("once answered")]
    frame_before: Annotated[int, When("once answered")]
    frame_release_planned: int
    frame_released: Annotated[int, When("once answered")]
    frame_set: Annotated[int, When("once answered")]
    frames: int
    instructions_completed: int
    lines_ahead: int
    mask: Annotated[str, When("once answered")]
    mode: str
    name: Annotated[str, When("once answered")]
    pending: Annotated[bool, When("without an answer")]
    player: int
    polls: int
    port: str
    port_before: Annotated[str, When("once answered")]
    port_held: str | dict[str, Any]
    reader_steps: Annotated[int, OmitEmpty]
    regpoint_hit: dict[str, Any]
    released: Annotated[bool, When("once answered")]
    route: str
    seen_bytes: int
    tagged_lines: list[Any]
    value: str
    verdict: Annotated[str, When("once answered")]
    watch_hit: dict[str, Any]
    watches: list[Any]


class LogReply(MameEnvelope, total=False):
    channel: str
    counts: Annotated[dict[str, Any], When("on channel `all`")]
    labels: dict[str, Any]
    lines: Required[list[Any]]
    lines_total: Required[int]
    pattern: str
    truncated: Required[bool]


class LogWaitReply(MameEnvelope, tool_replies.LogWaitFields, total=False):
    pass


class LuaReply(MameConsoleAccount, total=False):
    call: str
    # Every Lua run counts its reruns. A TypedDict cannot make a key required that its base
    # leaves optional, and the base serves tools that do not count them.
    console_reruns: Required[int]  # type: ignore[misc]
    clipped: Required[bool]
    evaluated_by: Required[str]
    lines_ahead: Required[int]
    output: Required[str]
    output_chars: int
    output_path: Annotated[str, When("past 4000 characters")]
    pc_before: Required[str]
    pending: bool
    reader_steps: Annotated[int, OmitEmpty]
    regpoint_hit: dict[str, Any]
    script_chars: int
    seen_bytes: int
    watch_hit: dict[str, Any]
    watches: list[Any]


class MachineMapReply(MameEnvelope, total=False):
    address_map: Annotated[list[Any], When("no source backs")]
    counts: Annotated[dict[str, Any], When("no source backs")]
    cpu: str | dict[str, Any]
    cpus: Annotated[list[Any], When("no source backs")]
    frame_symbol: Annotated[str | dict[str, Any], When("no source backs")]
    regions: Annotated[list[Any], When("no source backs")]
    rom_files: Annotated[list[Any], When("no source backs")]
    screens: Annotated[list[Any], When("no source backs")]
    shares: Annotated[list[Any], When("no source backs")]
    sources: Annotated[dict[str, Any], When("no source backs")]
    spaces: Annotated[list[Any], When("no source backs")]
    symbol_coverage: Annotated[list[Any], When("no source backs")]
    truncated: Annotated[bool, When("no source backs")]


class MapFindReply(MameConsoleAccount, total=False):
    call: str
    controls: Annotated[list[Any], When("when matched")]
    evaluated_by: str
    kind: Required[str]
    layer: Annotated[str, When("when matched")]
    lines_ahead: int
    matched: Required[bool]
    pc_before: str
    reader_steps: Annotated[int, OmitEmpty]
    screen: Annotated[str, When("when matched")]
    screens_mapped: Annotated[int, When("when not")]
    screens_tried: Annotated[int, When("if the view fits")]
    screens_unjudged: Annotated[int, When("if the view fits")]
    size: Required[list[Any]]
    view_fits: Annotated[bool, When("else")]


class MemdumpReply(MameEnvelope, total=False):
    addr: Required[str]
    bytes: Required[int]
    cpu: str | dict[str, Any]
    length: int
    path: Required[str]


class PaletteReply(MameConsoleAccount, total=False):
    alpha: Annotated[list[Any], When("not fully opaque")]
    call: str
    colors: Required[list[Any]]
    count: int
    entries: Required[int]
    evaluated_by: str
    first: int
    highlights: bool
    image: Required[dict[str, Any]]
    indirect_entries: Required[int]
    lines_ahead: int
    palette: str
    palettes: list[Any]
    pc_before: str
    reader_steps: Annotated[int, OmitEmpty]
    shadows: bool
    truncated: Required[bool]


class PaletteLogReply(MameEnvelope, total=False):
    across: list[Any]
    armed_now: Annotated[bool, When("unless `clear`")]
    call: str
    callback_errors: dict[str, Any]
    cleared: bool
    component_bits: int
    cpu: str
    cpus_with_io: list[Any]
    data_port: str
    desyncs: Annotated[int, When("once the log has dumped")]
    frame_as_of: int
    index_port: str
    index_writes: int
    install_resent: Annotated[int, OmitEmpty]
    installed: Annotated[bool, When("unless `clear`")]
    lines_ahead: int
    not_proved: list[Any]
    order: str
    overflow_rows: int
    palette: str
    palette_port: str
    palette_ports: list[Any]
    partial_writes: int
    pen_range: list[Any]
    pen_state: dict[str, Any]
    pending: bool
    pens_written: list[Any]
    protocol: Required[str]
    removal: str
    rows: list[Any]
    rows_cut: bool
    rows_kept: int
    rows_max: int
    rows_path: Annotated[str, When("once the log has dumped")]
    sees_reset_and_load: bool
    setters: list[Any]
    setters_path: str | dict[str, Any]
    setters_total: int
    space: str
    state: Annotated[str, When("once armed")]
    superseded: bool
    synced_at_start: bool
    tally_id: str
    unsynced_writes: Annotated[int, OmitEmpty]
    why: str
    writes_total: Annotated[int, When("once the log has dumped")]


class PerformReply(MameEnvelope, account.SequenceFields, account.SequenceRun, total=False):
    failed: Annotated[dict[str, Any], When("`step_failed`")]
    verdict: Annotated[str, When("once the list waited")]
    frame_reached: Annotated[int | dict[str, Any], When("with `until_frame`")]
    operations: list[Any]
    until_frame: int
    visible_cpu: str | dict[str, Any]
    visible_cpu_kept: dict[str, Any]


class PerformExportReply(MameEnvelope, media_replies.PerformExportFields, total=False):
    pass


class ReadBlockReply(MameConsoleAccount, total=False):
    addr: Annotated[str, When("with `ref`")]
    addr_cpu: Annotated[str, When("with `ref`")]
    bytewidth: Required[int]
    call: str
    endianness: Required[str]
    evaluated_by: str
    hex: Required[str]
    kind: Required[str]
    length: int
    lines_ahead: int
    map_entry: dict[str, Any]
    offset: int
    pc_before: str
    pending: bool
    reader_steps: Annotated[int, OmitEmpty]
    regpoint_hit: dict[str, Any]
    seen_bytes: int
    size: Required[int]
    start: Annotated[str, When("with `ref`")]
    tag: str
    tags: dict[str, Any]
    watch_hit: dict[str, Any]
    watches: list[Any]


class ReadMemoryReply(MameEnvelope, total=False):
    addr: Required[str]
    cpu: str | dict[str, Any]
    hex: Required[str]
    length: int


class RecordReply(MameRecordingRun, total=False):
    avi_frames: Annotated[int | dict[str, Any], When("once answered")]
    began: Annotated[bool, When("once answered")]
    bytes: Annotated[int | dict[str, Any], When("once answered")]
    cycles: int | dict[str, Any]
    drain_steps: Annotated[int, OmitEmpty]
    tagged_lines: list[Any]
    verdict: Annotated[str, When("once answered")]
    view: Required[str | dict[str, Any]]
    watch_hit: dict[str, Any]
    watches: list[Any]


class RegistersReply(MameEnvelope, total=False):
    cpu: str
    register_bits: Required[dict[str, Any]]
    regs: Required[dict[str, Any]]
    superseded: Annotated[bool, When("with `from_last_stop`")]


class RegpointAddReply(MameEnvelope, total=False):
    already_stored: Annotated[bool, OmitEmpty]
    armed: Required[bool]
    by: str
    command_chars: int
    condition: str
    cpu: str | dict[str, Any]
    entry: Required[str]
    index: int
    limit_chars: int
    ref: Required[str]
    state: Required[str]
    stored: Required[bool]
    while_running: Required[bool]


class ResetReply(MameEnvelope, total=False):
    boot_pc: Required[str | dict[str, Any]]
    cpu: str
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: int
    frame_at_reset: Required[int]
    kind: Required[str]
    pc: Required[str]
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    taps_across: Annotated[list[Any], When("a tap was live")]
    verified: Required[bool]
    watch_hit: dict[str, Any]
    watches: list[Any]


class ResumeReply(MameEnvelope, total=False):
    average_speed: dict[str, Any]
    cpu: str
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: int
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    verdict: Annotated[str, When("with a bound")]
    waited_s: Annotated[float, When("with a bound")]
    watch_hit: dict[str, Any]
    watches: list[Any]


class RomCheckReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    deterministic: Required[bool]
    query_s: Required[float]
    rom_check: Required[str]


class RunForReply(MameEnvelope, total=False):
    command_chars: int
    cpu: str | dict[str, Any]
    cycles: Required[int | dict[str, Any]]
    following: list[str]
    instruction: StopInstruction
    disarmed_watches: list[Any]
    emulated_after_s: Required[float | dict[str, Any]]
    emulated_before_s: Required[float]
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    frame_after: Required[int | dict[str, Any]]
    frame_before: Required[int | dict[str, Any]]
    limit_chars: int
    not_rearmed: list[Any]
    pc: str
    polls: Annotated[int, When("by frames")]
    reads: Annotated[int, When("by milliseconds")]
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    verdict: Required[str]
    watch_hit: dict[str, Any]
    watches: list[Any]


class RunToReply(MameEnvelope, total=False):
    addr: str
    call: Annotated[str, When("a run to a screen")]
    evaluated_by: Annotated[str, When("a run to a screen")]
    lines_ahead: Annotated[int, When("a run to a screen")]
    pc_before: Annotated[str, When("a run to a screen")]
    reader_steps: Annotated[int, OmitEmpty]
    resent: Annotated[int, OmitEmpty]
    thread_errors: int
    armed: bool
    command_chars: int
    condition: str
    control: str
    control_dasm: list[Any]
    control_hits: Annotated[int, When("a run to a ref or an anchor")]
    console_reruns: int
    control_on: list[Any]
    controls: Annotated[list[Any], When("a run to a ref or an anchor")]
    cpu: str | dict[str, Any]
    following: list[str]
    frames: Annotated[int, When("a screen with no anchor")]
    instruction: StopInstruction
    disarmed_watches: list[Any]
    errorlog: dict[str, Any]
    frame: int
    limit_chars: int
    not_rearmed: list[Any]
    pc: str
    ref: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    screen: dict[str, Any]
    state: str
    stop_seq: int
    stored: bool
    target_disarmed: Annotated[
        bool, When("the target was left armed or the interrupt went unanswered")]
    verdict: Required[str]
    watch_hit: dict[str, Any]
    watches: list[Any]


class ScreenWaitReply(RunForReply, total=False):
    already: bool
    entries: int
    frames: Annotated[int, When("once answered")]
    palette: str
    polls: Annotated[int, When("once answered")]
    predicate: Annotated[str, When("once answered")]
    sampled_every: Annotated[int, When("once answered")]
    screen: Annotated[dict[str, Any], When("a screen predicate")]
    verdict: Required[str]
    waited_s: Annotated[float, When("once answered")]


class ScreenSignatureReply(MameConsoleAccount, total=False):
    call: str
    crop: list[Any]
    evaluated_by: str
    frame_screen: int
    height: Required[int]
    kind: str
    lines_ahead: int
    pc_before: str
    reader_steps: Annotated[int, OmitEmpty]
    screen: str
    signature: Required[str]
    width: Required[int]


class ScreenViewReply(MameConsoleAccount, total=False):
    bbox: list[Any]
    call: str
    color: str
    crop: list[Any]
    entries: Required[int]
    evaluated_by: str
    frame_screen: Required[int]
    height: Required[int]
    histogram: Annotated[list[Any], When("mode histogram")]
    image: Annotated[dict[str, Any], When("not for mode histogram")]
    isolate_color: str
    lines_ahead: int
    mode: str
    palette: Required[str | dict[str, Any]]
    pc_before: str
    pen: int
    pens: list[Any]
    pens_not_restored: list[Any]
    pens_used: int
    pixels: int
    point_in_crop: list[Any]
    reader_steps: Annotated[int, OmitEmpty]
    rows_cut: bool
    same_color_write: dict[str, Any]
    screen: Required[str]
    screen_indexed: Required[bool]
    screen_type: str
    screens: list[Any]
    set_by: dict[str, Any]
    unused: list[Any]
    watches: list[Any]
    width: Required[int]
    x: int
    y: int


class SeriesCaptureReply(MameConsoleAccount, total=False):
    emulated_after_s: float | dict[str, Any]
    emulated_before_s: float | dict[str, Any]
    count: Required[int]
    crop: list[Any]
    cycles: int
    distinct: Required[int]
    first: int
    frame_after: int
    frame_before: int
    frame_source: str
    frames_asked: int
    kept_after_close: Required[bool]
    last: int
    lost: Required[list[Any]]
    manifest: Required[str]
    polls: int
    verdict: str


class SetRegisterReply(MameEnvelope, total=False):
    cpu: str
    readback: Required[str]
    register: Required[str]
    value: str
    verified: Required[bool]


class SnapshotReply(MameEnvelope, total=False):
    bytes: Required[int]
    path: Required[str]
    sha256: Required[str]
    view: Required[str | dict[str, Any]]


class WindowRefused(MameEnvelope, tool_replies.WindowRefusedFields, total=False):
    """What a `window_not_visible` refusal says of the window it looked for."""


class WindowReply(WindowRefused, tool_replies.WindowSizeField, total=False):
    window: Required[dict[str, Any]]


class StartReply(WindowRefused, total=False):
    kept: Annotated[str, OmitEmpty]
    after_s: float
    alive: bool
    background: bool
    binary: str
    binary_origin: str
    boot_lua_path: str
    bundle: str
    cfg: dict[str, Any]
    debugger: dict[str, Any]
    declarations: dict[str, Any]
    dial_attempts: list[Any]
    env: Annotated[dict[str, Any], OmitEmpty]
    error: str
    errorlog_path: str
    flags: list[Any]
    frame: Required[int | dict[str, Any]]
    frame_symbol: str | dict[str, Any]
    machine: dict[str, Any]
    pc: Required[str]
    phase: str
    pid: Required[int]
    presence: bool
    profile: dict[str, Any]
    recommended_release: Required[str]
    registers: list[Any]
    reply: str
    rom_check: Required[str]
    scratch_dir: str
    start_retries: Annotated[list[Any], OmitEmpty]
    state_dir: str
    stdout_kept: str
    stdout_path: str
    stdout_tail: str
    stub_port: int
    symbols_by_class: dict[str, Any]
    symbols_by_cpu: dict[str, Any]
    symbols_format: str
    symbols_total: int
    symbols_typed: Annotated[int, OmitEmpty]
    system: str
    throttle_from_frame: Annotated[int, OmitEmpty]
    version: str | dict[str, Any]
    view: str | dict[str, Any]
    views: list[Any] | dict[str, Any]
    window: Annotated[dict[str, Any], When("with `shared`")]


class StateListReply(MameEnvelope, total=False):
    state_dir: Required[str]
    states: Required[list[Any]]


class StatusReply(MameEnvelope, total=False):
    last_stop: Annotated[dict[str, Any], When("with or without a session")]
    exit_code: Annotated[int | dict[str, Any], When("exited under it")]
    cfg: dict[str, Any]
    console_pending: Annotated[int, When("with a session")]
    debugger: Annotated[dict[str, Any], When("with a session")]
    errorlog_path: Annotated[str, When("with a session")]
    fingerprint: Annotated[str, When("with a session")]
    fingerprints: dict[str, Any]
    frame_symbol: str | dict[str, Any]
    in_debugger: Annotated[dict[str, Any], When("with a session")]
    pc: Annotated[str | dict[str, Any], When("with a session")]
    pid: Annotated[int, When("with a session")]
    presence: Annotated[bool, When("with a session")]
    scratch_dir: Annotated[str, When("with a session")]
    state_dir: Annotated[str, When("with a session")]
    stdout_path: str
    stub_port: Annotated[int, When("with a session")]
    system: Annotated[str, When("with a session")]
    tallies_pending_removal: Annotated[list[Any], When("with a session")]
    threads: dict[str, Any]
    throttles_pending: Annotated[list[Any], OmitEmpty]
    broken: Annotated[str, When("can no longer be trusted")]


class StepReply(MameEnvelope, total=False):
    command_chars: int
    cpu: str
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    instructions_completed: Required[int]
    limit_chars: int
    mode: str
    others: Annotated[dict[str, Any], When("a thread per cpu")]
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    watch_hit: dict[str, Any]
    watches: list[Any]


class StopReply(MameEnvelope, total=False):
    average_speed: dict[str, Any]
    cpu: str
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    interrupted: Required[bool]
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    watch_hit: dict[str, Any]
    watches: list[Any]


class SymbolsFindReply(MameEnvelope, total=False):
    addr: Annotated[str, When("by address")]
    cpu: str
    delta: Annotated[int, When("by address")]
    linear: str
    memory: Annotated[str, When("by address")]
    name: str
    query: Annotated[str, When("by name")]
    symbols: Annotated[list[Any], When("by name")]
    symbols_total: Annotated[int, When("by name")]
    truncated: Annotated[bool, When("by name")]


class ThrottleReply(MameEnvelope, total=False):
    applies: str
    confirmed_by: str
    frame: int
    on: bool
    pending: Required[bool]
    tag: Required[str]
    tagged_lines: list[Any]
    waited_s: float


class TraceReply(MameEnvelope, total=False):
    emulated_after_s: float | dict[str, Any]
    emulated_before_s: float | dict[str, Any]
    cpu: str | dict[str, Any]
    cycles: int
    following: list[str]
    instruction: StopInstruction
    errorlog: dict[str, Any]
    frame: int
    frame_after: int
    frame_before: int
    path: str
    pc: str | dict[str, Any]
    polls: int
    regs: dict[str, Any]
    stop_seq: int
    trace: Required[dict[str, Any]]
    verdict: str


class WatchAddReply(MameEnvelope, total=False):
    addr: str
    already_stored: Annotated[bool, OmitEmpty]
    armed: Required[bool]
    by: str
    call: str
    condition: str
    condition_typed: str
    cpu: str
    cpus_with_io: list[Any]
    entry: str
    fmt: str
    index: int
    installed: bool
    length: int
    lines_ahead: int
    mine: bool
    mode: str
    pending: bool
    pointer: dict[str, Any]
    read_maps_to: str
    reading: Annotated[dict[str, Any], When("on a stopped machine")]
    ref: str
    source: dict[str, Any]
    space: str
    state: Required[str]
    stored: Required[bool]
    tally_id: str
    trigger: str
    trigger_addr: str
    trigger_maps_to: str
    trigger_type: str
    values_from: str
    visible_cpu: str
    while_running: bool
    write_maps_to: str


class WriteReply(MameEnvelope, total=False):
    addr: Required[str]
    bytes_written: Required[int]
    captures_reading_it: Annotated[list[Any], When("with `region`")]
    cpu: str | dict[str, Any]
    readback: Required[str]
    region: str
    region_offset: Annotated[int, When("with `region`")]
    target: Annotated[str, When("on ROM")]
    verified: Required[bool]


class CommentWriteReply(MameEnvelope, tool_replies.CommentWriteFields, total=False):
    cpu: str
    held_in_memory: bool


class DeclarationClearReply(MameEnvelope, total=False):
    declarations_cleared: Required[int]
    disarmed: Required[list[Any]]
    tallies_removed: Annotated[list[Any], When("removing an io tap")]
    while_running: Required[bool]


class DeclarationListReply(MameEnvelope, total=False):
    breakpoints: Annotated[list[Any], When("each kind asked")]
    cpu: str | dict[str, Any]
    foreign: Annotated[dict[str, Any], OmitEmpty]
    regpoints: Annotated[list[Any], When("each kind asked")]
    watches: Annotated[list[Any], When("each kind asked")]


class MapWriteReply(MameConsoleAccount, tool_replies.MapWriteFields, total=False):
    call: str
    evaluated_by: str
    lines_ahead: int
    pc_before: str
    reader_steps: Annotated[int, OmitEmpty]


class ScanReply(MameEnvelope, total=False):
    addr: Annotated[str, When("`start`")]
    cell_bytes: int
    cleared: Annotated[bool, When("`clear`")]
    closed: Annotated[bool, When("`filter`")]
    cpu: str
    hits: Annotated[list[Any], When("`filter`")]
    hits_total: Annotated[int, When("`start`", "`filter`")]
    iterations: Annotated[int, When("`filter`")]
    length: int
    operator: str
    space: Annotated[str, When("`start`", "`filter`")]
    truncated: Annotated[bool, When("`filter`")]
    value: str | dict[str, Any]


class StateWriteReply(MameEnvelope, total=False):
    bytes: Annotated[int, When("`save`")]
    cpu: str
    following: list[str]
    instruction: StopInstruction
    differs: dict[str, Any]
    errorlog: Required[dict[str, Any]]
    frame: Required[int | dict[str, Any]]
    held: Annotated[str, When("held for a timer")]
    mark: Annotated[dict[str, Any], When("`load`")]
    name: str
    output: Annotated[str, When("`load`")]
    path: Required[str]
    pc: Required[str]
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    rom_check: Annotated[str | dict[str, Any], When("`load`")]
    saved: Annotated[dict[str, Any], When("`load`")]
    stop_seq: Annotated[int, When("`load`", "held")]
    system: str
    taps_across: Annotated[list[Any], When("a tap was live")]
    verified: Annotated[bool | dict[str, Any], When("`load`")]
    watch_hit: dict[str, Any]
    watches: list[Any]


#: Each tool's reply model, by the tool's name.
class PromoteReply(MameEnvelope, core_promote.PromoteFields, total=False):
    """`promote`: the store, a review's candidates, an approval's writes, what is still kept."""


MODELS: dict[str, type] = {
    "comment_write": CommentWriteReply,
    "declaration_clear": DeclarationClearReply,
    "declaration_list": DeclarationListReply,
    "screen_map_write": MapWriteReply,
    "promote": PromoteReply,
    "scan": ScanReply,
    "state_write": StateWriteReply,
    "audio_record": AudioRecordReply,
    "breakpoint_at": BreakpointAtReply,
    "captures": CapturesReply,
    "close": CloseReply,
    "comment_list": CommentListReply,
    "cpu_info": CpuInfoReply,
    "debug": DebugReply,
    "disassemble": DisassembleReply,
    "drive": DriveReply,
    "find": FindReply,
    "cpu_focus": FocusReply,
    "window": WindowReply,
    "gfx_blit_source": GfxBlitSourceReply,
    "gfx_blits": GfxBlitsReply,
    "gfx_draft": GfxDraftReply,
    "gfx_film": GfxFilmReply,
    "gfx_load": GfxLoadReply,
    "gfx_locate": GfxLocateReply,
    "gfx_sweep": GfxSweepReply,
    "gfx_view": GfxViewReply,
    "history": HistoryReply,
    "input": InputReply,
    "log": LogReply,
    "log_wait": LogWaitReply,
    "lua": LuaReply,
    "machine_map": MachineMapReply,
    "screen_map_find": MapFindReply,
    "memdump": MemdumpReply,
    "palette": PaletteReply,
    "palette_log": PaletteLogReply,
    "perform": PerformReply,
    "perform_export": PerformExportReply,
    "read_block": ReadBlockReply,
    "read_memory": ReadMemoryReply,
    "record": RecordReply,
    "registers": RegistersReply,
    "regpoint_add": RegpointAddReply,
    "reset": ResetReply,
    "resume": ResumeReply,
    "rom_check": RomCheckReply,
    "run_for": RunForReply,
    "run_to": RunToReply,
    "screen_wait": ScreenWaitReply,
    "screen_signature": ScreenSignatureReply,
    "screen_view": ScreenViewReply,
    "series_capture": SeriesCaptureReply,
    "set_register": SetRegisterReply,
    "snapshot": SnapshotReply,
    "start": StartReply,
    "state_list": StateListReply,
    "status": StatusReply,
    "step": StepReply,
    "stop": StopReply,
    "symbols_find": SymbolsFindReply,
    "throttle": ThrottleReply,
    "trace": TraceReply,
    "watch_add": WatchAddReply,
    "write": WriteReply,
    **{name: media_replies.MODELS[name] for name in ("audio_compare", "image_compare")},
}
