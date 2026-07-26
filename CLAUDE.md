# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this is

A benchmarking suite for DataLad-family implementations. Read `README.md` first —
it defines the core model (scenario x fixture x environment -> run record) and the
invariants below exist to protect it.

## Invariants — do not violate these without discussion

1. **A run has exactly one measured phase.** Setup phases are timed and recorded
   separately. If you find yourself wanting to measure two things in one run, that
   is two runs. This is what stops an expensive clone from hiding the `save` it
   prepares.
2. **`run-one` is self-sufficient.** It must not depend on in-process state left by
   a previous run. Every other executor (slurm array, babs, CI) drives `run-one` as
   a subprocess, so anything cached in memory between runs is a portability bug.
3. **Fixture generation is never timed.** Creating fake data is not a DataLad
   operation worth measuring. Cloning it is — that is a scenario.
4. **Every scenario asserts it did real work.** A benchmark that silently measures
   a no-op is worse than no benchmark. New scenarios get a `checks` entry.
5. **Metrics carry reliability, they are not filtered by it.** All metrics are
   recorded and reported. `METRIC_RELIABILITY` in `records.py` says how much to
   trust each one, and is snapshotted into every record. When the measurement
   backend improves, update that map — not the reporting code.
6. **Records are the only interface.** Reporting and analysis read `record.json`
   and nothing else. Changing the record schema means bumping `SCHEMA`.

## Goals

- Accuracy: prefer kernel-truth measurement over sampling and estimation.
- Evenness: runs being compared must experience comparable conditions, or the record must say they didn't.
- STAMPED: self-contained, portable, reproducible execution environments.
- Provenance: a record carries everything needed to interpret it years later, without the host it ran on.

## Measuring honestly

- Vary one axis at a time. A fixture spec that bundles several axes (a
  "BIDS-shaped" shape parameter) cannot attribute cost to a cause. The `Shape`
  dataclass is a generic tree for exactly this reason.
- Wall clock is the trustworthy metric today. duct's RSS/CPU sampling is
  known-unreliable (upstream fix pending) and rated `low`.
- Page cache dominates repeats. Say which state a number came from.
- Report ratios, not absolutes, when comparing across machines.

## Conventions

- Go with the grain of the problem. Do not overfit to a user-ask; push back when necessary.
- Python >= 3.11, stdlib-first. `con-duct` is the only runtime dependency; keep it
  that way unless there is a strong reason.
- Comments explain *why*, especially where a simpler-looking approach was rejected
  (see the fixture-reset rationale in `fixtures.py`).
- `uv` manages the venv and the lockfile. Never `pip install` into system Python.

## Running things

    uv sync                                   # recreate the venv from uv.lock
    uv run ladometer stat --config suite.toml <fixture>
    uv run ladometer run  --config suite.toml
    uv run ladometer report --config suite.toml
    uv run pytest

Fixture builds are cached under `--root` (default `~/.cache/ladometer`) and can take
minutes the first time. Use a separate `--root` for an experiment you do not want
sharing a cache with the default suite.
