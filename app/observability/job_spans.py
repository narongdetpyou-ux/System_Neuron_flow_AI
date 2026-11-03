"""One finished job as OpenTelemetry spans, built after the fact (roadmap 5.1).

Everything comes from records that already exist, so nothing has to be exported from Core's child
processes:
* the queue record: when the job was admitted, first claimed and finished, its status, claims and
  failure reason;
* its ``job.queued`` event: the request id and the ``traceparent`` of the request that admitted it;
* Core's step events (``Runtime.synapse.events_for("monitor", job_id)``): when each attempt of each step
  started and how it ended (only the error *type* is read, never a message);
* the AI view in the job result: provider, model, served model, tokens, masked-item counts and the latency
  the gateway measured.

The shape of one trace::

    POST /v1/jobs                  the request that admitted the job (built by the API process)
    └── job case_triage.v2         admitted → outcome
        ├── queue wait             admitted → first claim
        └── run                    first claim → outcome
            ├── step classify_rules     one span per attempt
            ├── step classify_llm
            │   └── chat <model>        the AI call
            ├── step compare
            └── step prepare

Honest limits:
* times are wall-clock times written by the API and the Runner on the same machine;
* the AI call's length is what the gateway measured. Its position is not recorded, so it is placed to end
  with its step attempt (the call is the agent's last action; ``neuron_flow.ai.placement`` says so). It can
  be off by the few milliseconds that Core needs to collect and check the answer;
* a failed AI attempt that Core retried has no AI span: its step span carries the error type instead.
"""

import re

from .tracing import (KIND_CLIENT, KIND_INTERNAL, STATUS_ERROR, STATUS_UNSET, Span, new_span_id, new_trace_id,
                      parse_traceparent, to_ns)

FAILED_JOB = ("FAILED", "DELIVERY_FAILED")
FAILED_ATTEMPT = ("FAILED", "RETRY_WAIT", "UNFINISHED")
_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,99}$")


def _error_type(error):
    value = error.get("type") if isinstance(error, dict) else None
    return value if isinstance(value, str) and _TYPE.fullmatch(value) else ("Unknown" if error else None)


def _printable(value):
    return isinstance(value, str) and bool(value) and value.isascii() and value.isprintable()


def _ms(start, end):
    return round(max(0.0, end - start) * 1000, 3)


def step_attempts(events, *, end_ns):
    """Pair every ``step.running`` event with the event that ended that attempt.

    Returns dicts with ``step_id``, ``attempt``, ``outcome`` (SUCCEEDED, FAILED, RETRY_WAIT, BLOCKED or
    UNFINISHED), ``start_ns``, ``end_ns`` and ``error_type``, in start order. A blocked step never ran: its
    span has no length.
    """
    running, attempts = {}, []
    for event in events:
        kind, step_id = event.get("kind") or "", event.get("step_id")
        if not step_id or not kind.startswith("step."):
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        attempt = payload.get("attempt")
        at = to_ns(event["timestamp"])
        outcome = kind[len("step."):].upper()
        if outcome == "RUNNING":
            running[(step_id, attempt)] = at
            continue
        start = running.pop((step_id, attempt), at)
        attempts.append({"step_id": step_id, "attempt": attempt, "outcome": outcome, "start_ns": min(start, at),
                         "end_ns": at, "error_type": _error_type(payload.get("error"))})
    for (step_id, attempt), start in running.items():  # never ended; not expected for a finished job
        attempts.append({"step_id": step_id, "attempt": attempt, "outcome": "UNFINISHED", "start_ns": start,
                         "end_ns": max(start, end_ns), "error_type": None})
    return sorted(attempts, key=lambda item: (item["start_ns"], item["step_id"]))


def _ai_attributes(ai, max_tokens, job_attributes):
    usage = ai.get("usage") if isinstance(ai.get("usage"), dict) else {}
    masked = ai.get("masked") if isinstance(ai.get("masked"), dict) else {}
    return {**job_attributes,
            "gen_ai.operation.name": "chat", "gen_ai.provider.name": ai.get("provider"),
            "gen_ai.request.model": ai.get("model"), "gen_ai.response.model": ai.get("served_model"),
            "gen_ai.request.max_tokens": max_tokens,
            "gen_ai.usage.input_tokens": usage.get("input_tokens"),
            "gen_ai.usage.output_tokens": usage.get("output_tokens"),
            "neuron_flow.ai.usage_estimated": usage.get("estimated"),
            "neuron_flow.ai.prompt_id": ai.get("prompt_id"), "neuron_flow.ai.prompt_sha256": ai.get("prompt_sha256"),
            "neuron_flow.ai.redaction": ai.get("redaction"),
            "neuron_flow.ai.masked_items": sum(n for n in masked.values() if type(n) is int),
            "neuron_flow.ai.latency_ms": ai.get("latency_ms"), "neuron_flow.ai.placement": "ends_with_attempt"}


def _max_tokens(spec, step_id):
    for step in (spec or {}).get("steps", []):
        if step.get("id") == step_id:
            value = ((step.get("params") or {}).get("llm") or {}).get("max_tokens")
            return value if type(value) is int else None
    return None


def job_spans(job, admission, core_events, *, ai_step):
    """The spans of one finished job.

    ``job`` is its queue record (``QueueStore.get``), ``admission`` the payload of its ``job.queued`` event
    (``QueueStore.admission``), ``core_events`` its Core events in order (empty when Core never saw the job,
    for example ``configuration_changed``), and ``ai_step`` the id of the step whose output is the job
    result's AI view (``app.services.results.AI_STEP``).
    """
    created, started, finished = job["created_at"], job["started_at"], job["finished_at"]
    if finished is None:
        raise ValueError("the job has not finished")
    parent = parse_traceparent((admission or {}).get("trace_parent"))
    trace_id, parent_id = parent if parent else (new_trace_id(), None)
    start_ns, end_ns = to_ns(created), to_ns(finished)
    status = job["status"]
    result = job.get("result") or {}
    reason = (job.get("failure") or {}).get("reason")
    ids = {"neuron_flow.job.id": job["job_id"]}
    job_span_id = new_span_id()
    attributes = {**ids, "neuron_flow.workflow_type": job["workflow_type"], "neuron_flow.job.status": status,
                  "neuron_flow.job.claims": job["claims"], "neuron_flow.core.status": result.get("core_status"),
                  "neuron_flow.failure.reason": reason, "error.type": reason if status in FAILED_JOB else None,
                  "neuron_flow.request_id": (admission or {}).get("request_id")}
    if started is not None:
        attributes["neuron_flow.queue.wait_ms"] = _ms(created, started)
        attributes["neuron_flow.job.run_ms"] = _ms(started, finished)
    spans = [Span(f"job {job['workflow_type']}", trace_id, job_span_id, parent_id, KIND_INTERNAL, start_ns,
                  max(start_ns, end_ns), attributes, STATUS_ERROR if status in FAILED_JOB else STATUS_UNSET)]
    if started is None:
        return spans
    run_id, run_start = new_span_id(), to_ns(started)
    spans.append(Span("queue wait", trace_id, new_span_id(), job_span_id, KIND_INTERNAL, start_ns,
                      max(start_ns, run_start), {**ids, "neuron_flow.workflow_type": job["workflow_type"]}))
    spans.append(Span("run", trace_id, run_id, job_span_id, KIND_INTERNAL, run_start, max(run_start, end_ns),
                      {**ids, "neuron_flow.job.claims": job["claims"]}))

    spec = job.get("spec") or {}
    definitions = {step["id"]: step for step in spec.get("steps", [])}
    versions = spec.get("agent_versions") or {}
    ai = result.get("ai") if isinstance(result.get("ai"), dict) else None
    for attempt in step_attempts(core_events, end_ns=end_ns):
        definition = definitions.get(attempt["step_id"], {})
        agent = definition.get("agent")
        identity = versions.get(agent) if agent else None  # Core's {"entrypoint": ..., "version": ...}
        version = identity.get("version") if isinstance(identity, dict) else None
        step_attributes = {**ids, "neuron_flow.step.id": attempt["step_id"], "neuron_flow.step.agent": agent,
                           "neuron_flow.step.attempt": attempt["attempt"] if type(attempt["attempt"]) is int else None,
                           "neuron_flow.step.max_attempts": definition.get("max_attempts"),
                           "neuron_flow.step.outcome": attempt["outcome"],
                           # A version that is not printable ASCII is left out rather than losing the trace.
                           "neuron_flow.agent.version": version if _printable(version) else None,
                           "error.type": attempt["error_type"]}
        answered = (ai is not None and attempt["step_id"] == ai_step and attempt["outcome"] == "SUCCEEDED"
                    and attempt["attempt"] == ai.get("attempt"))
        if answered:
            step_attributes["neuron_flow.ai.status"] = ai.get("status")
            if ai.get("status") == "unavailable":
                step_attributes["neuron_flow.ai.reason"] = ai.get("reason")
        step_id = new_span_id()
        spans.append(Span(f"step {attempt['step_id']}", trace_id, step_id, run_id, KIND_INTERNAL,
                          attempt["start_ns"], attempt["end_ns"], step_attributes,
                          STATUS_ERROR if attempt["outcome"] in FAILED_ATTEMPT else STATUS_UNSET))
        latency = ai.get("latency_ms") if answered else None
        measured = isinstance(latency, (int, float)) and not isinstance(latency, bool)
        if answered and ai.get("status") == "ok" and measured:
            call_end = attempt["end_ns"]
            call_start = max(attempt["start_ns"], call_end - int(round(latency * 1_000_000)))
            spans.append(Span(f"chat {ai.get('model')}", trace_id, new_span_id(), step_id, KIND_CLIENT, call_start,
                              call_end, _ai_attributes(ai, _max_tokens(spec, ai_step), ids)))
    return spans
