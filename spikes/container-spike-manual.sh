#!/bin/bash
# Step 2 of the container spike: prove the environment works containerized.
#
# Deliberately no duct and no cgroup readout yet -- this answers only "does
# datalad run in there and see the fixture", so a failure has exactly one
# possible cause. Measurement is step 3.

export PS4='> '
set -x
set -eu

PRISTINE=/home/austin/.cache/ladometer-scaling/fixtures/pristine-4026ef6dd3f2
WORK=/home/austin/.cache/ladometer-scaling/work/spike-manual

/usr/bin/rm -rf /home/austin/.cache/ladometer-scaling/work/spike-manual
mkdir -p "$WORK/home"

# keep-id puts us in the container as uid 1000, for which the image has no
# passwd entry, so HOME collapses to / and datalad fails writing /.cache.
# Set it explicitly rather than baking a uid into the image -- the uid varies
# per host, which is the whole reason not to bake it. Pointing HOME at the bind
# mount also keeps datalad's config and cache off overlayfs.
HOME_ARGS=(-e HOME=/work/home)

# Phase 1: setup (the clone). Unmeasured, and in its own container so that its
# cgroup high-water mark cannot leak into the measured phase's.
#
# label=disable rather than :z -- :z would recursively relabel the pristine
# fixture's xattrs, and that side effect persists in the shared cache.
# GIT_* identity is passed at run time, mirroring _prepend_path on the host.
podman run --rm --userns=keep-id --security-opt label=disable "${HOME_ARGS[@]}" \
  -v "$PRISTINE":/pristine:ro \
  -v "$WORK":/work:rw \
  -e GIT_AUTHOR_NAME=ladometer -e GIT_AUTHOR_EMAIL=ladometer@example.invalid \
  -e GIT_COMMITTER_NAME=ladometer -e GIT_COMMITTER_EMAIL=ladometer@example.invalid \
  ladometer-base \
  datalad install -r -s /pristine /work/clone

# Phase 2: the measured phase, in a fresh container whose cgroup therefore
# contains nothing but the thing under test. Bare `time` for now.
time podman run --rm --userns=keep-id --security-opt label=disable "${HOME_ARGS[@]}" \
  -v "$WORK":/work:rw \
  ladometer-base \
  sh -c 'cd /work/clone && datalad status -e full'
