# Ladometer

A benchmarking suite for DataLad-family implementations.

**Status: early skeleton.** Built as a learning exercise. Not affiliated with the DataLad project (yet).

## Why

DataLad core has an [asv](https://asv.readthedocs.io) suite that runs per-PR as a
regression gate. It answers "did this commit make *this package* slower?" — every
benchmark must be cheap enough to run twice on a GitHub runner.

Ladometer answers a different question: **how do different implementations compare on
the same real workload?** That means:

- comparing across *packages*, not commits: `datalad` vs `datalad`+`datalad-next` vs
  [`git-lad`](https://hub.datalad.org/datalad/git-lad)/[`datalad-core`](https://hub.datalad.org/datalad/datalad-core),
  and across git-annex versions
- benchmarks that are allowed to take minutes, because that is what the interesting
  workloads actually cost
- separable scenarios with explicit fixtures, rather than measurements crammed into
  existing tests to amortize expensive setup

## Core model

A single measurement is one point in a matrix:

    scenario x fixture x environment x host  ->  run record

- **fixture** — a dataset in a known state (shape, file counts, clean/dirty)
- **environment** — a resolved set of installed packages (datalad, extensions, git-annex)
- **scenario** — a command to measure, plus a validity check that it did real work
- **run record** — one JSON object, the unit of output

**One run is one hermetic process invocation.** `ladometer run-one` executes exactly one
(scenario, fixture, environment, rep) and writes exactly one record. Everything else —
running a matrix locally, fanning out over a slurm array, driving it through babs — is
just a way of invoking `run-one` many times. That is the property that keeps the suite
portable across executors, so it is the property to protect.

Measurement is delegated to [con-duct](https://github.com/con/duct), which wraps the
command and records wall clock plus resource sampling.

## Caveats to keep honest

- **Metrics carry a reliability annotation.** All metrics are recorded, reported, and
  compared — but each one travels with a reliability rating (`METRIC_RELIABILITY`),
  snapshotted into every record. Wall clock is `high`. duct's RSS and CPU sampling is
  `low` today (upstream fix pending). Reliability is a property of the measurement
  backend, not of the metric's usefulness — so when duct improves, the same records and
  the same reporting code simply become more trustworthy, with one map to update.
- Page cache dominates repeated runs. Every record carries a `cache_state` field; a
  warm number and a cold number are different measurements, not noise.
- On a shared machine, other load is invisible to the record. Prefer exclusive
  allocation when the numbers matter.

## Usage

    ladometer stat   <fixture>                    # describe a fixture's shape
    ladometer run-one --scenario S --fixture F --environment E --rep N
    ladometer run    --config suite.toml          # local executor over the matrix
