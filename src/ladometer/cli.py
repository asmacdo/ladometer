"""Command line interface.

`run-one` is the primitive: exactly one measured run, one record. `run` is a
convenience that invokes the primitive across a matrix locally. Any other
executor (a slurm array, babs) is expected to drive `run-one` the same way, so
keep it self-sufficient -- no shared in-process state between runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import fixtures
from .execute import run_one
from .specs import Suite

DEFAULT_ROOT = Path.home() / ".cache" / "ladometer"


def _roots(args) -> dict:
    root = Path(args.root).expanduser()
    return {
        "cache_root": root / "fixtures",
        "work_root": root / "work",
        "env_root": root / "envs",
        "out_root": Path(args.out).expanduser() if args.out else root / "runs",
    }


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default="suite.toml", help="suite definition")
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="cache/work root")
    p.add_argument("--out", default=None, help="where to write run records")


def cmd_stat(args) -> int:
    suite = Suite.load(Path(args.config))
    spec = suite.fixtures[args.fixture]
    roots = _roots(args)
    if spec.kind == "generated":
        path = fixtures.ensure_pristine(spec.shape, roots["cache_root"])
    else:
        path = spec.path
    print(json.dumps({"path": str(path), **fixtures.stat_hierarchy(path)}, indent=2))
    return 0


def cmd_run_one(args) -> int:
    suite = Suite.load(Path(args.config))
    record = run_one(
        suite.scenarios[args.scenario],
        suite.fixtures[args.fixture],
        suite.environments[args.environment],
        args.rep,
        warmup=args.warmup,
        **_roots(args),
    )
    print(record.to_json())
    return 0 if record.validity.get("ok") else 1


def cmd_run(args) -> int:
    suite = Suite.load(Path(args.config))
    scenarios = args.scenarios or list(suite.scenarios)
    envs = args.environments or list(suite.environments)
    fixtures_ = args.fixtures or list(suite.fixtures)
    roots = _roots(args)

    failures = 0
    for fx in fixtures_:
        for ev in envs:
            for sc in scenarios:
                for rep in range(args.reps or suite.reps):
                    rec = run_one(
                        suite.scenarios[sc],
                        suite.fixtures[fx],
                        suite.environments[ev],
                        rep,
                        warmup=args.warmup,
                        **roots,
                    )
                    ok = rec.validity.get("ok")
                    wall = rec.measurement.wall_clock_sec
                    flag = "ok  " if ok else "FAIL"
                    timing = f"{wall:8.2f}s" if wall is not None else "       --"
                    print(
                        f"{flag} {sc:16s} {fx:16s} {ev:14s} rep{rep} {timing}",
                        flush=True,
                    )
                    failures += 0 if ok else 1
    print(f"\nrecords in {roots['out_root']}")
    return 1 if failures else 0


def cmd_report(args) -> int:
    """Summarise recorded runs.

    Reads records only -- never re-runs anything -- so a report is cheap and
    reproducible. Metrics are printed alongside their reliability rating rather
    than silently, so a reader knows which columns to lean on.
    """
    out_root = _roots(args)["out_root"]
    records = []
    for path in sorted(out_root.glob("*/record.json")):
        try:
            records.append(json.loads(path.read_text()))
        except Exception:
            continue
    if not records:
        print(f"no records under {out_root}")
        return 1

    rel = records[-1].get("metric_reliability", {})
    print(f"{len(records)} records in {out_root}")
    print(f"metric reliability: {rel}\n")

    rows = {}
    for r in records:
        key = (r["scenario"]["name"], r["fixture"]["name"], r["environment"]["name"])
        wall = r["measurement"].get("wall_clock_sec")
        if wall is not None:
            rows.setdefault(key, []).append(wall)

    hdr = f"{'scenario':16s} {'fixture':16s} {'environment':14s} {'n':>2s} {'wall_med':>9s} {'files':>8s} {'repos':>6s}"
    print(hdr)
    print("-" * len(hdr))
    stats = {
        (r["scenario"]["name"], r["fixture"]["name"], r["environment"]["name"]): (
            r["fixture"].get("stats") or {}
        )
        for r in records
    }
    for key in sorted(rows):
        walls = sorted(rows[key])
        med = walls[len(walls) // 2]
        st = stats.get(key, {})
        print(
            f"{key[0]:16s} {key[1]:16s} {key[2]:14s} {len(walls):2d} "
            f"{med:9.2f} {st.get('tracked_files', '?'):>8} {st.get('repos', '?'):>6}"
        )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ladometer", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stat", help="describe a fixture's shape")
    _add_common(p)
    p.add_argument("fixture")
    p.set_defaults(func=cmd_stat)

    p = sub.add_parser("run-one", help="execute exactly one measured run")
    _add_common(p)
    p.add_argument("--scenario", required=True)
    p.add_argument("--fixture", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--rep", type=int, default=0)
    p.add_argument("--warmup", action="store_true")
    p.set_defaults(func=cmd_run_one)

    p = sub.add_parser("run", help="run a matrix locally")
    _add_common(p)
    p.add_argument("--scenarios", nargs="*")
    p.add_argument("--fixtures", nargs="*")
    p.add_argument("--environments", nargs="*")
    p.add_argument("--reps", type=int)
    p.add_argument("--warmup", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="summarise recorded runs")
    _add_common(p)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
