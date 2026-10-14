#!/usr/bin/env bash
# The wiring of `pre-commit.sh`: its one line reaches scry-core's hook, through the real jscpd and
# the real probe check. What the hook decides is tested in scry-core; here the CONTROL (this tree
# passes) and one planted clone (blocked at 1) are what shows the line works.
#
# BOTH RUN ON A COPY of the tree (its tracked and untracked files), so a clone planted here never
# sits in the working tree where another run or a commit would meet it. The copy runs in this
# repository's own environment, unsynced, so nothing is installed and the venv is not re-pointed.
set -euo pipefail
# The real tools, never the hook's seams, whatever the caller's shell exports.
unset PRECOMMIT_JSCPD PRECOMMIT_PROBE

cd "$(dirname "$0")/.." || exit 3
root=$PWD
copy=$(cd "$(mktemp -d)" && pwd -P)
# Under the repository's own directory name: an ignore glob can name it (this tree's do).
tree="$copy/$(basename "$root")"
mkdir "$tree"
trap 'rm -rf "$copy"' EXIT
fails=0

ok() { printf '  OK    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

{ git ls-files -z; git ls-files -z --others --exclude-standard; } | sort -zu \
    | while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done \
    | tar -c --null -T - -f - | tar -x -f - -C "$tree"
git -C "$tree" init -q
hook() { (cd "$tree" && UV_PROJECT_ENVIRONMENT="$root/.venv" UV_NO_SYNC=1 \
          bash .githooks/pre-commit.sh > "$copy/out" 2>&1); }

rc=0; hook || rc=$?
if [ "$rc" -eq 0 ]; then ok "this tree passes (the control)"; else bad "the control gave rc=$rc: $(cat "$copy/out")"; fi
if grep -q "no new duplication" "$copy/out" && grep -q "^   OK " "$copy/out"; then
    ok "and both checks ran"
else
    bad "a check did not run: $(cat "$copy/out")"
fi

# Two copies of one block, longer than jscpd's minimum, in a directory of their own.
mkdir "$tree/tests/planted-clone"
for f in a b; do
    {
        echo "def planted_$f(rows, cols, step):"
        echo "    total = 0"
        for k in 1 2 3 4 5 6; do
            echo "    for i in range(rows):"
            echo "        for j in range(cols):"
            echo "            total += (i * j + $k) % (step + $k) - (i + j) * $k"
        done
        echo "    return total"
    } > "$tree/tests/planted-clone/clone_$f.py"
done
rc=0; hook || rc=$?
if [ "$rc" -eq 1 ]; then ok "a planted clone blocks at rc=1"; else bad "a planted clone gave rc=$rc: $(cat "$copy/out")"; fi
if grep -q "new clone" "$copy/out"; then ok "and says so"; else bad "the clone is not named"; fi

if [ "$fails" -eq 0 ]; then
    echo "==> GREEN: 0 failures"
else
    echo "==> RED: $fails failure(s)" >&2
    exit 1
fi
