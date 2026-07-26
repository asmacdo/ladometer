# spikes/ — one-off evidence, not the suite

Throwaway scripts and raw logs behind design decisions, kept so the decisions
stay auditable. Nothing here is part of the final design: each script's job is
meant to be absorbed into the suite proper (a calibration path emitting run
records, conditions capture inside `run_one`), and once that happens the script
here is history, not an interface. Do not build on these.

- `cgroup-arms.sh` — two arms (containerless / containerized) x two known
  allocations (0 / 200 MB), reading `memory.peak` from a cgroup the script
  owns. The run that calibrated the collector (~0.5% against ground truth) and
  demoted containers from the measurement path.
- `host-measured-phase.sh` — first real datalad workload (`status -e full` on
  an all-git fixture) measured through the cgroup chain, containerless; the
  cross-check against the duct-based instrument (~3% agreement).
- `container-spike-manual.sh` — the containerized `status-full` run; where the
  SELinux labeling and `--userns=keep-id` HOME findings came from.
- `rerun-axes.sh` — the scaling-axes rerun at `reps = 3`, with load average
  sampled to a conditions log every 30 s (`rerun-axes.log`,
  `rerun-axes-conditions.log`).
- `scaling.log`, `axisf.log`, `verify.log` — raw console output of the
  original scaling-axis passes (`reps = 1`, axis F at 2 manual reps). The
  authoritative data is the run records; these are the contemporaneous
  transcripts.
