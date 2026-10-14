#!/usr/bin/env bash
# The cases of `pre-commit.sh`. Every one of them goes through the SEAM
# (`PRECOMMIT_JSCPD`), because the three outcomes that matter cannot be produced by asking
# the real jscpd nicely: a tool that examined nothing, a tool that found new duplication,
# and a tool that wrote no report at all. The green case is the CONTROL: without it, a hook
# that blocked everything would satisfy all three reds.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 3
HOOK="$PWD/.githooks/pre-commit.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fails=0

ok() { printf '  OK    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

# The double writes the report jscpd's JSON reporter would write, into the --output it is
# given, with the numbers this case needs. It is the SHAPE of the real one: `statistics`
# with a `total` carrying `sources`, `newClones` and `duplicatedLines`, read by name.
make_fake() {
    cat > "$T/fake-jscpd" <<FAKE
#!/usr/bin/env bash
out=""
prev=""
for a in "\$@"; do
    [ "\$prev" = "--output" ] && out="\$a"
    prev="\$a"
done
[ -n "\$out" ] && mkdir -p "\$out" && cat > "\$out/jscpd-report.json" <<JSON
{"duplicates": [], "statistics": {"total": {"sources": $1, "newClones": $2, "duplicatedLines": 640}}}
JSON
echo "fake jscpd: sources=$1 newClones=$2"
exit $3
FAKE
    chmod +x "$T/fake-jscpd"
}

# The probe check's double prints what the real one prints (`OK <server>: ...` or
# `REFUSED <problem>`) and exits with the code this case needs; clean by default, so the jscpd
# cases below judge jscpd alone.
make_probe() {
    printf '#!/usr/bin/env bash\nprintf "%%s\\n" %s\nexit %s\n' "$1" "$2" > "$T/fake-probe"
    chmod +x "$T/fake-probe"
}
make_probe "'OK mame: 56 tasks cover 45 tools'" 0

run() { PRECOMMIT_JSCPD="$T/fake-jscpd" PRECOMMIT_PROBE="$T/fake-probe" bash "$HOOK" > "$T/out" 2>&1; }

# --- the CONTROL: a clean run must pass, or every red below proves nothing -----
make_fake 196 0 0
if run; then ok "a clean run passes (the control)"; else bad "the control went red: $(cat "$T/out")"; fi

# --- new duplication BLOCKS, at 1 ---------------------------------------------
make_fake 196 3 1
rc=0; run || rc=$?
if [ "$rc" -eq 1 ]; then ok "new duplication blocks at rc=1"; else bad "new duplication gave rc=$rc"; fi
if grep -q "3 new clone" "$T/out"; then ok "and it says HOW MANY"; else bad "the count is not named"; fi
if grep -q "update-baseline" "$T/out"; then ok "and how to accept it deliberately"; else bad "no remedy named"; fi
if grep -q "640 duplicated lines" "$T/out"; then ok "and the duplicated lines to compare"; else bad "the total is not named"; fi
if grep -q "shrank or split" "$T/out"; then ok "and the re-keyed clone that is not new"; else bad "the shrink case is not named"; fi

# --- A ZERO THAT IS NOT A VERDICT: examined nothing is INVALID, never green ----
# The tool exits 0, which is exactly how this failure disguises itself.
make_fake 0 0 0
rc=0; run || rc=$?
if [ "$rc" -eq 3 ]; then ok "0 files analysed is INVALID (rc=3), not a pass"; else bad "0 files gave rc=$rc"; fi
if grep -q "not a verdict" "$T/out"; then ok "and says so in words"; else bad "the INVALID is not explained"; fi

# --- a MISSING BASELINE says so, instead of blaming the tool ------------------
# Its own case, because the diagnostic is the whole point: without it this arrives as
# "jscpd wrote no report", which sends a reader hunting for a broken tool.
make_fake 196 0 0
mv .jscpd-baseline.json "$T/baseline.kept"
rc=0; run || rc=$?
mv "$T/baseline.kept" .jscpd-baseline.json
if [ "$rc" -eq 3 ]; then ok "a missing baseline is INVALID (rc=3)"; else bad "missing baseline gave rc=$rc"; fi
if grep -q "baseline.json is missing" "$T/out"; then ok "and names the file, not the tool"; else bad "the missing file is not named"; fi

# --- no report written at all is INVALID too, not a pass ----------------------
cat > "$T/fake-jscpd" <<'NOREPORT'
#!/usr/bin/env bash
echo "fake jscpd: died before writing anything" >&2
exit 0
NOREPORT
chmod +x "$T/fake-jscpd"
rc=0; run || rc=$?
if [ "$rc" -eq 3 ]; then ok "no report is INVALID (rc=3), even at exit 0"; else bad "no report gave rc=$rc"; fi

# --- the probe check: an uncovered tool BLOCKS, a broken check is INVALID ----
make_fake 196 0 0
make_probe "'REFUSED no task on mame frame_grab'" 1
rc=0; run || rc=$?
if [ "$rc" -eq 1 ]; then ok "an uncovered tool blocks at rc=1"; else bad "an uncovered tool gave rc=$rc"; fi
if grep -q "no task on mame frame_grab" "$T/out"; then ok "and it names the hole"; else bad "the hole is not named"; fi
if grep -q "scry_core.probe <server> --servers" "$T/out"; then ok "and how to measure after"; else bad "no remedy named"; fi

make_probe "'ModuleNotFoundError: No module named mame_args'" 1
rc=0; run || rc=$?
if [ "$rc" -eq 3 ]; then ok "a 1 naming no refusal is INVALID (rc=3)"; else bad "a bare 1 gave rc=$rc"; fi
if grep -q "naming no refusal" "$T/out"; then ok "and says so, not 'write the tasks'"; else bad "a bare 1 got the task remedy"; fi

make_probe "'INVALID mcp_probe/tasks/mame.json: bad JSON'" 3
rc=0; run || rc=$?
if [ "$rc" -eq 3 ]; then ok "a check that could not examine is INVALID (rc=3)"; else bad "check rc=3 gave rc=$rc"; fi

make_probe "'probe: error: unrecognized arguments'" 2
rc=0; run || rc=$?
if [ "$rc" -eq 3 ]; then ok "a check that refused its own call is INVALID (rc=3)"; else bad "check rc=2 gave rc=$rc"; fi

# A zero with nothing examined is the disguise again: exit 0 and not one server covered.
make_probe "''" 0
rc=0; run || rc=$?
if [ "$rc" -eq 3 ]; then ok "a check that examined no server is INVALID (rc=3)"; else bad "an empty check gave rc=$rc"; fi
make_probe "'OK mame: 56 tasks cover 45 tools'" 0

if [ "$fails" -eq 0 ]; then
    echo "==> GREEN: 0 failures"
else
    echo "==> RED: $fails failure(s)" >&2
    exit 1
fi
