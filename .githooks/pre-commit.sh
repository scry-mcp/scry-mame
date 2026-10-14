#!/usr/bin/env bash
# pre-commit.sh -- the pre-commit hook of this repository. `pre-commit` beside it is a
# symlink, so git finds the name it expects while the program keeps the extension that
# makes shellcheck see it. Enable once per clone:
#     git config core.hooksPath .githooks
#
# IT RUNS TWO CHECKS, and that is the whole design rather than a stub. The linters and the
# suite are the battery, run directly and read by whoever is working; what belongs HERE is
# what nobody would otherwise run, because its answer is about the tree as a whole and not
# about the file in front of you: new duplication, and a probe task set that no longer fits
# the MCP servers. Skipping is git's own `--no-verify`.
#
# 0 clean / 1 new duplication or an uncovered tool / 3 INVALID (it examined nothing). INVALID
# is never folded into green.
set -euo pipefail

# The seams: `PRECOMMIT_JSCPD` and `PRECOMMIT_PROBE` name the programs to run in place of
# `jscpd` and of the probe's check, so the test beside this file can hand each one that fails
# on demand and one that examined nothing.
jscpd_cmd="${PRECOMMIT_JSCPD:-jscpd}"

root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "pre-commit: INVALID -- git does not say where the repo root is." >&2
    exit 3
}
cd "$root" || exit 3

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

echo "== jscpd (new duplication against the baseline)"
# THE BASELINE HAS TO BE THERE, and its absence is said in its own words. Without this the
# tool refuses, no report is written, and the hook reports "wrote no report", which sends
# whoever reads it hunting for a broken jscpd instead of a missing file. It is tracked, so
# the case that reaches here is a tree where somebody removed it, or a brand-new bucket.
if [ ! -f .jscpd-baseline.json ]; then
    echo "pre-commit: INVALID -- .jscpd-baseline.json is missing, so there is nothing to" >&2
    echo "  judge NEW duplication against. It is tracked; restore it, or create one with:" >&2
    echo "      jscpd . --baseline .jscpd-baseline.json --update-baseline" >&2
    exit 3
fi
# THE DECLARED HALF, not the pretty one: the console table is aligned columns a reader
# scans, and picking a number out of it BY POSITION cannot say which metric it landed on.
# The JSON names its fields, so a shape that moves is visible instead of misread.
rc=0
"$jscpd_cmd" . --baseline .jscpd-baseline.json --fail-on-new-clones \
    --reporters json --output "$scratch" > "$scratch/stdout" 2>&1 || rc=$?

report="$scratch/jscpd-report.json"
if [ ! -f "$report" ]; then
    echo "pre-commit: INVALID -- jscpd wrote no report (rc=$rc):" >&2
    cat "$scratch/stdout" >&2
    exit 3
fi

# A RUN THAT EXAMINED NOTHING IS NOT A PASS. jscpd exits 0 having lexed zero files when
# pointed at a language it cannot read, and a zero there would read as "no duplication".
read -r sources new dup < <(python3 -c '
import json, sys
t = json.load(open(sys.argv[1]))["statistics"]["total"]
print(t.get("sources", 0), t.get("newClones", 0), t.get("duplicatedLines", "?"))
' "$report") || {
    echo "pre-commit: INVALID -- the report could not be read." >&2
    exit 3
}

if [ "$sources" -eq 0 ]; then
    echo "pre-commit: INVALID -- jscpd analysed 0 files, so this is not a verdict." >&2
    exit 3
fi

if [ "$rc" -ne 0 ] || [ "$new" -gt 0 ]; then
    echo "" >&2
    cat "$scratch/stdout" >&2
    echo "pre-commit: BLOCKED -- $new new clone(s) over a baseline of accepted duplication," >&2
    echo "  in $sources files, $dup duplicated lines (rc=$rc)." >&2
    # The fingerprint hashes the clone's content, not its position: a block that only moved
    # keeps its key, but one that SHRANK or split under an edit inside it gets a new one, so
    # a change that removed duplication can read as new here. Only the totals tell them apart.
    echo "  A clone that shrank or split under your edit is counted as new even when the" >&2
    echo "  duplication went DOWN. Compare the duplicated lines with HEAD's first:" >&2
    cat >&2 <<'RECIPE'
      d=$(mktemp -d); git archive HEAD | tar -x -C "$d"
      (cd "$d" && jscpd . --reporters json --output r) # statistics.total.duplicatedLines
RECIPE
    echo "  Consolidate it, or accept it deliberately with:" >&2
    echo "      jscpd . --baseline .jscpd-baseline.json --update-baseline" >&2
    echo "  and say in the commit message WHY that site stays duplicated." >&2
    exit 1
fi

echo "   $sources files, no new duplication"

echo "== mcp_probe (the probe's tasks still fit the MCP servers)"
# THE CHECK ONLY, which asks no model: free, offline, the same answer every time. The model
# run is not a gate, because at a cheap model a miss moves between tools from run to run.
rc=0
if [ -n "${PRECOMMIT_PROBE:-}" ]; then
    "$PRECOMMIT_PROBE" > "$scratch/probe" 2>&1 || rc=$?
else
    uv run python -m scry_core.probe all --check --servers mcp_probe/servers.py \
        --tasks mcp_probe/tasks > "$scratch/probe" 2>&1 || rc=$?
fi
case $rc in
    0)
        covered=$(grep -c '^OK ' "$scratch/probe" || true)
        if [ "$covered" -eq 0 ]; then
            echo "pre-commit: INVALID -- the probe check examined no server, so this is not" >&2
            echo "  a verdict:" >&2
            cat "$scratch/probe" >&2
            exit 3
        fi
        sed 's/^/   /' "$scratch/probe"
        ;;
    1)
        # A 1 is a refusal only when the check SAYS one: a probe that died on import exits 1
        # too, and "write the tasks" would be the wrong remedy for it.
        if ! grep -q '^REFUSED ' "$scratch/probe"; then
            echo "pre-commit: INVALID -- the probe check exited 1 naming no refusal:" >&2
            cat "$scratch/probe" >&2
            exit 3
        fi
        cat "$scratch/probe" >&2
        echo "pre-commit: BLOCKED -- a probe task is missing or wrong (above). Write the tasks" >&2
        echo "  in mcp_probe/tasks/<server>.json, then measure the server with:" >&2
        echo "      uv run python -m scry_core.probe <server> --servers mcp_probe/servers.py \\" >&2
        echo "          --tasks mcp_probe/tasks --runs 3" >&2
        exit 1
        ;;
    *)
        echo "pre-commit: INVALID -- the probe check exited $rc:" >&2
        cat "$scratch/probe" >&2
        exit 3
        ;;
esac
