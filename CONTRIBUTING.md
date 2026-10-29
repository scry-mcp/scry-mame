# Contributing to scry-mame

This is the guide for changing the server. What the tools promise is in `REFERENCE.md`; this
file says where the code lives, how to run the battery and the live tiers, and what proves a
change.

## Where the code lives

`src/scry_mame/server.py` holds the tools and `src/scry_mame/mcp.py` the MCP boundary (the server
object, its `instructions`, the roster of tools by family). Every other module in `src/scry_mame/`
holds one concern, and its
docstring opens with what it holds and why: read that before changing it. What both Scry servers
share (the reply contract, the reference generator, the demo runner, the probe, the live bench)
is the scry-core package, pinned by tag in `pyproject.toml`. `demos/` holds the demos on free sets and `patches/` the MAME patches the README names. `tests/` holds the
contract tests and `tests/live/` the tiers that drive a real emulator.

## The battery

```sh
uv run ruff check .
uv run mypy --strict .
uv run mypy --strict --platform win32 .
uv run pytest -q
bash .githooks/pre-commit.test.sh   # the hook's own cases
```

Ruff and mypy (strict, over the whole tree) judge the code, the second mypy as Windows sees it, so
a call Windows lacks goes red on any host until it is guarded by `sys.platform`; pytest runs the
contract tests and, through `--cov`, the coverage floor in `pyproject.toml`; the last line runs the
pre-commit hook's own cases. All five green is what a change needs before it is committed.

On Windows the battery is the same, with `uv run pytest -q --no-cov`: the floor is judged on macOS
only, because Windows skips by design the cases that need what it lacks (a FIFO, a mode bit, a
symlink), and the floor counts the whole tree.

`.github/workflows/ci.yml` runs this battery on GitHub's Linux runners when started by hand, with
`--no-cov` since the floor is macOS's, plus the pre-commit's checks (which need `jscpd` on the
`PATH`, here as on a contributor's machine); the live tier stays on macOS and Windows, where an
emulator and a display are. The suite needs a `lua` on the `PATH` (the Lua doubles run MAME's Lua
through it) and, on Linux, `lsof` (the stub owner reads it); the workflow installs both.

A tool's reply model is its contract. A field every `ok` reply of the tool carries is `Required[...]`
in the model; one that comes only under a condition is `Annotated[T, When("words")]`, and the
tool's `Reply:` sentence says those words beside the field; a datum that could not be read is
`unavailable(why)` and never absent. The battery refuses an `ok` reply that lacks a required field,
and `tests/test_reply_models.py` refuses a promised field whose condition the sentence does not say.

A change to a tool's arguments, reply model or description changes its reference page, and
`tests/test_reference_pages.py` goes red naming the tool, the page and the line. Regenerate the pages from the
code, and the examples only from a live run's transcript (each `--mark` spells a directory of
the run's host, as the committed examples do):

```sh
uv run python -m scry_core.reference scry_mame.server:REFERENCE --write
uv run python -m scry_core.reference scry_mame.server:REFERENCE --write \
    --examples <transcript.jsonl ...> --mark '/tmp/<the run>=$TMPDIR'
```

A green live run deletes its scratch, transcript included: hard-link `transcript.jsonl` while it
runs. A clock reading, pid, port or scratch directory name in a reply is hidden by the generator.
`--skip '<regex>'` leaves out the cells whose call, reply, section or label match it, so a tool
whose first cell ran on a board a stranger cannot have takes its next cell as its example; a tool
with no other cell keeps none.

The commit itself runs scry-core's pre-commit (`python -m scry_core.hook --help` says what it checks): enable it once per clone with

```sh
git config core.hooksPath .githooks
```

Every pytest run judges the coverage floor: `--cov` is in `addopts` and the floor is
`fail_under` in `pyproject.toml`. A partial run goes red on that floor by construction, because
the floor is the whole repository's, so for a single file add `--no-cov` and read it as a run
that judged no floor. The live tier is not part of `pytest`: it is the two scripts below, so a clone runs no emulator
by accident.

The ruff and mypy configuration in `pyproject.toml` is scry-core's bar; mypy runs strict with no
path list, so a new directory is covered without being added anywhere.

A guarantee in the reference has a test that fails against the defect it guards. The console
parsers are held to text captured live rather than authored; the captures are under
`tests/fixtures/console/`, with their provenance in `tests/fixtures/README.md`.

## The live tier

The live half is `tests/live/live_check.py` against a real board. It drives every tool through
the server, the running contract and the throttle flight included.

```sh
uv run python tests/live/live_check.py
```

Its checks are mostly on the `m68k-dual` board; the rest run the demos on the free sets with the
MAME `MAME_BINARY` names, and a host without either leaves something unexamined, which is INVALID
and not a pass. The tracked live code names boards only by label.

`tests/live/live_matrix.py` is the matrix around those checks (every tool, every machine state,
every argument edge, every pair of tools that share state), one printed line per cell:

    timeout 1800 uv run python tests/live/live_matrix.py

Its cells are declared before anything boots, so the count PLANNED is printed first and a cell the
run never reached shows at the end. A cell is OK when the reply matches the tool's published
contract for that state and input, FAIL when it contradicts it, raises, or leaves the session
block disagreeing with the machine, and BLOCKED when it could not run, with the reason; every call
lands whole in a JSONL transcript. `MAME_LIVE_SECTIONS` names the letters to run (all, unset);
`MAME_LIVE_JOBS` runs each letter as a process of its own, that many at once (unset, half the
host's CPUs; `1`, one after another), while section X, the focus gate, opens and closes the run in
the parent so its watch spans every job. The focus gate's start in front and its Space move take
the desk of whoever is working, so they run only with `SCRY_FOCUS_CONTROL=1` on an idle machine;
unset, those cells are BLOCKED naming the variable and the verdict says it is unproven. The free boards and the games' boards run on the MAME
`MAME_BINARY` names, built with every driver, and the free boards read their sets from `MAME_TEST_ROMS`; unset, those cells
are BLOCKED naming the variable. The LineUp demo reads its romset and symbol map from
`LINEUP_MAME_ROMS`, and is BLOCKED the same way without it. The cells that open a watched
window open it as `start` does, and the host's own arguments (*The window, and the host's own
arguments*, on [`start`'s page](docs/reference/session.md#start)) place it, so a host can keep
those runs off the display somebody works on.

## The bench the live tier reads

The private boards run on a bench: copies of their ROMs and symbol files, and of the binary of a
board that runs its own, pinned by hash in the bench's own `bench.json`, with an `identity.json`
beside it that says which set and files each board's label stands for (its keys: `IDENTITY_KEYS` in `tests/live/bench_boards.py`). A live
run reads no other repository, so a session editing a checkout cannot change what it measures.

Neither file is tracked, because both name the programs the copies came from. The bench is the
directory `MAME_LIVE_BENCH` names, else `.local/share/scry-bench/mame` under your home directory.

```sh
uv run python -m scry_core.live_bench fill --bench <bench> --from <source_repo>=<checkout>
uv run python -m scry_core.live_bench check --bench <bench>
```

`fill` copies the files from their checkouts and `check` says whether they still match. A board
whose identity is incomplete or whose copies are absent or wrong is BLOCKED naming what is wrong,
and never runs on something else.

## What a live run guards

A live run refuses a host that cannot start MAME, and proves it left none running. Before its
first start it launches the board once in a form that ends by itself; one that does not return is
INVALID naming the host, and nothing else is launched. Every MAME a session starts is recorded
where it is spawned, and at the end of the run one still alive is killed and FAILS the run by
name. A green run removes its scratch; a red, INVALID or broken one keeps it and prints its path
(`scry_core.live_host`).

## Development scripts

None beyond the tests and the live tier: this server has no bench script and no sweep that sits
off the commit path.

## Fixtures and the sweep off the commit path

This server has no generated fixtures and no sweep kept off the commit path. The fixtures under
`tests/fixtures/` are captures of real output; the console ones are described above.

## Proving a change

A change to a tool's description, arguments or `instructions` is probed: the probe hands a model
only what a client delivers and checks that it calls the tool as the contract says. The
pre-commit runs its `--check`, which asks no model and names a tool or argument with no task in
`mcp_probe/tasks/`; a real run asks the `claude` CLI and judges each task over several runs:

```sh
uv run python -m scry_core.probe mame --servers mcp_probe/servers.py --tasks mcp_probe/tasks --check
uv run python -m scry_core.probe mame --servers mcp_probe/servers.py --tasks mcp_probe/tasks --runs 3
```

`python -m scry_core.probe --help` says how a failure is told from the model's noise.
