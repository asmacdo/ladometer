#!/bin/bash
# Rerun the scaling axes at reps=3 (was reps=1) so every (scenario, fixture)
# has a rep spread -- the gate for WLS weights and honest prediction bands.
#
# Environment deliberately UNPINNED: host git 2.54.0 + git-annex 10.20250630
# are unchanged since the original axis A-F pass, so this rerun varies only
# `reps` against that data. Pinning git-annex (the wheel build) would change
# the annex *build* at the same time as adding reps -- a confound. Pin after,
# as its own before/after-able change.
#
# Conditions are sampled because this is NOT a quiet box (live interactive
# session on it): loadavg every 30s -> conditions log, so a polluted rep is
# detectable afterward instead of assumed clean.
export PS4='> '
set -eu

LOG_DIR="$(cd "$(dirname "$0")" && pwd)"
COND="$LOG_DIR/rerun-axes-conditions.log"
RUNLOG="$LOG_DIR/rerun-axes.log"

echo "=== start $(date -Is) ===" >> "$RUNLOG"
echo "start $(date -Is) loadavg $(cat /proc/loadavg)" >> "$COND"

( while true; do
    echo "$(date -Is) $(cat /proc/loadavg)"
    sleep 30
  done >> "$COND" ) &
SAMPLER=$!
trap 'kill "$SAMPLER" 2>/dev/null' EXIT

cd /home/austin/devel/ladometer
uv run ladometer run \
    --config scaling.toml \
    --root ~/.cache/ladometer-scaling \
    --scenarios status-full status-commit \
    2>&1 | tee -a "$RUNLOG"
STATUS=${PIPESTATUS[0]}

echo "end $(date -Is) loadavg $(cat /proc/loadavg) exit=$STATUS" >> "$COND"
echo "=== end $(date -Is) exit=$STATUS ===" >> "$RUNLOG"
exit "$STATUS"
