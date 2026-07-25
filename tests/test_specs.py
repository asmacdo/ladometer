"""Tests for the declarative layer.

These are deliberately cheap: nothing here builds a dataset or runs a command.
The expensive end-to-end path is covered by a `slow`-marked test.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ladometer.fixtures import Shape
from ladometer.specs import Suite


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "suite.toml"
    p.write_text(textwrap.dedent(body))
    return p


def test_shape_counts():
    # depth 2, breadth 2 -> 1 root + 2 + 4
    s = Shape(depth=2, breadth=2, files_per_dataset=10)
    assert s.n_datasets() == 7
    assert s.n_files() == 70


def test_shape_chain_is_one_per_level():
    s = Shape(depth=14, breadth=1, files_per_dataset=1)
    assert s.n_datasets() == 15


def test_shape_digest_is_stable_and_specific():
    a = Shape(depth=2, breadth=2)
    b = Shape(depth=2, breadth=2)
    c = Shape(depth=2, breadth=3)
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()


def test_shape_digest_covers_every_field():
    """A field the digest ignores would silently reuse a wrong cached build."""
    base = Shape()
    for field, alt in (
        ("depth", 5),
        ("breadth", 7),
        ("files_per_dataset", 999),
        ("file_size_bytes", 4096),
        ("annex", False),
    ):
        assert Shape(**{**base.__dict__, field: alt}).digest() != base.digest(), field


def test_scenario_defaults_to_one_measured_command(tmp_path):
    cfg = write(
        tmp_path,
        """
        [scenario.s]
        command = ["datalad", "status"]
        """,
    )
    sc = Suite.load(cfg).scenarios["s"]
    assert sc.command == ("datalad", "status")
    assert sc.setup == ()
    assert sc.checks == ("exit_zero",)
    assert sc.cwd == "{work}"


def test_scenario_setup_is_separate_from_measurement(tmp_path):
    cfg = write(
        tmp_path,
        """
        [scenario.s]
        setup = [["datalad", "install", "-r", "-s", "{pristine}", "{work}"]]
        command = ["datalad", "save", "-r"]
        """,
    )
    sc = Suite.load(cfg).scenarios["s"]
    assert sc.setup == (("datalad", "install", "-r", "-s", "{pristine}", "{work}"),)
    assert sc.command == ("datalad", "save", "-r")


def test_fixture_generated_by_default(tmp_path):
    cfg = write(
        tmp_path,
        """
        [fixture.f]
        [fixture.f.shape]
        depth = 1
        breadth = 3
        """,
    )
    fx = Suite.load(cfg).fixtures["f"]
    assert fx.kind == "generated"
    assert fx.shape.n_datasets() == 4


def test_fixture_existing_carries_path(tmp_path):
    cfg = write(
        tmp_path,
        """
        [fixture.f]
        kind = "existing"
        path = "/somewhere/ds"
        """,
    )
    fx = Suite.load(cfg).fixtures["f"]
    assert fx.kind == "existing"
    assert fx.path == Path("/somewhere/ds")
    assert fx.shape is None


def test_shipped_suites_parse():
    """The suites in the repo must stay loadable -- they are documentation."""
    root = Path(__file__).resolve().parent.parent
    for name in ("suite.toml", "scaling.toml"):
        suite = Suite.load(root / name)
        assert suite.scenarios and suite.fixtures and suite.environments


def test_every_scenario_has_a_validity_check():
    """Invariant 4: a benchmark that can silently no-op is worse than none."""
    root = Path(__file__).resolve().parent.parent
    for name in ("suite.toml", "scaling.toml"):
        for sc in Suite.load(root / name).scenarios.values():
            assert sc.checks, f"{name}:{sc.name} has no checks"


@pytest.mark.parametrize("bad", ["", "[fixture.f]\nkind = 'nonsense'\n"])
def test_malformed_config_does_not_crash_loading(tmp_path, bad):
    suite = Suite.load(write(tmp_path, bad))
    assert isinstance(suite.scenarios, dict)
