#!/bin/bash
# Does the container contaminate the cgroup measurement, and by how much?
#
# Four runs, two arms x two allocation sizes. The 0 MB run is the floor: the cost
# of the machinery itself. The 200 MB run proves the chain reports a known
# allocation correctly. So:
#
#   (200MB - 0MB) within an arm  -> is the chain accurate?
#   floor_container - floor_host  -> what does the container cost the measurement?
#
# The second number is the one that decides whether containers belong in the
# measurement path at all.
#
# Caveat: the two arms use different python interpreters (host vs image), so the
# floors differ by interpreter overhead as well as container overhead. That is
# precisely why the floors are measured rather than assumed.

set -eu

U=/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service

alloc_expr() { echo "a = bytearray($1 * 1024 * 1024); del a"; }

read_peak() { echo "$(cat "$1"/memory.peak)"; }

fresh_cgroup() {
  local cg=$U/$1
  rmdir "$cg" 2>/dev/null || true
  mkdir -p "$cg"
  echo "$cg"
}

# --- arm A: containerless. The cgroup is the whole mechanism. -----------------
arm_host() {
  local cg; cg=$(fresh_cgroup "lado-host-$1")
  # Subshell joins the cgroup by writing its own pid, then execs the payload,
  # so the measured process is the only thing ever charged to this cgroup.
  ( echo $BASHPID > "$cg"/cgroup.procs; exec python3 -c "$(alloc_expr "$1")" )
  read_peak "$cg"
}

# --- arm B: containerized, under a parent cgroup we own ----------------------
arm_container() {
  local name=lado-ctr-$1
  local cg; cg=$(fresh_cgroup "$name")
  podman run --rm --cgroup-manager=cgroupfs \
    --cgroup-parent="/user.slice/user-1000.slice/user@1000.service/$name" \
    ladometer-base python3 -c "$(alloc_expr "$1")" >/dev/null
  read_peak "$cg"
}

H0=$(arm_host 0);      H200=$(arm_host 200)
C0=$(arm_container 0); C200=$(arm_container 200)

mb() { echo "scale=1; $1/1048576" | bc; }

printf '\n%-14s %14s %14s %12s\n' arm "floor(0MB)" "200MB" "delta"
printf '%-14s %11s MB %11s MB %9s MB\n' containerless "$(mb "$H0")" "$(mb "$H200")" "$(mb $((H200-H0)))"
printf '%-14s %11s MB %11s MB %9s MB\n' containerized "$(mb "$C0")" "$(mb "$C200")" "$(mb $((C200-C0)))"
printf '\ncontainer floor overhead: %s MB  (expect ~200 MB for both deltas)\n' "$(mb $((C0-H0)))"
