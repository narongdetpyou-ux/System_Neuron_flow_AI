"""Bounded execution telemetry; reporting does not change runtime decisions."""

from collections import Counter, deque
from contextlib import contextmanager
import math
import os
from pathlib import Path
import time

from .supervision import number


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


class Telemetry:
    def __init__(self, retention=2000):
        if type(retention) is not int or not 1 <= retention <= 100000:
            raise ValueError("retention must be 1-100000")
        self.samples = deque(maxlen=retention)
        self.counts = Counter()

    def record(self, phase, elapsed_ms, outcome="OK"):
        number(elapsed_ms, 0, 1e12, "elapsed_ms")
        if not isinstance(phase, str) or not 1 <= len(phase) <= 80 or not all(c.isalnum() or c in "_-" for c in phase):
            raise ValueError("Phase must be a 1-80 character identifier")
        self.samples.append({"phase": phase, "elapsed_ms": elapsed_ms, "outcome": outcome})
        self.counts[phase] += 1

    @contextmanager
    def measure(self, phase):
        start = time.monotonic()
        outcome = "ERROR"
        try:
            yield
            outcome = "OK"
        finally:
            self.record(phase, (time.monotonic() - start) * 1000, outcome)

    def snapshot(self):
        phases = {}
        for phase, total in sorted(self.counts.items()):
            values = [s["elapsed_ms"] for s in self.samples if s["phase"] == phase]
            phases[phase] = {"total_count": total, "retained_count": len(values),
                             "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
                             "errors_retained": sum(s["outcome"] != "OK" for s in self.samples if s["phase"] == phase)}
        rss = None
        if os.name == "posix":
            try:
                rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            except (OSError, ValueError, IndexError):
                pass
        return {"phases": phases, "retained_samples": len(self.samples), "samples": list(self.samples), "controller_rss_bytes": rss,
                "memory_scope": "Controller only; child memory is not aggregated or estimated"}


