"""THE REPLY MODELS, one per tool: the fields each tool's reply names beside the envelope
every reply carries, published as its `outputSchema` (names only) and held to every reply
the battery builds (`scry_core.reply_schema`). Named from the replies the battery and the
live runs built, so a branch none of them reached is unnamed until one does: a field a
reply grows is named here in the same change. The file tools' models are the core's
(`scry_core.media_replies`)."""

from __future__ import annotations

from typing import Any

from scry_core import media_replies
from scry_core import sequence_account as account
from scry_core.reply_schema import ReplyEnvelope


class MameEnvelope(ReplyEnvelope, total=False):
    """What this server's shared paths add to any reply: the stop a call met or
    applied, the refusal's context."""

    answers_while_running: list[Any]
    broken: str
    cause: str
    #: The machine's cpus by tag: what a refusal of a cpu offers, and `status`'s list. A row
    #: per cpu is `cpus`, `cpu_info`'s and `machine_map`'s.
    cpu_tags: list[str]
    exit_code: int | dict[str, Any]
    last_stop: dict[str, Any]
    stopped_on_its_own: dict[str, Any]


class MameConsoleAccount(MameEnvelope, total=False):
    """The account of a call the console evaluated (a Lua line, a read, a recording): what
    ran, how the reader fared, and the stop the machine is at."""

    console_reruns: int
    cpu: str
    dasm: list[Any] | dict[str, Any]
    errorlog: dict[str, Any]
    frame: int
    pc: str
    regs: dict[str, Any]
    resent: int
    stop_seq: int
    thread_errors: int



class AudioRecordReply(MameConsoleAccount, total=False):
    began: bool
    bytes: int | dict[str, Any]
    channels: int | dict[str, Any]
    cycles: int
    drain_steps: int
    emulated_s: float | dict[str, Any]
    ended: bool
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
    note: str
    path: str
    pending: bool
    polls: int
    reader_steps: int
    recording_after: bool | dict[str, Any]
    regpoint_hit: dict[str, Any]
    sample_max: int | dict[str, Any]
    sample_min: int | dict[str, Any]
    sample_rate_hz: int | dict[str, Any]
    samples: int | dict[str, Any]
    tagged_lines: list[Any]
    verdict: str
    watch_hit: dict[str, Any]
    watches: list[Any]


class BreakpointAtReply(MameEnvelope, total=False):
    addr: str
    already_stored: bool
    armed: bool
    by: str
    command_chars: int
    condition: str
    condition_typed: str
    cpu: str
    entry: str
    limit_chars: int
    note: str
    ref: str
    role: str
    state: str
    stored: bool
    temp: str
    visible_cpu: str
    while_running: bool


class BreakpointClearReply(MameEnvelope, total=False):
    declarations_cleared: int
    disarmed: list[Any]
    note: str
    while_running: bool


class BreakpointListReply(MameEnvelope, total=False):
    breakpoints: list[Any]
    cpu: str | dict[str, Any]
    foreign: list[Any]


class CapturesReply(MameEnvelope, total=False):
    captures: list[Any]


class CloseReply(MameEnvelope, total=False):
    average_speed: dict[str, Any]
    cfg: dict[str, Any]
    closed: bool
    console_drained: int
    console_pending_before: int
    ended_by: str
    errorlog_tail: str
    note: str
    state_written: bool | dict[str, Any]
    stdout_tail: str


class CommentAddReply(MameEnvelope, total=False):
    comment: dict[str, Any]
    cpu: str
    declarations: dict[str, Any]
    held_in_memory: bool
    note: str
    replaced_comments: list[Any]


class CommentDeleteReply(MameEnvelope, total=False):
    cpu: str
    declarations: dict[str, Any]
    deleted: dict[str, Any]
    held_in_memory: bool
    note: str


class CommentListReply(MameEnvelope, total=False):
    comments: list[Any]
    comments_total: int
    cpu: str | dict[str, Any]
    declarations: dict[str, Any]
    truncated: bool


class CommentLoadReply(MameEnvelope, total=False):
    added: int
    comments_total: int
    declarations: dict[str, Any]
    held_in_memory: bool
    note: str
    parsed: int
    path: str
    replaced_comments: list[Any]
    replaced_total: int
    truncated: bool
    unchanged: int


class CommentSaveReply(MameEnvelope, total=False):
    comments_total: int
    dropped_comments: list[Any]
    dropped_total: int
    note: str
    path: str
    truncated: bool


class CpuInfoReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    cpus: list[Any]


class DebugReply(MameEnvelope, total=False):
    clipped: bool
    command: str
    command_chars: int
    ignored: list[Any] | dict[str, Any]
    limit_chars: int
    mutates: bool
    not_run: list[Any]
    note: str
    output: str
    output_chars: int
    output_path: str
    refused: list[Any]
    refused_total: int
    visible_cpu: str | dict[str, Any]


class DisassembleReply(MameEnvelope, total=False):
    addr: str
    cpu: str | dict[str, Any]
    flow: list[Any]
    flow_source: str
    length: int
    lines: list[Any]
    note: str
    resolved: list[Any]


class DriveReply(MameEnvelope, total=False):
    act: dict[str, Any]
    looked: dict[str, Any]
    operations: list[Any]
    verify: dict[str, Any]


class FindReply(MameEnvelope, total=False):
    addr: str
    cpu: str | dict[str, Any]
    hits: list[Any]
    hits_total: int
    length: int
    span: dict[str, Any]
    symbol_class: str
    truncated: bool


class FocusReply(MameEnvelope, total=False):
    cause: str
    cpu: str
    dasm: list[Any]
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    ignored: list[Any]
    machine_ran: bool
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    unchanged: list[Any]
    unread: list[Any]
    via: str
    was: str | dict[str, Any]
    watch_hit: dict[str, Any]
    watches: list[Any]


class GfxBlitSourceReply(MameConsoleAccount, total=False):
    asset: str
    blit_pc: str
    blit_symbol: str
    blits_in_frame: int
    box: list[Any]
    call: str
    callback_errors: dict[str, Any]
    data: dict[str, Any]
    destination: dict[str, Any]
    draw_command: str
    entries: int
    evaluated_by: str
    format: str
    frame_blit: int
    image: dict[str, Any]
    index: int
    indexes: list[Any]
    lines_ahead: int
    margin: int
    n: int
    not_proved: list[Any]
    note: str
    palette: str
    palettes: list[Any]
    pc_before: str
    pen_base: int
    reader_steps: int
    reads_source: bool
    rect: dict[str, Any]
    source_tile: int
    tag: str
    tile_height: int
    tile_width: int
    tiles_available: int
    watches: list[Any]
    wrap: bool


class GfxBlitsReply(MameConsoleAccount, total=False):
    area: list[Any]
    blits: list[Any]
    blits_in_frame: int
    by_plane: list[Any]
    call: str
    callback_errors: dict[str, Any]
    colors_repeat: bool
    commands: list[Any]
    covering: int
    declare: str
    draw_command: str
    evaluated_by: str
    frame_blit: int
    frame_complete: bool
    frame_screen: int
    frames_with_blits: dict[str, Any]
    height: int
    image: dict[str, Any]
    legend: list[Any]
    lines_ahead: int
    listed: dict[str, Any]
    listed_of: int
    next_first: int
    not_proved: list[Any]
    note: str
    overflow_rows: int
    pc_before: str
    reader_steps: int
    rows_cut: bool
    rows_kept: int
    rows_path: str
    screen: str
    tally_id: str
    topmost: dict[str, Any]
    watches: list[Any]
    width: int


class GfxDraftReply(MameEnvelope, total=False):
    asset_names: list[Any]
    chose: dict[str, Any]
    command_fields: dict[str, Any]
    confirm: str
    draft: str
    evidence: dict[str, Any]
    formats: dict[str, Any]
    manifest: dict[str, Any]
    marker: str
    not_proved: list[Any]
    not_proved_more: int
    report: dict[str, Any]


class GfxFilmReply(MameConsoleAccount, total=False):
    animation: dict[str, Any]
    armed_now: bool
    baseline_value: str | dict[str, Any]
    call: str
    callback_errors: dict[str, Any]
    cells: list[Any]
    cleared: bool
    cost: dict[str, Any]
    cpus_with_io: list[Any]
    dropped_frames: list[Any] | dict[str, Any]
    dropped_total: int
    evaluated_by: str
    files_kept: str
    film: dict[str, Any]
    frame_as_of: int
    frame_baseline: int | dict[str, Any]
    height: int
    image: dict[str, Any]
    install_call: str
    install_lines_ahead: int
    install_resent: int
    installed: bool
    judged: int
    judged_frames: list[Any] | dict[str, Any]
    kept: int
    lines_ahead: int
    listed: dict[str, Any]
    listing_path: str
    lost: dict[str, Any]
    met: int
    next_first: int
    note: str
    nothing_kept: str
    pc_before: str
    pending: bool
    pending_picture: bool
    reader_steps: int
    refused: int
    refused_frames: list[Any]
    removal: str
    state: str
    superseded: bool
    tally_id: str
    trigger_maps_to: str
    watches: list[Any]
    why: str
    width: int


class GfxLoadReply(MameEnvelope, total=False):
    assets: dict[str, Any]
    commands: dict[str, Any]
    draft: bool
    formats: dict[str, Any]
    loaded: bool
    note: str
    palette_ports: dict[str, Any]
    path: str
    replaced_path: str | dict[str, Any]
    sha256: str
    status_counts: dict[str, Any]
    still_loaded: str | dict[str, Any]
    system: str
    systems: list[Any]


class GfxLocateReply(MameConsoleAccount, total=False):
    addr: str
    addr_cpu: str
    ambiguous: bool
    ambiguous_windows: int
    bytewidth: int
    call: str
    candidates: list[Any]
    endianness: str
    evaluated_by: str
    evidence: dict[str, Any]
    flips: list[Any]
    frame_screen: int
    height: int
    kind: str
    lines_ahead: int
    matched: bool
    matches: list[Any]
    matches_total: int
    nearest: dict[str, Any]
    note: str
    offset: int
    palette: str
    patch: list[Any]
    pc_before: str
    pen_map: dict[str, Any]
    pending: bool
    reader_steps: int
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
    candidates: int | list[Any]
    cell_scale: int
    count: int
    endianness: str
    entries: int
    evaluated_by: str
    image: dict[str, Any]
    kind: str
    lines_ahead: int
    next: str
    note: str
    offset: int
    palette: str
    palettes: list[Any]
    pc_before: str
    pen_base: int
    pending: bool
    reader_steps: int
    real_colors: bool
    seen_bytes: int
    size: int
    sweep: int
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
    image: dict[str, Any]
    kind: str
    layout: dict[str, Any]
    lines_ahead: int
    note: str
    offset: int
    palette: str
    palettes: list[Any]
    pc_before: str
    pen_base: int
    pending: bool
    reader_steps: int
    real_colors: bool
    seen_bytes: int
    size: int
    tag: str
    tags: dict[str, Any]
    tiles_available: int


class HistoryReply(MameEnvelope, total=False):
    asked: int
    cpu: str | dict[str, Any]
    lines: list[Any]
    note: str


class InputReply(MameConsoleAccount, total=False):
    active: bool | dict[str, Any]
    cycles: int
    defvalue: str
    drain_steps: int
    field: str
    frame_after: int
    frame_before: int
    frame_release_planned: int
    frame_released: int
    frame_set: int
    frames: int
    instructions_completed: int
    lines_ahead: int
    mask: str
    mode: str
    name: str
    note: str
    pending: bool
    player: int
    polls: int
    port: str
    port_before: str
    port_held: str | dict[str, Any]
    reader_steps: int
    regpoint_hit: dict[str, Any]
    released: bool
    route: str
    seen_bytes: int
    tagged_lines: list[Any]
    value: str
    verdict: str
    watch_hit: dict[str, Any]
    watches: list[Any]


class LogReply(MameEnvelope, total=False):
    channel: str
    counts: dict[str, Any]
    labels: dict[str, Any]
    lines: list[Any]
    lines_total: int
    pattern: str
    truncated: bool


class LogWaitReply(MameEnvelope, total=False):
    already: bool
    arrived_during: int
    channel: str
    line: str
    lines_before: int
    lines_examined: int
    lines_total: int
    note: str
    pattern: str
    verdict: str
    waited_s: float


class LuaReply(MameConsoleAccount, total=False):
    call: str
    clipped: bool
    evaluated_by: str
    lines_ahead: int
    note: str
    output: str
    output_chars: int
    output_path: str
    pc_before: str
    pending: bool
    reader_steps: int
    regpoint_hit: dict[str, Any]
    script_chars: int
    seen_bytes: int
    watch_hit: dict[str, Any]
    watches: list[Any]


class MachineMapReply(MameEnvelope, total=False):
    address_map: list[Any]
    counts: dict[str, Any]
    cpu: str | dict[str, Any]
    cpus: list[Any]
    frame_symbol: str | dict[str, Any]
    note: str
    regions: list[Any]
    rom_files: list[Any]
    screens: list[Any]
    shares: list[Any]
    sources: dict[str, Any]
    spaces: list[Any]
    symbol_coverage: list[Any]
    truncated: bool


class MapAddReply(MameConsoleAccount, total=False):
    call: str
    controls: int
    evaluated_by: str
    kind: str
    lines_ahead: int
    match: list[Any]
    pc_before: str
    reader_steps: int
    replaced: bool
    screen: str
    shadows_file: bool
    size: list[Any]


class MapFindReply(MameConsoleAccount, total=False):
    call: str
    controls: list[Any]
    evaluated_by: str
    kind: str
    layer: str
    lines_ahead: int
    matched: bool
    pc_before: str
    reader_steps: int
    screen: str
    screens_mapped: int
    screens_tried: int
    size: list[Any]


class MapLoadReply(MameEnvelope, total=False):
    application: str
    controls: int
    path: str
    screens: int


class MapSaveReply(MameEnvelope, total=False):
    application: str
    controls: int
    path: str
    promoted: list[Any]
    screens: int


class MemdumpReply(MameEnvelope, total=False):
    addr: str
    bytes: int
    cpu: str | dict[str, Any]
    length: int
    path: str


class PaletteReply(MameConsoleAccount, total=False):
    alpha: list[Any]
    call: str
    colors: list[Any]
    count: int
    entries: int
    evaluated_by: str
    first: int
    highlights: bool
    image: dict[str, Any]
    indirect_entries: int
    lines_ahead: int
    palette: str
    palettes: list[Any]
    pc_before: str
    reader_steps: int
    shadows: bool
    truncated: bool


class PaletteLogReply(MameEnvelope, total=False):
    across: list[Any]
    armed_now: bool
    call: str
    callback_errors: dict[str, Any]
    cleared: bool
    component_bits: int
    cpu: str
    cpus_with_io: list[Any]
    data_port: str
    desyncs: int
    frame_as_of: int
    index_port: str
    index_writes: int
    install_resent: int
    installed: bool
    lines_ahead: int
    not_proved: list[Any]
    note: str
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
    protocol: str
    removal: str
    rows: list[Any]
    rows_cut: bool
    rows_kept: int
    rows_max: int
    rows_path: str
    sees_reset_and_load: bool
    setters: list[Any]
    setters_path: str | dict[str, Any]
    setters_total: int
    space: str
    state: str
    superseded: bool
    synced_at_start: bool
    tally_id: str
    unsynced_writes: int
    why: str
    writes_total: int


class PerformReply(MameEnvelope, account.SequenceFields, total=False):
    frame_reached: int | dict[str, Any]
    operations: list[Any]
    until_frame: int
    visible_cpu: str | dict[str, Any]
    visible_cpu_kept: dict[str, Any]


class PerformExportReply(MameEnvelope, total=False):
    checks: int
    cut: dict[str, Any]
    dropped: list[Any]
    dropped_total: int
    path: str
    replay: str
    steps: int


class ReadBlockReply(MameConsoleAccount, total=False):
    addr: str
    addr_cpu: str
    bytewidth: int
    call: str
    endianness: str
    evaluated_by: str
    hex: str
    kind: str
    length: int
    lines_ahead: int
    map_entry: dict[str, Any]
    offset: int
    pc_before: str
    pending: bool
    reader_steps: int
    regpoint_hit: dict[str, Any]
    seen_bytes: int
    size: int
    start: str
    tag: str
    tags: dict[str, Any]
    watch_hit: dict[str, Any]
    watches: list[Any]


class ReadMemoryReply(MameEnvelope, total=False):
    addr: str
    cpu: str | dict[str, Any]
    hex: str
    length: int


class RecordReply(MameConsoleAccount, total=False):
    avi_frames: int | dict[str, Any]
    began: bool
    bytes: int | dict[str, Any]
    cycles: int | dict[str, Any]
    drain_steps: int
    ended: bool
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
    note: str
    path: str
    pending: bool
    polls: int
    reader_steps: int
    recording_after: bool | dict[str, Any]
    regpoint_hit: dict[str, Any]
    tagged_lines: list[Any]
    verdict: str
    view: str | dict[str, Any]
    watch_hit: dict[str, Any]
    watches: list[Any]


class RegistersReply(MameEnvelope, total=False):
    cpu: str
    register_bits: dict[str, Any]
    regs: dict[str, Any]
    superseded: bool


class RegpointAddReply(MameEnvelope, total=False):
    already_stored: bool
    armed: bool
    by: str
    command_chars: int
    condition: str
    cpu: str | dict[str, Any]
    entry: str
    index: int
    limit_chars: int
    note: str
    ref: str
    state: str
    stored: bool
    while_running: bool


class RegpointClearReply(MameEnvelope, total=False):
    declarations_cleared: int
    disarmed: list[Any]
    note: str
    while_running: bool


class RegpointListReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    foreign: list[Any]
    regpoints: list[Any]


class ResetReply(MameEnvelope, total=False):
    boot_pc: str | dict[str, Any]
    cpu: str
    dasm: list[Any]
    errorlog: dict[str, Any]
    frame: int
    frame_at_reset: int
    kind: str
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    taps_across: list[Any]
    verified: bool
    watch_hit: dict[str, Any]
    watches: list[Any]


class ResumeReply(MameEnvelope, total=False):
    average_speed: dict[str, Any]
    cpu: str
    dasm: list[Any] | dict[str, Any]
    errorlog: dict[str, Any]
    frame: int
    note: str
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    verdict: str
    waited_s: float
    watch_hit: dict[str, Any]
    watches: list[Any]


class RomCheckReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    deterministic: bool
    query_s: float
    rom_check: str


class RunForReply(MameEnvelope, total=False):
    command_chars: int
    cpu: str | dict[str, Any]
    cycles: int | dict[str, Any]
    dasm: list[Any] | dict[str, Any]
    disarmed_watches: list[Any]
    emulated_after_s: float | dict[str, Any]
    emulated_before_s: float
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    frame_after: int | dict[str, Any]
    frame_before: int | dict[str, Any]
    limit_chars: int
    not_rearmed: list[Any]
    note: str
    pc: str
    polls: int
    reads: int
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    verdict: str
    watch_hit: dict[str, Any]
    watches: list[Any]


class RunToReply(MameEnvelope, total=False):
    addr: str
    armed: bool
    command_chars: int
    condition: str
    control: str
    control_dasm: list[Any]
    control_hits: int
    control_on: list[Any]
    controls: list[Any]
    cpu: str | dict[str, Any]
    dasm: list[Any] | dict[str, Any]
    disarmed_watches: list[Any]
    errorlog: dict[str, Any]
    frame: int
    limit_chars: int
    not_rearmed: list[Any]
    note: str
    pc: str
    ref: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    state: str
    stop_seq: int
    stored: bool
    target_disarmed: bool
    verdict: str
    watch_hit: dict[str, Any]
    watches: list[Any]


class ScanClearReply(MameEnvelope, total=False):
    cleared: bool
    note: str


class ScanFilterReply(MameEnvelope, total=False):
    closed: bool
    cpu: str
    hits: list[Any]
    hits_total: int
    iterations: int
    operator: str
    space: str
    truncated: bool
    value: str | dict[str, Any]


class ScanStartReply(MameEnvelope, total=False):
    addr: str
    cell_bytes: int
    cpu: str
    hits_total: int
    length: int
    space: str


class ScreenSignatureReply(MameConsoleAccount, total=False):
    call: str
    crop: list[Any]
    evaluated_by: str
    frame_screen: int
    height: int
    kind: str
    lines_ahead: int
    pc_before: str
    reader_steps: int
    screen: str
    signature: str
    width: int


class ScreenViewReply(MameConsoleAccount, total=False):
    bbox: list[Any]
    call: str
    color: str
    crop: list[Any]
    entries: int
    evaluated_by: str
    frame_screen: int
    height: int
    histogram: list[Any]
    image: dict[str, Any]
    isolate_color: str
    lines_ahead: int
    mode: str
    note: str
    palette: str | dict[str, Any]
    pc_before: str
    pen: int
    pens: list[Any]
    pens_not_restored: list[Any]
    pens_used: int
    pixels: int
    point_in_crop: list[Any]
    reader_steps: int
    rows_cut: bool
    same_color_write: dict[str, Any]
    screen: str
    screen_indexed: bool
    screen_type: str
    screens: list[Any]
    set_by: dict[str, Any]
    unused: list[Any]
    watches: list[Any]
    width: int
    x: int
    y: int


class SeriesCaptureReply(MameConsoleAccount, total=False):
    count: int
    crop: list[Any]
    cycles: int
    distinct: int
    first: int
    frame_after: int
    frame_before: int
    frame_source: str
    frames_asked: int
    kept_after_close: bool
    last: int
    lost: list[Any]
    manifest: str
    polls: int
    verdict: str


class SetRegisterReply(MameEnvelope, total=False):
    cpu: str
    readback: str
    register: str
    value: str
    verified: bool


class SnapshotReply(MameEnvelope, total=False):
    bytes: int
    path: str
    sha256: str
    view: str | dict[str, Any]


class StartReply(MameEnvelope, total=False):
    after_s: float
    alive: bool
    background: bool
    binary: str
    binary_origin: str
    boot_lua_path: str
    cfg: dict[str, Any]
    debugger: dict[str, Any]
    declarations: dict[str, Any]
    dial_attempts: list[Any]
    display: str
    env: dict[str, Any]
    error: str
    errorlog_path: str
    flags: list[Any]
    frame: int | dict[str, Any]
    frame_symbol: str | dict[str, Any]
    machine: dict[str, Any]
    note: str
    pc: str
    phase: str
    pid: int
    presence: bool
    registers: list[Any]
    reply: str
    rom_check: str
    scratch_dir: str
    start_retries: list[Any]
    state_dir: str
    stdout_kept: str
    stdout_path: str
    stdout_tail: str
    stub_port: int
    symbols_by_class: dict[str, Any]
    symbols_by_cpu: dict[str, Any]
    symbols_format: str
    symbols_total: int
    symbols_typed: int
    system: str
    throttle_from_frame: int
    version: str | dict[str, Any]
    view: str | dict[str, Any]
    views: list[Any] | dict[str, Any]


class StateListReply(MameEnvelope, total=False):
    state_dir: str
    states: list[Any]


class StateLoadReply(MameEnvelope, total=False):
    cpu: str
    dasm: list[Any] | dict[str, Any]
    differs: dict[str, Any]
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    held: str
    mark: dict[str, Any]
    name: str
    note: str
    output: str
    path: str
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    rom_check: str | dict[str, Any]
    saved: dict[str, Any]
    stop_seq: int
    system: str
    taps_across: list[Any]
    verified: bool | dict[str, Any]
    watch_hit: dict[str, Any]
    watches: list[Any]


class StateSaveReply(MameEnvelope, total=False):
    bytes: int
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    held: str
    name: str
    path: str
    pc: str
    stop_seq: int
    system: str


class StatusReply(MameEnvelope, total=False):
    cfg: dict[str, Any]
    console_pending: int
    debugger: dict[str, Any]
    errorlog_path: str
    fingerprint: str
    fingerprints: dict[str, Any]
    frame_symbol: str | dict[str, Any]
    in_debugger: dict[str, Any]
    note: str
    pc: str | dict[str, Any]
    pid: int
    presence: bool
    scratch_dir: str
    state_dir: str
    stdout_path: str
    stub_port: int
    system: str
    tallies_pending_removal: list[Any]
    threads: dict[str, Any]
    throttles_pending: list[Any]


class StepReply(MameEnvelope, total=False):
    command_chars: int
    cpu: str
    dasm: list[Any] | dict[str, Any]
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    instructions_completed: int
    limit_chars: int
    mode: str
    note: str
    others: dict[str, Any]
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    watch_hit: dict[str, Any]
    watches: list[Any]


class StopReply(MameEnvelope, total=False):
    average_speed: dict[str, Any]
    cpu: str
    dasm: list[Any] | dict[str, Any]
    errorlog: dict[str, Any]
    frame: int | dict[str, Any]
    interrupted: bool
    note: str
    pc: str
    regpoint_hit: dict[str, Any]
    regs: dict[str, Any]
    stop_seq: int
    watch_hit: dict[str, Any]
    watches: list[Any]


class SymbolsFindReply(MameEnvelope, total=False):
    addr: str
    cpu: str
    delta: int
    linear: str
    memory: str
    name: str
    note: str
    query: str
    symbols: list[Any]
    symbols_total: int
    truncated: bool


class ThrottleReply(MameEnvelope, total=False):
    applies: str
    confirmed_by: str
    frame: int
    on: bool
    pending: bool
    tag: str
    tagged_lines: list[Any]
    waited_s: float


class TraceReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    cycles: int
    dasm: list[Any]
    errorlog: dict[str, Any]
    frame: int
    frame_after: int
    frame_before: int
    path: str
    pc: str | dict[str, Any]
    polls: int
    regs: dict[str, Any]
    stop_seq: int
    trace: dict[str, Any]
    verdict: str


class WatchAddReply(MameEnvelope, total=False):
    addr: str
    already_stored: bool
    armed: bool
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
    note: str
    pending: bool
    pointer: dict[str, Any]
    read_maps_to: str
    reading: dict[str, Any]
    ref: str
    source: dict[str, Any]
    space: str
    state: str
    stored: bool
    tally_id: str
    trigger: str
    trigger_addr: str
    trigger_maps_to: str
    trigger_type: str
    values_from: str
    visible_cpu: str
    while_running: bool
    write_maps_to: str


class WatchClearReply(MameEnvelope, total=False):
    declarations_cleared: int
    disarmed: list[Any]
    note: str
    tallies_removed: list[Any]
    while_running: bool


class WatchListReply(MameEnvelope, total=False):
    cpu: str | dict[str, Any]
    foreign: list[Any]
    watches: list[Any]


class WriteReply(MameEnvelope, total=False):
    addr: str
    bytes_written: int
    captures_reading_it: list[Any]
    cpu: str | dict[str, Any]
    note: str
    readback: str
    region: str
    region_offset: int
    target: str
    verified: bool


#: Each tool's reply model, by the tool's name.
MODELS: dict[str, type] = {
    "audio_record": AudioRecordReply,
    "breakpoint_at": BreakpointAtReply,
    "breakpoint_clear": BreakpointClearReply,
    "breakpoint_list": BreakpointListReply,
    "captures": CapturesReply,
    "close": CloseReply,
    "comment_add": CommentAddReply,
    "comment_delete": CommentDeleteReply,
    "comment_list": CommentListReply,
    "comment_load": CommentLoadReply,
    "comment_save": CommentSaveReply,
    "cpu_info": CpuInfoReply,
    "debug": DebugReply,
    "disassemble": DisassembleReply,
    "drive": DriveReply,
    "find": FindReply,
    "focus": FocusReply,
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
    "map_add": MapAddReply,
    "map_find": MapFindReply,
    "map_load": MapLoadReply,
    "map_save": MapSaveReply,
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
    "regpoint_clear": RegpointClearReply,
    "regpoint_list": RegpointListReply,
    "reset": ResetReply,
    "resume": ResumeReply,
    "rom_check": RomCheckReply,
    "run_for": RunForReply,
    "run_to": RunToReply,
    "scan_clear": ScanClearReply,
    "scan_filter": ScanFilterReply,
    "scan_start": ScanStartReply,
    "screen_signature": ScreenSignatureReply,
    "screen_view": ScreenViewReply,
    "series_capture": SeriesCaptureReply,
    "set_register": SetRegisterReply,
    "snapshot": SnapshotReply,
    "start": StartReply,
    "state_list": StateListReply,
    "state_load": StateLoadReply,
    "state_save": StateSaveReply,
    "status": StatusReply,
    "step": StepReply,
    "stop": StopReply,
    "symbols_find": SymbolsFindReply,
    "throttle": ThrottleReply,
    "trace": TraceReply,
    "watch_add": WatchAddReply,
    "watch_clear": WatchClearReply,
    "watch_list": WatchListReply,
    "write": WriteReply,
    **{name: media_replies.MODELS[name]
       for name in ("audio_diff", "audio_measure", "golden_check",
                    "image_diff", "region_track", "series_diff")},
}
