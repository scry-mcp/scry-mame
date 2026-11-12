---
paths:
  - "src/scry_mame/lua/**"
  - "src/scry_mame/lua_source.py"
  - "tests/test_lua_*.py"
  - ".luacheckrc"
  - "stylua.toml"
---

# How this server composes and sends its Lua

The Lua the server sends MAME lives in `src/scry_mame/lua/`, rendered by `lua_source.py` and sent
down the console as one line of bounded length. The fleet-wide rule (`~/.claude/rules/lua.md`)
holds; this is what the console and the loader add.

- **A value enters through a slot that is a valid Lua identifier, `__SCRY_<name>__`**, so the file
  parses as it stands, and the loader fills it with a Lua literal of the value's type: a string is
  quoted and escaped, a number is a number, `None` is `nil`. Code the server built goes in as
  `Code`. A line that is only `--- __SCRY_<name>__` is a statement slot for shared statements. A
  slot left unfilled, or a value for no slot, is refused, never rendered as text. A one-line
  expression built from data (a device lookup, a condition) may stay in Python.
- **A value the script prints for a parser goes in as an argument, never spliced into a string
  literal**: `string.format("%s armed frame=%d", __SCRY_mark__, frame)`. A slot inside quotes is
  text the loader cannot type, and a `%` in it breaks the format.
- **luacheck runs on the scripts as they are rendered and sent** (`tests/test_lua_scripts.py`):
  most files are fragments that read the locals of the one they are composed into, so a fragment
  alone reports what it borrows. StyLua owns the layout, so a test that looks for code in the text
  compares it with the whitespace squashed (`tests/lua_text.py`).
- **Whole-line comments only.** `lua_source` drops a line that is only a comment before the
  script is sent, so the file explains itself at no cost; a comment after code on its line travels
  to MAME and spends the console line.
- **No inline linter directive.** A `-- luacheck:` comment is dropped with the other comment lines
  before luacheck sees the rendered script, so every exception lives in `.luacheckrc`, with the
  reason beside it.
- **`---` is the statement slot only**; every comment is `--`. Nothing generates documentation
  from these files, so LDoc's `---` would buy nothing and blur the slot.
- **The prose ceiling is measured**: scry-core's pre-commit judges each `.lua` at a quarter, as it
  judges Python. A fragment that exists to carry one line of code goes into what loads it.
