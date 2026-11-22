# scry-mame

Context for a coding assistant working on this repository. The public documentation starts at
`README.md`; this file says what the repository is, how to check a change, and where its rules
live.

## What this repository is

An MCP server that drives a machine emulated in MAME through the emulator's debugger and its Lua
console: it stops, reads and writes the machine, captures the screen and replays sequences of
steps. It is built on scry-core, the shared package, pinned by a git tag in `pyproject.toml`.
The tools' contracts are in `REFERENCE.md` and `docs/reference/`, generated from the server's
registry; `CONTRIBUTING.md` says where the code lives and how a tool is changed.

## Checking a change

```sh
uv run ruff check .
uv run mypy --strict .
uv run mypy --strict --platform win32 .
uv run pytest -q
```

The commit hook is scry-core's (`git config core.hooksPath .githooks` once per clone), and
`uv run python -m scry_core.hook` runs it by hand. Tests against a real emulator are opt-in:
`CONTRIBUTING.md`, *Tests against a real emulator*.

## How work is done here

- English everywhere: code, comments, documents, commit messages.
- Conventional Commits; the body says why.
- A new test is seen failing first, by breaking the line it covers.
- No new check, hook or CI step is added without the maintainers asking for it.

## Rules

Path-scoped rules live in `.claude/rules/` and load when a file they govern is opened.
