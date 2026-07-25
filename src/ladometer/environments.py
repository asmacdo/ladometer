"""Environments: a resolved set of installed packages to measure.

Each environment is a uv-managed venv built from an explicit package list.
git-annex is treated as just another package (via the git-annex-wheel project),
so an environment pins the annex version alongside the Python side instead of
inheriting whatever the host happens to provide. That is what makes a
cross-implementation comparison meaningful rather than accidental.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .specs import EnvironmentSpec


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv not found on PATH; required to build environments")
    return uv


def ensure(spec: EnvironmentSpec, root: Path) -> Path:
    """Build (or reuse) the venv for ``spec``. Returns its bin/ directory."""
    venv = root / spec.name
    bindir = venv / "bin"
    stamp = venv / ".ladometer-env.json"

    want = {"packages": list(spec.packages), "python": spec.python}
    if stamp.exists() and json.loads(stamp.read_text()) == want:
        return bindir

    if venv.exists():
        shutil.rmtree(venv)
    venv.parent.mkdir(parents=True, exist_ok=True)

    uv = _uv()
    subprocess.run(
        [uv, "venv", "--python", spec.python, str(venv)],
        check=True,
        capture_output=True,
    )
    if spec.packages:
        subprocess.run(
            [uv, "pip", "install", "--python", str(bindir / "python"), *spec.packages],
            check=True,
            capture_output=True,
        )
    stamp.write_text(json.dumps(want))
    return bindir


def describe(bindir: Path) -> dict:
    """Record exactly what is installed.

    The resolved versions, not the requested specifiers -- 'datalad' and
    'datalad==1.6.1' must produce distinguishable records.
    """
    out: dict = {"bin": str(bindir)}
    try:
        frozen = subprocess.run(
            [str(bindir / "python"), "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        out["packages"] = sorted(frozen.split())
    except Exception:
        # uv venvs may not ship pip; fall back to importlib metadata.
        try:
            code = (
                "import importlib.metadata as m, json;"
                "print(json.dumps(sorted("
                "f'{d.metadata[\"Name\"]}=={d.version}' for d in m.distributions())))"
            )
            out["packages"] = json.loads(
                subprocess.run(
                    [str(bindir / "python"), "-c", code],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
            )
        except Exception:
            out["packages"] = None

    for tool, args in (("git", ["--version"]), ("git-annex", ["version", "--raw"])):
        exe = bindir / tool
        cmd = [str(exe) if exe.exists() else tool, *args]
        try:
            out[tool] = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            ).stdout.strip()
        except Exception:
            out[tool] = None
    return out
