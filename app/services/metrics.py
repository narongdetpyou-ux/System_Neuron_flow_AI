"""Queue and run-time figures for the status page (roadmap 5.3).

Computed from the application queue on every ``GET /v1/status``, so they need no extra state:
* **waiting:** how many jobs wait now, and how long the oldest one has waited;
* **per workflow type**, over the newest ``WINDOW`` jobs that ran to an outcome (cancelled jobs never
  ran, so they are left out): how many there were, the median and the longest **queue wait**
  (admitted → first claimed by the Runner) and **run time** (first claimed → outcome), and how many
  were taken over again after a Runner stop (``recovered``);
* **failures by reason**, over the same jobs (``failure.reason`` of FAILED and DELIVERY_FAILED jobs).

Honest limits, also said on the page:
* run time starts at the *first* claim. A job whose Runner stopped mid-way includes the time until a new
  Runner took it over; ``recovered`` shows when that happened;
* failed jobs count in the timings too, because they ran;
* on Render's free plan the queue is wiped on every sleep, restart and deploy, so the figures start again;
* the figures hold timings, workflow names, counts and reason codes only: no case text and no job ids.
"""

from statistics import median

WINDOW = 100  # the newest jobs that ran to an outcome


def _seconds(start, end):
    """A duration in seconds (never negative, even if the clock stepped back), or ``None``."""
    if start is None or end is None:
        return None
    return max(0.0, end - start)


def _spread(values):
    """``{"median": …, "max": …}`` in seconds rounded to milliseconds, or ``None`` without values."""
    if not values:
        return None
    return {"median": round(median(values), 3), "max": round(max(values), 3)}


def queue_metrics(store, now, *, window=WINDOW):
    count, oldest = store.waiting()
    outcomes = store.recent_outcomes(window)
    timings, failures = {}, {}
    for job in outcomes:
        entry = timings.setdefault(job["workflow_type"], {"jobs": 0, "recovered": 0, "wait": [], "run": []})
        entry["jobs"] += 1
        entry["recovered"] += 1 if job["claims"] > 1 else 0
        wait = _seconds(job["created_at"], job["started_at"])
        run = _seconds(job["started_at"], job["finished_at"])
        if wait is not None:
            entry["wait"].append(wait)
        if run is not None:
            entry["run"].append(run)
        if job["status"] in ("FAILED", "DELIVERY_FAILED"):
            reason = job["reason"] or "unknown"
            failures[reason] = failures.get(reason, 0) + 1
    return {
        "waiting": {"count": count,
                    "oldest_age_s": None if oldest is None else round(_seconds(oldest, now), 1)},
        "window": {"limit": window, "jobs": len(outcomes)},
        "workflows": {name: {"jobs": entry["jobs"], "recovered": entry["recovered"],
                             "wait_s": _spread(entry["wait"]), "run_s": _spread(entry["run"])}
                      for name, entry in sorted(timings.items())},
        # The most frequent reason first; ties in name order, so the order never flickers.
        "failures": dict(sorted(failures.items(), key=lambda item: (-item[1], item[0]))),
    }
