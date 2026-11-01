"""Helpers for the intake, queue and Runner tests.

* ``settings``/``case_body``: test settings and request bodies;
* ``slow_catalog``: a test-only workflow whose single step can be made slow on chosen attempts,
  so a test can kill the Runner in the middle of it;
* ``branches_catalog``: two independent branches where one step's output always fails validation;
* ``run_runner``: the target of a spawned process that runs a Runner until it is killed.
"""

from pathlib import Path
import time

from neuron_flow import AgentDefinition

from app.llm import LLMConfig
from app.services.workflows import CATALOG, WorkflowType, check_case
from app.settings import Settings

KEY = "test-access-key-0123456789"


def settings(data_dir, **overrides):
    values = {"data_dir": Path(data_dir), "storage": "configured", "access_key": KEY, "runner_poll_s": 0.05}
    values.update(overrides)
    return Settings(**values)


def case_body(key, summary="I cannot upload an attachment", case_id="CASE-1", workflow_type="case_triage.v2"):
    return {"workflow_type": workflow_type, "idempotency_key": key, "input": {"case_id": case_id, "summary": summary}}


def wait_for(condition, timeout=30.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


# -- a slow step ---------------------------------------------------------------------------------

def slow_step(message):
    params = message["params"]
    marker = Path(params["marker_dir"]) / f"{message['job_id']}.attempt{message['attempt']}"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("started", encoding="utf-8")
    if message["attempt"] in params["slow_attempts"]:
        time.sleep(params["sleep_s"])
    return {"ok": True, "attempt": message["attempt"]}


def validate_slow(message, output):
    if output != {"ok": True, "attempt": message["attempt"]}:
        raise ValueError("slow step output is not what the test expects")


def slow_catalog(marker_dir, *, sleep_s=60.0, slow_attempts=(1,), max_attempts=2):
    def build(job_id, case, _config):
        return {"job_id": job_id, "input": case, "steps": [{
            "id": "slow", "agent": "test.slow", "max_attempts": max_attempts, "timeout_s": sleep_s + 30,
            "retry_delay_s": 0.05,
            "params": {"marker_dir": str(marker_dir), "sleep_s": sleep_s, "slow_attempts": list(slow_attempts)}}]}

    def agents(_config):
        return [AgentDefinition("test.slow", "tests.service_fixtures:slow_step", validate_slow, version="1")]

    return {"test.slow": WorkflowType("test.slow", "test only: one slow step", "slow", check_case, build, agents),
            **CATALOG}


# -- a step whose output never passes its validator --------------------------------------------

def emit(message):
    return {"value": message["params"]["value"]}


def validate_good(message, output):
    if output != {"value": "good"}:
        raise ValueError("output rejected by the validator")


def follow(message):
    (dependency,) = message["dependencies"].values()
    return {"value": dependency["value"]}


def validate_follow(message, output):
    (dependency,) = message["dependencies"].values()
    if output != {"value": dependency["value"]}:
        raise ValueError("follow output does not copy its dependency")


def branches_catalog():
    def build(job_id, case, _config):
        return {"job_id": job_id, "input": case, "steps": [
            {"id": "bad", "agent": "test.emit", "max_attempts": 1, "params": {"value": "bad"}},
            {"id": "after_bad", "agent": "test.follow", "depends_on": ["bad"], "max_attempts": 1},
            {"id": "good", "agent": "test.emit", "max_attempts": 1, "params": {"value": "good"}},
            {"id": "after_good", "agent": "test.follow", "depends_on": ["good"], "max_attempts": 1},
        ]}

    def agents(_config):
        return [AgentDefinition("test.emit", "tests.service_fixtures:emit", validate_good, version="1"),
                AgentDefinition("test.follow", "tests.service_fixtures:follow", validate_follow, version="1")]

    return {"test.branches": WorkflowType("test.branches", "test only: a failed validator", "after_good",
                                          check_case, build, agents)}


# -- a Runner in its own process -----------------------------------------------------------------

def run_runner(data_dir, marker_dir, sleep_s, slow_attempts, max_attempts):
    from app.services.runner import Runner
    catalog = slow_catalog(marker_dir, sleep_s=sleep_s, slow_attempts=slow_attempts, max_attempts=max_attempts)
    Runner(settings(data_dir), catalog=catalog, llm_config=LLMConfig()).serve()
