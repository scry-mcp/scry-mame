#!/usr/bin/env bash
# The pre-commit of this repository is scry-core's: `python -m scry_core.hook --help` says what it
# checks and why. This is the one line that runs it in the repository's own environment; the
# `pre-commit` beside it is a symlink so git finds the name it expects. Enable once per clone:
#     git config core.hooksPath .githooks
set -euo pipefail
exec uv run python -m scry_core.hook "$@"
