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

    Deliberately a *generic tree* rather than a BIDS-shaped one. The suite's
    first job is to find out what actually drives cost -- dataset count, file
    count, nesting depth, file size, annex-vs-git -- and that requires varying
    one axis while holding the others fixed. A domain-shaped spec bakes several
    axes together and cannot answer the question.

    A realistic BIDS-like hierarchy is expressible as a tree; the reverse is
    not true, so this loses nothing.
    """

    #: Levels of subdatasets below the root. depth=0 is a single dataset.
    depth: int = 2
    #: Child subdatasets per dataset.
    breadth: int = 2
    #: Files committed in every dataset in the tree.
    files_per_dataset: int = 100
    #: Bytes per file. Separates "many files" from "much data" as cost drivers.
    file_size_bytes: int = 64
    #: Annex the files (locked symlinks) rather than committing them to git.
    annex: bool = True

    def n_datasets(self) -> int:
        return sum(self.breadth**i for i in range(self.depth + 1))

    def n_files(self) -> int:
        return self.n_datasets() * self.files_per_dataset

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


def _populate(ds: Path, shape: Shape, env: dict, tag: str) -> None:
    """Create ``shape.files_per_dataset`` files and commit them.

    Files are written directly and added with git/git-annex rather than through
    datalad: the datalad call overhead per file would dominate build time, and
    the resulting repository is identical.
    """
    n = shape.files_per_dataset
    if n <= 0:
        return
    data = ds / "data"
    data.mkdir(exist_ok=True)
    for i in range(n):
        # Unique content per file so annex keys differ, as they would in
        # reality -- identical content would collapse to one key and make the
        # fixture unrepresentatively cheap.
        head = f"{tag}-{i}\n".encode()
        pad = max(0, shape.file_size_bytes - len(head))
        (data / f"{tag}_{i:06d}.dat").write_bytes(head + b"\0" * pad)
    if shape.annex:
        _run(["git", "annex", "add", "--quiet", "data"], cwd=ds, env=env)
    else:
        _run(["git", "add", "data"], cwd=ds, env=env)
    _run(["git", "commit", "-q", "-m", f"add {n} files"], cwd=ds, env=env)


def _build_subtree(
    parent: Path, level: int, shape: Shape, env: dict, datalad: str
) -> None:
    """Recursively create ``breadth`` children under ``parent``."""
    if level > shape.depth:
        return
    for b in range(shape.breadth):
        child_rel = f"sub-{level:02d}-{b:03d}"
        child = parent / child_rel
        _run([datalad, "create", "-d", str(parent), str(child)], cwd=parent, env=env)
        _populate(child, shape, env, f"l{level}b{b}")
        _build_subtree(child, level + 1, shape, env, datalad)


def build(shape: Shape, dest: Path, datalad: str = "datalad") -> Path:
    """Build a pristine hierarchy at ``dest``. Returns ``dest``."""
    env = _git_env()
    dest.parent.mkdir(parents=True, exist_ok=True)

    _run([datalad, "create", str(dest)], cwd=dest.parent, env=env)
    _populate(dest, shape, env, "root")
    _build_subtree(dest, 1, shape, env, datalad)

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
