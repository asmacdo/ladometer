"""Fixtures: datasets in a known state, built from a spec.

Design note -- why generated fixtures, and why that solves fixture reset:

A benchmark needs the same starting state on every rep, and the interesting
scenarios mutate the dataset. The obvious approaches both disappoint:

- ``git reset --hard`` + ``clean`` is fast but subtly not-pristine: it leaves
  reflogs, loosened objects, and touched mtimes behind. For a suite whose whole
  subject is "how long does it take to inspect state", perturbing state between
  reps is exactly the wrong failure mode (a stale mtime makes git re-run the
  annex clean filter, and you measure that instead of the thing you meant to).
- re-cloning from a seed is honest but slow enough to dominate the measurement.

Generating from a deterministic spec dissolves the problem: the pristine build
is *derived*, so it can be cached once and cheaply re-materialized per run. On a
copy-on-write filesystem (btrfs/xfs/zfs) a reflink copy is near-instant and
near-free, which makes "restore to pristine" the default for every scenario
rather than a thing you opt into. On other filesystems it degrades to a plain
recursive copy -- slower, still correct.

The secondary win is portability: a spec is a few lines of TOML that anyone can
reproduce, whereas a real-world dataset is a 22 GB thing on one particular host.
Real datasets stay supported as ``kind = "existing"`` for validation, but the
suite should never *depend* on one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .specs import FixtureSpec


@dataclass(frozen=True)
class Shape:
    """The parameters of a generated dataset hierarchy.

    Modelled on the shape that actually hurts: a superdataset of studies, each
    with derivative subdatasets, each pointing at a raw-data subdataset holding
    the bulk of the files. That nesting -- not raw file count alone -- is what
    makes a recursive dirty check expensive.
    """

    #: Number of study subdatasets under the superdataset.
    studies: int = 2
    #: Derivative subdatasets per study.
    derivatives_per_study: int = 2
    #: Files in each derivative dataset.
    files_per_derivative: int = 20
    #: Files in the shared raw dataset under each derivative. This is the fat
    #: one -- in the real workload it is tens of thousands.
    files_per_raw: int = 200
    #: Annex the bulk files (locked symlinks) rather than committing to git.
    #: Locked annex files are the common case and make dirty-checking cheap per
    #: file; flipping this is how you would measure the unlocked penalty.
    annex: bool = True

    def digest(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]

    @classmethod
    def from_toml(cls, d: dict) -> Shape:
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, env=env)


def _git_env() -> dict:
    """Deterministic identity, so a build does not depend on host git config."""
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="ladometer",
        GIT_AUTHOR_EMAIL="ladometer@example.invalid",
        GIT_COMMITTER_NAME="ladometer",
        GIT_COMMITTER_EMAIL="ladometer@example.invalid",
    )
    return env


def _populate(ds: Path, n: int, annex: bool, env: dict, tag: str) -> None:
    """Create ``n`` small files and commit them.

    Files are written directly and added with git/git-annex rather than through
    datalad: the datalad call overhead per file would dominate build time, and
    the resulting repository is identical.
    """
    if n <= 0:
        return
    data = ds / "data"
    data.mkdir(exist_ok=True)
    for i in range(n):
        # Unique content per file so annex keys differ, as they would in reality.
        (data / f"{tag}_{i:06d}.dat").write_text(f"{tag}-{i}\n")
    if annex:
        _run(["git", "annex", "add", "data"], cwd=ds, env=env)
    else:
        _run(["git", "add", "data"], cwd=ds, env=env)
    _run(["git", "commit", "-q", "-m", f"add {n} {tag} files"], cwd=ds, env=env)


def build(shape: Shape, dest: Path, datalad: str = "datalad") -> Path:
    """Build a pristine hierarchy at ``dest``. Returns ``dest``."""
    env = _git_env()
    dest.parent.mkdir(parents=True, exist_ok=True)

    _run([datalad, "-f", "json", "create", str(dest)], cwd=dest.parent, env=env)

    for s in range(shape.studies):
        study_rel = f"studies/study-{s:03d}"
        _run(
            [datalad, "create", "-d", str(dest), str(dest / study_rel)],
            cwd=dest,
            env=env,
        )
        study = dest / study_rel

        for d in range(shape.derivatives_per_study):
            deriv_rel = f"derivatives/deriv-{d:03d}"
            _run(
                [datalad, "create", "-d", str(study), str(study / deriv_rel)],
                cwd=study,
                env=env,
            )
            deriv = study / deriv_rel
            _populate(deriv, shape.files_per_derivative, shape.annex, env, "deriv")

            # The fat leaf: each derivative carries its own raw subdataset,
            # mirroring how derivative datasets reference their inputs.
            raw_rel = "sourcedata/raw"
            _run(
                [datalad, "create", "-d", str(deriv), str(deriv / raw_rel)],
                cwd=deriv,
                env=env,
            )
            _populate(deriv / raw_rel, shape.files_per_raw, shape.annex, env, "raw")

    # One recursive save to record every subdataset pointer up the chain.
    _run([datalad, "save", "-r", "-m", "build fixture"], cwd=dest, env=env)
    return dest


def ensure_pristine(shape: Shape, cache_root: Path, datalad: str = "datalad") -> Path:
    """Return a cached pristine build for ``shape``, building it if absent.

    Keyed by the shape digest, so changing the spec makes a new cache entry
    rather than silently reusing a mismatched one.
    """
    pristine = cache_root / f"pristine-{shape.digest()}"
    stamp = pristine / ".ladometer-built"
    if stamp.exists():
        return pristine
    if pristine.exists():
        shutil.rmtree(pristine)
    build(shape, pristine, datalad=datalad)
    stamp.write_text(json.dumps(asdict(shape), indent=2))
    return pristine


def materialize(pristine: Path, dest: Path) -> dict:
    """Make a working copy of a pristine fixture.

    Uses ``cp --reflink=auto``: instant and space-free on CoW filesystems,
    silently falling back to a real copy elsewhere. Returns a dict describing
    how it went, for the run record -- the copy method changes what "restore"
    costs, so it is not an implementation detail.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cp", "-a", "--reflink=auto", str(pristine), str(dest)],
        check=True,
        capture_output=True,
    )
    return {"method": "cp -a --reflink=auto", "source": str(pristine)}


def stat_hierarchy(root: Path) -> dict:
    """Describe a fixture's actual shape, as built rather than as specified.

    Recorded with every run so a record is interpretable without needing the
    fixture itself.
    """
    repos, tracked = 0, 0
    for gitpath in root.rglob(".git"):
        repo = gitpath.parent
        try:
            out = subprocess.run(
                ["git", "ls-files"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            continue
        repos += 1
        tracked += out.count("\n")
    return {"repos": repos, "tracked_files": tracked}


def resolve(
    spec: FixtureSpec, cache_root: Path, work_root: Path, datalad: str = "datalad"
) -> tuple[Path, dict]:
    """Produce a ready-to-measure fixture path plus provenance for the record."""
    if spec.kind == "generated":
        pristine = ensure_pristine(spec.shape, cache_root, datalad=datalad)
        dest = work_root / spec.name
        prov = materialize(pristine, dest)
        prov["shape"] = asdict(spec.shape)
        prov["shape_digest"] = spec.shape.digest()
        return dest, prov
    if spec.kind == "existing":
        # Measured in place. Only valid for non-mutating scenarios; the runner
        # enforces that rather than trusting the suite author to remember.
        return spec.path, {"method": "in-place", "source": str(spec.path)}
    raise ValueError(f"unknown fixture kind: {spec.kind!r}")
