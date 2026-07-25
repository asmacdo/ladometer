"""The run record: the single unit of output.

One measured run produces exactly one record. Everything downstream (comparison,
plotting, regression tracking) reads records and nothing else, so this schema is
the suite's real interface -- change it deliberately and bump SCHEMA.
"""

from __future__ import annotations

import json
import platform
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ladometer/run/1"

#: Per-metric reliability of the current measurement backend.
#:
#: These are first-class metrics -- recorded, reported, and compared. The
#: annotation travels with the data so a reader knows how much weight to put on
#: a given number, and so that the same records and the same reporting code
#: become more trustworthy the moment the backend improves. Reliability is a
#: property of the measurement source, not of the metric's usefulness.
#:
#: duct's RSS and CPU sampling is known-unreliable today (upstream fix pending),
#: so those are marked 'low'. Update this map when that lands; nothing else in
#: the suite needs to change.
METRIC_RELIABILITY = {
    "wall_clock_sec": "high",
    "peak_rss_bytes": "low",  # duct sampling, unreliable as of 2026-07
    "average_rss_bytes": "low",
    "peak_vsz_bytes": "low",
    "peak_pcpu": "low",
    "average_pcpu": "low",
}


@dataclass
class Measurement:
    """What we measured, as first-class metrics.

    Consult ``METRIC_RELIABILITY`` (carried in every record) before drawing a
    conclusion from any given field.
    """

    wall_clock_sec: float | None = None
    peak_rss_bytes: int | None = None
    average_rss_bytes: float | None = None
    peak_vsz_bytes: int | None = None
    peak_pcpu: float | None = None
    average_pcpu: float | None = None
    exit_code: int | None = None
    #: Sampling density -- context for how much to trust the sampled metrics
    #: on this particular run (few samples on a fast command means less).
    num_samples: int | None = None
    #: Anything else duct reported, kept verbatim so records stay re-analysable.
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_duct_info(cls, info: dict) -> Measurement:
        s = info.get("execution_summary", {})
        return cls(
            wall_clock_sec=s.get("wall_clock_time"),
            peak_rss_bytes=s.get("peak_rss"),
            average_rss_bytes=s.get("average_rss"),
            peak_vsz_bytes=s.get("peak_vsz"),
            peak_pcpu=s.get("peak_pcpu"),
            average_pcpu=s.get("average_pcpu"),
            exit_code=s.get("exit_code"),
            num_samples=s.get("num_samples"),
            raw=s,
        )


@dataclass
class RunRecord:
    schema: str = SCHEMA
    run_id: str = ""
    started_at: str = ""
    scenario: dict = field(default_factory=dict)
    fixture: dict = field(default_factory=dict)
    environment: dict = field(default_factory=dict)
    host: dict = field(default_factory=dict)
    rep: int = 0
    #: 'warm' (a discarded warmup pass ran first) or 'unknown'. Cold requires
    #: dropping caches, which needs privileges we do not assume.
    cache_state: str = "unknown"
    command: list[str] = field(default_factory=list)
    measurement: Measurement = field(default_factory=Measurement)
    #: Snapshot of METRIC_RELIABILITY at record time, so an old record can be
    #: read correctly years later without guessing which backend produced it.
    metric_reliability: dict = field(default_factory=lambda: dict(METRIC_RELIABILITY))
    measurement_backend: dict = field(default_factory=dict)
    validity: dict = field(default_factory=dict)
    duct_prefix: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def describe_host() -> dict:
    """Host facts that plausibly change a measurement."""
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": _cpu_count(),
        "python": platform.python_version(),
    }


def _cpu_count() -> int | None:
    try:
        import os

        return os.cpu_count()
    except Exception:
        return None


def describe_filesystem(path: Path) -> dict:
    """Filesystem type of a path.

    Recorded because it routinely matters more than CPU for these workloads --
    NFS versus local nvme is not a footnote.
    """
    try:
        out = subprocess.run(
            ["findmnt", "-no", "FSTYPE,SOURCE", "--target", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        return {"fstype": out[0], "source": out[1] if len(out) > 1 else None}
    except Exception:
        return {"fstype": None, "source": None}
