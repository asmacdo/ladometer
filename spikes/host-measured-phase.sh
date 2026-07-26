#!/bin/bash
# First real datalad measurement through the cgroup chain, containerless.
#
# status-full on f-git-400, to be compared against the bare axis-F number for the
# same fixture (8.80 / 8.45 s, mean 8.63 s -- those were duct-wrapped).
#
# The setup clone deliberately runs in the shell's own cgroup, NOT the measurement
# one: memory.peak is a max-since-creation, so anything that ever ran in the
# measurement cgroup would be baked into the number permanently.
#
# Environment is the same venv axis F used, so the comparison differs in the
# measurement method and nothing else.

export PS4='> '
set -x
set -eu

U=/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service
BIN=/home/austin/.cache/ladometer-scaling/envs/datalad-1_6_1/bin
PRISTINE=/home/austin/.cache/ladometer-scaling/fixtures/pristine-4026ef6dd3f2
WORK=/home/austin/.cache/ladometer-scaling/work/spike-host

export PATH="$BIN:$PATH"
export GIT_AUTHOR_NAME=ladometer GIT_AUTHOR_EMAIL=ladometer@example.invalid
export GIT_COMMITTER_NAME=ladometer GIT_COMMITTER_EMAIL=ladometer@example.invalid

/usr/bin/rm -rf /home/austin/.cache/ladometer-scaling/work/spike-host
mkdir -p "$WORK"

datalad install -r -s "$PRISTINE" "$WORK/clone" >/dev/null

set +x

# status is non-mutating, so reps need no re-clone -- but rep 2 is therefore
# reading a warmer page cache than rep 1. Recorded, not hidden.
for rep in 1 2; do
  CG=$U/lado-measure-$rep
  rmdir "$CG" 2>/dev/null || true
  mkdir -p "$CG"

  START=$(date +%s.%N)
  # The subshell joins the cgroup by writing its own pid, then becomes datalad,
  # so datalad and every git subprocess it spawns are charged here and nothing else is.
  ( echo $BASHPID > "$CG"/cgroup.procs; cd "$WORK/clone"; exec datalad status -e full ) >/dev/null
  END=$(date +%s.%N)

  echo "=== rep $rep ==="
  printf 'wall        : %.2f s\n' "$(echo "$END - $START" | bc)"
  printf 'memory.peak : %.1f MB\n' "$(echo "scale=1; $(cat "$CG"/memory.peak)/1048576" | bc)"
  printf 'cpu (usage) : %.2f s\n' "$(echo "scale=2; $(awk '/^usage_usec/{print $2}' "$CG"/cpu.stat)/1000000" | bc)"
  echo   "pids.peak   : $(cat "$CG"/pids.peak)"
  echo   "io.stat     : $(cat "$CG"/io.stat | head -3)"
done
