"""Executing one run.

The central rule: **a run has exactly one measured phase.** Everything a
scenario needs beforehand happens in setup phases, which are timed and recorded
but never folded into the headline number. That is what lets an expensive
recursive clone precede a `save` measurement without hiding it.

The same command can play either role. `datalad install -r` is the measured
phase of the `clone-recursive` scenario and a setup phase of the `save-r-clean`
scenario -- one definition, two roles. Adding a costly setup step therefore
cannot silently change what a scenario reports; it can only add a separately
visible setup timing.

Fixture *generation* is a third thing again: cached, shared across runs, and
never timed at all. Generating fake data is not a DataLad operation worth
measuring; cloning it is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import environments, fixtures
from .records import (
    Measurement,
    RunRecord,
    describe_filesystem,
    describe_host,
    utcnow,
)
from .specs import EnvironmentSpec, FixtureSpec, ScenarioSpec


@dataclass
class Phase:
    name: str
    command: list[str]
    cwd: Path
    measured: bool


def _expand(tokens, mapping: dict) -> list[str]:
    return [str(t).format(**mapping) for t in tokens]


def _prepend_path(bindir: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    # Keep runs from picking up the operator's config.
    env.setdefault("GIT_AUTHOR_NAME", "ladometer")
    env.setdefault("GIT_AUTHOR_EMAIL", "ladometer@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "ladometer")
    env.setdefault("GIT_COMMITTER_EMAIL", "ladometer@example.invalid")
    return env


def _run_plain(phase: Phase, env: dict) -> dict:
    """Run an unmeasured (setup) phase, recording coarse timing only."""
    t0 = time.monotonic()
    proc = subprocess.run(
        phase.command, cwd=phase.cwd, env=env, capture_output=True, text=True
    )
    return {
        "name": phase.name,
        "command": phase.command,
        "elapsed_sec": time.monotonic() - t0,
        "exit_code": proc.returncode,
        "stderr_tail": proc.stderr[-2000:] if proc.returncode else "",
    }


def _run_measured(phase: Phase, env: dict, duct: Path, outdir: Path) -> tuple[dict, str]:
    """Run the measured phase under duct. Returns (duct info.json, prefix)."""
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = str(outdir / "duct_")
    subprocess.run(
        [
            str(duct),
            "-p",
            prefix,
            "--sample-interval",
            "0.5",
            "--report-interval",
            "2.0",
            "-q",
            "--",
            *phase.command,
        ],
        cwd=phase.cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    info_path = Path(prefix + "info.json")
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    return info, prefix


def _check(name: str, info: dict, phase: Phase) -> dict:
    """Validity checks.

    A benchmark that silently measures a no-op is worse than no benchmark, so
    every scenario asserts it did real work.
    """
    summary = info.get("execution_summary", {})
    if name == "exit_zero":
        code = summary.get("exit_code")
        return {"check": name, "ok": code == 0, "detail": f"exit_code={code}"}
    if name == "path_exists":
        ok = phase.cwd.exists()
        return {"check": name, "ok": ok, "detail": str(phase.cwd)}
    return {"check": name, "ok": None, "detail": "unknown check"}


def run_one(
    scenario: ScenarioSpec,
    fixture: FixtureSpec,
    environment: EnvironmentSpec,
    rep: int,
    *,
    cache_root: Path,
    work_root: Path,
    env_root: Path,
    out_root: Path,
    warmup: bool = False,
) -> RunRecord:
    """Execute exactly one (scenario, fixture, environment, rep) and record it."""
    run_id = f"{scenario.name}--{fixture.name}--{environment.name}--r{rep}--{uuid.uuid4().hex[:8]}"
    outdir = out_root / run_id

    bindir = environments.ensure(environment, env_root)
    env = _prepend_path(bindir)
    datalad = str(bindir / "datalad")

    # --- fixture preparation: cached, shared, never timed -------------------
    if fixture.kind == "generated":
        pristine = fixtures.ensure_pristine(fixture.shape, cache_root, datalad=datalad)
        fixture_prov = {
            "kind": "generated",
            "shape": fixture.shape.__dict__,
            "shape_digest": fixture.shape.digest(),
            "pristine": str(pristine),
        }
    else:
        pristine = fixture.path
        fixture_prov = {"kind": "existing", "path": str(pristine)}

    work = work_root / run_id
    if work.exists():
        shutil.rmtree(work)
    work_root.mkdir(parents=True, exist_ok=True)

    mapping = {
        "pristine": str(pristine),
        "work": str(work),
        "work_root": str(work_root),
        "datalad": datalad,
    }

    # --- phases -------------------------------------------------------------
    setup_phases = [
        Phase(
            name=f"setup{i}",
            command=_expand(cmd, mapping),
            cwd=work_root,
            measured=False,
        )
        for i, cmd in enumerate(scenario.setup)
    ]
    measured = Phase(
        name="measure",
        command=_expand(scenario.command, mapping),
        cwd=Path(scenario.cwd.format(**mapping)),
        measured=True,
    )

    setup_results = [_run_plain(p, env) for p in setup_phases]

    if warmup:
        # A discarded pass, so the measured run is unambiguously warm-cache.
        # Only meaningful for non-mutating scenarios; the CLI enforces that.
        _run_plain(measured, env)

    info, prefix = _run_measured(measured, env, bindir / "duct", outdir)

    record = RunRecord(
        run_id=run_id,
        started_at=utcnow(),
        scenario={
            "name": scenario.name,
            "description": scenario.description,
            "command": measured.command,
            "setup": [p.command for p in setup_phases],
            "mutates": scenario.mutates,
        },
        fixture=dict(
            fixture_prov,
            name=fixture.name,
            stats=fixtures.stat_hierarchy(work) if work.exists() else None,
            filesystem=describe_filesystem(work if work.exists() else work_root),
        ),
        environment=dict(environments.describe(bindir), name=environment.name),
        host=describe_host(),
        rep=rep,
        cache_state="warm" if warmup else "unknown",
        command=measured.command,
        measurement=Measurement.from_duct_info(info),
        measurement_backend={
            "tool": "con-duct",
            "version": info.get("duct_version"),
            "schema_version": info.get("schema_version"),
        },
        validity={
            "checks": [_check(c, info, measured) for c in scenario.checks],
            "setup": setup_results,
        },
        duct_prefix=prefix,
    )
    record.validity["ok"] = all(
        c["ok"] is not False for c in record.validity["checks"]
    ) and all(s["exit_code"] == 0 for s in setup_results)

    record.write(outdir / "record.json")
    return record
