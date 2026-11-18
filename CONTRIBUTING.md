# Contributing to scry-mame

This page is for changing the server: where the code lives, which checks a change must pass,
and what proves it. What the tools promise is in [REFERENCE.md](REFERENCE.md).

## Where the code lives

- `src/scry_mame/server.py` holds the tools, and `src/scry_mame/mcp.py` the MCP server object,
  its `instructions` and the list of tools by group.
- Every other module of `src/scry_mame/` holds one concern. Its docstring opens with what it
  holds and why: read that before changing it.
- What both SCRY servers share is the scry-core package, pinned by tag in `pyproject.toml`.
  [Its module list](https://github.com/scry-mcp/scry-core/blob/main/docs/modules.md) has one
  row per module.
- `demos/` holds the demos and `patches/` the MAME patches the README names.
- `tests/` holds the unit tests, and `tests/live/` the tests that drive a real emulator.

## The checks

```sh
uv run ruff check .
uv run mypy --strict .
uv run mypy --strict --platform win32 .
uv run pytest -q
bash .githooks/pre-commit-test.sh
```

All five pass before a change is committed. What each one proves:

- `ruff` and the first `mypy` check the code, strict, over the whole repository. A new
  directory is covered without being added anywhere.
- The second `mypy` reads the code as Windows sees it. A call Windows lacks fails on any
  computer until it is guarded by `sys.platform`.
- `pytest` runs the unit tests and checks the coverage floor in `pyproject.toml`.
- The last line runs the commit hook's own cases.

The tests run with a home and a temporary folder of their own, and fail a run that leaves a
file in that home (scry-core's `private_run`). Every file the server writes follows scry-core's
[rule of file names](https://github.com/scry-mcp/scry-core/blob/main/docs/file-names.md); a
red `names_judged` means one was written outside it.

On Windows the fourth command is `uv run pytest -q --no-cov`. The coverage floor is checked on
macOS only, because Windows skips the cases that need what it lacks (a FIFO, a mode bit, a
symlink).

`.github/workflows/ci.yml` runs the same checks on GitHub's Linux runners when started by hand,
with `--no-cov` and with `jscpd` installed for the hook. The tests need a `lua` on the `PATH`
and, on Linux, `lsof`; the workflow installs both.

### Running part of the tests

Every `pytest` run checks the coverage floor, which belongs to the whole repository, so a
partial run fails on it. Two traps follow from how `addopts` is written:

- `addopts` ends in a bare `--cov`, which takes the next argument as its source. So
  `uv run pytest tests/test_x.py` runs every test while looking like a one-file run.
- Narrow a run with `-o addopts=""` and the test files, or with `-k <module name> --no-cov`.
  Read it as a run that checked no floor.
- `-o addopts=` also drops the `not live` and `not window` deselections. Name test files with
  it, never a directory: `tests` would start a real emulator.

### The Lua the server sends

The Lua the server sends MAME lives in `src/scry_mame/lua/`. `lua_source.py` loads it and fills
each `__SCRY_<name>__` slot with a Lua literal of its value's type.

`tests/test_lua_scripts.py` checks every script as it is sent, with three programs, and fails
when one is missing: StyLua (`stylua --check`), `luac` of Lua 5.4, which is MAME's, and
luacheck. On macOS, `brew install stylua luacheck lua@5.4`. Windows skips that file: the
scripts are the same bytes there.

### A scry-core checkout

`uv run` syncs the environment before its command. So the next plain `uv run` replaces an
editable install of a scry-core checkout (`uv pip install -e ../scry-core`) with the pinned
package. The run then checks the pinned package while looking like a run on the checkout.

- Print `scry_core.__file__` from the project's Python before and after a run.
- Use `uv run --no-sync` (or `UV_NO_SYNC=1`) while the editable install is wanted, and
  reinstall it after a full run of the checks.
- Export `PYTHONPATH=<checkout>/src` for a run that must keep the checkout while another
  command syncs the environment.

## Changing a tool

A tool's reply model is its contract:

- A number whose natural notation is hex (an address, an offset, a port) is answered as `0x`
  text, and taken as `0x` text or an integer.
- A field every `ok` reply carries is `Required[...]` in the model.
- A field that comes only sometimes is `Annotated[T, When("words")]`, and the tool's `Reply:`
  sentence says those words beside it.
- A value that could not be read is `unavailable(why)`, never absent.

The tests refuse an `ok` reply that lacks a required field. `tests/test_reply_models.py` refuses
a promised field whose condition the sentence does not say.

A change to a tool's arguments, reply model or description changes its reference page.
`tests/test_reference_pages.py` then fails, naming the tool, the page and the line. Rewrite the
pages from the code:

```sh
uv run python -m scry_core.reference scry_mame.server:REFERENCE --write
```

The examples on those pages come only from the transcript of a run against the real emulator.
Each `--mark` spells one of that computer's directories the way the committed examples do:

```sh
uv run python -m scry_core.reference scry_mame.server:REFERENCE --write \
    --examples <transcript.jsonl ...> --mark '/tmp/<the run>=$TMPDIR'
```

- A run that passes deletes its temporary folder, transcript included. Hard-link
  `transcript.jsonl` while it runs, and only one newer than the run's start.
- Mark the temporary root as well as the run's directory, with
  `--mark '<TMPDIR without its trailing slash>=$TMPDIR'`. The server's own temporary folder
  sits directly under `$TMPDIR`.
- Before the commit, search `docs/reference` for `/Users/`, `/var/folders` and `/private/var`.
- `--skip '<regex>'` leaves out the test cases whose call, reply or label match it. Use it when
  a tool's first case ran on a game a stranger cannot have.

A promise in the reference has a test that fails against the defect it guards. The parsers of
MAME's console are tested on text captured from a real MAME, never written by hand. The
captures are under `tests/fixtures/console/`, and `tests/fixtures/README.md` says where each
came from.

### A tool that moves to another page

The reference generator rewrites only the blocks between its markers. The hand-written
paragraphs after a block belong to that tool by position, so a tool moved to another page
leaves them behind.

1. Take the text between the tool's end marker and the next begin marker, at `HEAD`.
2. Remove it from the old page and put it after the same tool's end marker on the new page.
3. Run `tests/test_reference_pages.py` again.

The paragraphs of `REFERENCE.md` that name the group, and the demos' tables of tools, need the
same pass. The group of each tool both servers have is `roster.SHARED_FAMILIES` in scry-core.

## The commit hook

The commit runs scry-core's pre-commit check; `python -m scry_core.hook --help` says what it
looks at. Turn it on once per clone:

```sh
git config core.hooksPath .githooks
```

One of its checks is the share of comments and docstrings in each file's bytes. A change that
only deletes code raises that share and can fail with no comment touched. Cut a clause in the
file it names; never raise the limit.

## Tests against a real emulator

A plain `pytest` starts no emulator. These two scripts do, and both call every tool through the
server:

```sh
uv run python tests/live/live_check.py
timeout 1800 uv run python tests/live/live_matrix.py
```

`live_check.py` runs its checks on games this repository does not carry and on the demos' free
ROMs, with the MAME that `MAME_BINARY` names. A game it needs and does not find makes the run
INVALID, naming what is missing.

`live_matrix.py` tries every tool in every state of the machine, at every edge of its
arguments, and every pair of tools that share state. It prints one line per test case:

- The cases are listed before anything starts, so the count is printed first and a case the run
  never reached shows at the end.
- OK means the reply matches the tool's published contract for that state and input.
- FAIL means it contradicts the contract, raises, or leaves the `session` block disagreeing
  with the machine.
- BLOCKED means the case could not run, with the reason.
- Every call lands whole in a JSONL transcript.

What the scripts read from the environment:

| Variable | What it sets |
|---|---|
| `MAME_BINARY` | the MAME the free ROMs and the V30 games run on, built with every driver |
| `MAME_TEST_ROMS` | the directory of the free ROMs |
| `MAME_LIVE_BENCH` | the folder of the private test games, each with its own MAME where it needs one |
| `LINEUP_MAME_ROMS`, `SPEEDF_MAME_ROMS` | each game demo's ROM set and symbol map |
| `MAME_LIVE_SECTIONS` | the letters of the sections to run; unset, all of them |
| `MAME_LIVE_JOBS` | how many sections run at once, each as its own process; unset, half the CPUs |
| `MAME_BACKGROUND` | `1` opens every window behind, `0` every one in front; unset, each start decides |
| `SCRY_FOCUS_CONTROL` | `1` lets the focus section open a window in front and move a Space |

With a variable unset, the cases that need it are BLOCKED and name it. The tracked test code
names the private games only by a label; a set name MAME publishes may appear.

A few cases depend on the computer:

- The focus section opens and closes the run in the parent process, so its watch spans every
  job. Its start in front and its Space move take your screen and keyboard: they run only with
  `SCRY_FOCUS_CONTROL=1`, on a machine nobody is using.
- The cases that open a window open it as `start` does, on the display they ask for
  ([`start`'s page](docs/reference/session.md#start)).
- Section C's cases that break MAME's table writer run on macOS only: they read the files MAME
  holds open through `lsof`.
- Section Z captures the window as the computer shows it. On Windows that needs the display
  on, because Windows draws no new frame of a window while it is off.
- The cases that move a Space carry the `window` marker and are out of every default run.
  `SCRY_FOCUS_CONTROL=1 uv run pytest -o addopts="" -m 'live and window' tests/live` runs them.

### What a window opened behind promises

A start behind does not come to the front, so the keyboard stays where it was. That is all it
promises: the window is still there to be seen, and the computer carries the load of every
emulator the run starts.

So run the live test script in an account or on a machine nobody is working at, or at an hour
agreed with whoever is. Whether a run took the front is the focus section's verdict, read as
[scry-core's page on these tests](https://github.com/scry-mcp/scry-core/blob/main/docs/live-tests.md#showing-that-a-run-took-nobodys-focus)
says.

### A game controller makes a debug MAME abort

A debug build of MAME aborts at start, on an SDL3 input assert, while a game controller is
connected. Every start of these tests passes an ini that holds `joystickprovider none` as
`inipath`: the tracked `tests/live/fixtures/ini-no-joystick`, or a copy. A start written by
hand passes one too.

### What a run checks about the computer

A run refuses a computer that cannot start MAME, and proves it left none running
(`scry_core.live_host`):

- Before its first start it launches the game once in a form that ends by itself. If that does
  not return, the run is INVALID and starts nothing else.
- Every MAME a session starts is recorded where it is started. One still alive at the end is
  killed and fails the run by name.
- A run that passes removes its temporary folder. Any other keeps it and prints its path.

## Demos

`demos/<name>/demo.py` runs one demo end to end. With `--update-readme` it rewrites the demo's
page from a run where every step passed: the two generated blocks of its README,
`TRANSCRIPT.md`, `screen.png` and `loop.webp`.

- The steps a demo marks with an `ask` are the examples of its page, and of the README for the
  two demos on free ROMs.
- `loop.webp` shows the demo's moments, each cut from a `record` step of the run. ffmpeg
  decodes the recordings and `img2webp` assembles the file; without either on the `PATH` the
  update is refused by name.
- The LineUp demo also writes what the README opens with: its clip, a caption and one step of
  the run as an exchange, all named in its `Lead`.
- A second run gives the same page. `loop.webp` alone may differ in its bytes.

The block of the README that adds the server to each client is scry-core's table of clients:

```sh
uv run python -m scry_core.install scry_mame --write
```

## The description test

A tool's description, its arguments and the server's `instructions` are all a model has to call
the tool from. The description test gives a model only what a client delivers and checks the
calls it makes:

```sh
uv run python -m scry_core.probe mame --servers mcp_probe/servers.py \
    --tasks mcp_probe/tasks --check
uv run python -m scry_core.probe mame --servers mcp_probe/servers.py \
    --tasks mcp_probe/tasks --runs 3
```

- `--check` asks no model. It names a tool or an argument that has no task in
  `mcp_probe/tasks/`, and the commit hook runs it.
- `--runs` asks the `claude` CLI and checks each task over several runs.
  `python -m scry_core.probe --help` says how a failure is told from the model's noise.

A task the model keeps getting wrong is tolerated when the server refuses the wrong call and
says why: report it with its numbers. A client retries on a refusal, and more description text
spends the room the other tools need. Only a wrong call the server accepts with `status: ok`
is a defect.
