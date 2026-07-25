"""Declarative specs: what to measure, against what, in which environment.

These are plain data. Nothing here touches the filesystem or runs a command --
that keeps the suite definition inspectable and diffable on its own.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FixtureSpec:
    """A dataset in a known state, to run scenarios against.

    ``generated`` is the default and the one to prefer: it is reproducible on
    any host and cheap to restore between reps (see fixtures.py). ``existing``
    points at a real dataset already on disk -- useful for validating that a
    generated shape actually reproduces real-world behavior, but it cannot be
    restored, so it is limited to non-mutating scenarios.
    """

    name: str
    kind: str = "generated"
    #: Only for kind='existing'.
    path: Path | None = None
    #: Only for kind='generated'. Imported lazily to keep specs.py data-only.
    shape: object | None = None

    @classmethod
    def from_toml(cls, name: str, d: dict) -> FixtureSpec:
        from .fixtures import Shape

        kind = d.get("kind", "generated")
        return cls(
            name=name,
            kind=kind,
            path=Path(d["path"]).expanduser() if d.get("path") else None,
            shape=Shape.from_toml(d.get("shape", {})) if kind == "generated" else None,
        )


@dataclass(frozen=True)
class EnvironmentSpec:
    """A set of packages to install into a venv.

    git-annex is a package too: psychoinformatics-de/git-annex-wheel makes it
    pip-installable, so an environment can pin the annex version alongside the
    Python side rather than depending on whatever the host provides.
    """

    name: str
    packages: tuple[str, ...]
    python: str = "3.13"

    @classmethod
    def from_toml(cls, name: str, d: dict) -> EnvironmentSpec:
        return cls(
            name=name,
            packages=tuple(d.get("packages", ())),
            python=d.get("python", "3.13"),
        )


@dataclass(frozen=True)
class ScenarioSpec:
    """A command to measure, plus how to tell it actually did the work.

    ``mutates`` is load-bearing: it decides whether the fixture must be restored
    between reps. A scenario that mutates without declaring it will silently
    measure a different starting state on every rep.
    """

    name: str
    #: The one measured command. Exactly one per scenario, by design.
    command: tuple[str, ...]
    #: Commands run before the measurement. Timed and recorded separately, so
    #: an expensive setup can never be mistaken for the thing under test. The
    #: same command may be a setup phase here and the measured command of a
    #: different scenario -- that is how clone gets benchmarked in its own right
    #: while also preparing a clean tree for `save`.
    setup: tuple[tuple[str, ...], ...] = ()
    #: Working directory for the measured command. Supports {work}, {pristine},
    #: {work_root} placeholders.
    cwd: str = "{work}"
    mutates: bool = False
    #: Named validity checks applied to the completed run. A benchmark that
    #: silently no-ops is worse than no benchmark, so this is not optional.
    checks: tuple[str, ...] = ("exit_zero",)
    description: str = ""

    @classmethod
    def from_toml(cls, name: str, d: dict) -> ScenarioSpec:
        return cls(
            name=name,
            command=tuple(d["command"]),
            setup=tuple(tuple(c) for c in d.get("setup", ())),
            cwd=d.get("cwd", "{work}"),
            mutates=d.get("mutates", False),
            checks=tuple(d.get("checks", ("exit_zero",))),
            description=d.get("description", ""),
        )


@dataclass
class Suite:
    """A whole suite definition: the matrix axes plus which points to run."""

    fixtures: dict[str, FixtureSpec] = field(default_factory=dict)
    environments: dict[str, EnvironmentSpec] = field(default_factory=dict)
    scenarios: dict[str, ScenarioSpec] = field(default_factory=dict)
    reps: int = 3

    @classmethod
    def load(cls, path: Path) -> Suite:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        return cls(
            fixtures={
                k: FixtureSpec.from_toml(k, v)
                for k, v in raw.get("fixture", {}).items()
            },
            environments={
                k: EnvironmentSpec.from_toml(k, v)
                for k, v in raw.get("environment", {}).items()
            },
            scenarios={
                k: ScenarioSpec.from_toml(k, v)
                for k, v in raw.get("scenario", {}).items()
            },
            reps=raw.get("reps", 3),
        )
