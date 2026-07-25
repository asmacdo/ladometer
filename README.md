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

## Quick start

Requires [uv](https://docs.astral.sh/uv) and git-annex.

```
git clone <this repo> && cd ladometer
uv sync                       # recreate the venv exactly, from uv.lock
uv run pytest                 # fast tests, no dataset builds
uv run ladometer stat a-files-100 --config scaling.toml
```

The first `stat` or `run` against a fixture **builds** it, which takes seconds to
minutes depending on shape. Builds are cached under `--root` (default
`~/.cache/ladometer`) and keyed by a digest of the shape, so changing a shape makes
a new cache entry rather than silently reusing a mismatched one.

## Usage

```
ladometer stat <fixture>            # build if needed, then describe actual shape
ladometer run-one --scenario S --fixture F --environment E --rep N
ladometer run                       # local executor over the whole matrix
ladometer report                    # summarise recorded runs
```

All commands take `--config` (default `suite.toml`), `--root` (cache/work/envs), and
`--out` (where records land).

Two suites ship with the repo:

- `suite.toml` — the standing benchmark matrix
- `scaling.toml` — an experiment isolating what drives dirty-check cost, varying one
  axis at a time (file count, dataset count, nesting depth, file size, annex-vs-git)

Use a separate `--root` per experiment to keep fixture caches from mingling:

```
uv run ladometer run --config scaling.toml --root ~/.cache/ladometer-scaling \
    --scenarios status-full status-commit --reps 1
uv run ladometer report --config scaling.toml --root ~/.cache/ladometer-scaling
```

## Adding a scenario

Add a table to a suite file. `command` is the one measured thing; `setup` is
everything needed beforehand, timed separately.

```toml
[scenario.my-thing]
description = "What this measures and why it is interesting."
setup = [["{datalad}", "install", "-r", "-s", "{pristine}", "{work}"]]
command = ["{datalad}", "status", "-e", "full"]
mutates = false
checks = ["exit_zero"]
```

Placeholders: `{datalad}` (the environment's executable), `{pristine}` (cached
fixture build), `{work}` (this run's working copy), `{work_root}`.
