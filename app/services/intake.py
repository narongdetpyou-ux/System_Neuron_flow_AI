"""A person's answer to the router (roadmap 4.2's second part, ADR-039): confirm a proposal, or reply to a question.

The router (``intake.route.v1``) never runs a task. Two API routes let a person act on its answer, and both are a
person's requests that go through normal admission (``app.services.admission``), never through the exchange:

* ``POST /v1/jobs/{router_job_id}/confirm`` ("ใช่ ทำเลย"): the router job must have ended with a ``proposal`` or a
  ``confirm`` answer. The person may choose its task (the default) or the study offer in ``also``. The new job's
  input is built from the stored answer, never from the request: the person's own words as the router copied them,
  plus the fields the application fills (a case's id, made from the router job's id). Its idempotency key is
  ``confirm:<router job id>``, a key no outside request may use, so a router job is confirmed at most once: the same
  confirmation again returns the same job, and another task gets ``409 already_confirmed``. The task's own input
  check runs here, at admission.
* ``POST /v1/jobs/{router_job_id}/reply``: the router job must have asked a ``question``. The answer becomes a new
  router job whose message is the earlier message and the answer (both the person's words), and whose input carries
  ``earlier`` (the earlier job's id and the question), copied from the store; a request cannot set it.

Either way the queue records the link in the new job's first event and one event on the router job, in the same
transaction (``QueueStore.admit``'s ``link``). Nothing here decides about a person: a confirmed case still waits for a
person's decision (rule 4).
"""

from .admission import RESERVED_KEY_PREFIXES, AdmissionError, admit

COMPLETED = "COMPLETED"  # the router's job state once it answered (informational, ADR-018)

ROUTER = "intake.route.v1"
CONFIRM_PREFIX = "confirm:"
CONFIRMABLE = ("proposal", "confirm")
ANSWERABLE = ("question",)
# The fields the application fills when a person confirms (the frame names them as given by the system).
SYSTEM_FILLERS = {"case_id": lambda router_job_id: "RT-" + router_job_id[len("job_"):][:12].upper()}
CONFIRMED_EVENT, REPLIED_EVENT = "router.confirmed", "router.replied"


class IntakeError(Exception):
    """A refused confirmation or reply. ``status`` is the HTTP status, ``code`` a stable machine-readable reason."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def confirm_key(router_job_id):
    return CONFIRM_PREFIX + router_job_id


def router_answer(job, kinds):
    """The router's stored answer, when the job is a finished router job whose answer is one of ``kinds``."""
    if job is None:
        raise IntakeError(404, "job_not_found", "No job with this id")
    if job["workflow_type"] != ROUTER:
        raise IntakeError(409, "not_a_router_job", "Only an answer of the router can be confirmed or answered")
    if job["status"] != COMPLETED:
        raise IntakeError(409, "router_not_finished", "The router has not answered yet", job_status=job["status"])
    answer = (job.get("result") or {}).get("output") or {}
    if answer.get("kind") not in kinds:
        what = "confirm" if kinds == CONFIRMABLE else "answer"
        raise IntakeError(409, f"nothing_to_{what}", f"This answer of the router has nothing to {what}",
                          kind=answer.get("kind"))
    return answer


def choices(answer):
    """``{task id: (workflow type, input, fields the system fills)}``: the proposed task and the study offer."""
    options = {answer["task"]: (answer["workflow_type"], dict(answer["input"]), list(answer["system_fields"]))}
    for offer in answer.get("also") or []:
        options.setdefault(offer["task"], (offer["workflow_type"], dict(offer["input"]), []))
    return options


def target_input(router_job_id, given, system_fields):
    """The task's input: the person's words from the router's answer, and the fields the application fills."""
    filled = dict(given)
    for name in system_fields:
        filler = SYSTEM_FILLERS.get(name)
        if filler is None:
            raise IntakeError(409, "cannot_fill", f"The system cannot fill the field {name} of this task")
        filled[name] = filler(router_job_id)
    return filled


def confirm(store, router_job, body, *, catalog, max_queued, request_id=None, trace_parent=None):
    """Admit the task a person confirmed. Returns ``(job, created, task)``; raises :class:`IntakeError`."""
    body = {} if body is None else body
    if not isinstance(body, dict) or not set(body) <= {"task"}:
        raise IntakeError(400, "invalid_fields", "A confirmation takes no fields, or only task")
    answer = router_answer(router_job, CONFIRMABLE)
    options = choices(answer)
    task = body.get("task", answer["task"])
    if not isinstance(task, str) or task not in options:
        raise IntakeError(400, "unknown_task", "task must be the proposed task or the study offer",
                          allowed=sorted(options))
    workflow_type, given, system_fields = options[task]
    request = {"workflow_type": workflow_type, "idempotency_key": confirm_key(router_job["job_id"]),
               "input": target_input(router_job["job_id"], given, system_fields)}
    try:
        job, created = admit(store, request, max_queued=max_queued, catalog=catalog, request_id=request_id,
                             trace_parent=trace_parent, internal=True, link=(router_job["job_id"], CONFIRMED_EVENT))
    except AdmissionError as exc:
        if exc.code == "idempotency_conflict":
            raise IntakeError(409, "already_confirmed", "This answer was already confirmed as another task",
                              job_id=exc.extra.get("job_id")) from None
        raise IntakeError(exc.status, exc.code, exc.message, **exc.extra) from None
    return job, created, task


def reply(store, router_job, body, *, catalog, max_queued, request_id=None, trace_parent=None):
    """A person's answer to the router's question, as a new router job. Returns ``(job, created)``."""
    if not isinstance(body, dict) or set(body) != {"message", "idempotency_key"}:
        raise IntakeError(400, "invalid_fields", "A reply must contain exactly message and idempotency_key")
    if not isinstance(body["message"], str) or not body["message"].strip():
        raise IntakeError(400, "invalid_input", "message must be the answer, in text")
    key = body["idempotency_key"]
    if isinstance(key, str) and key.startswith(RESERVED_KEY_PREFIXES):
        raise IntakeError(400, "invalid_idempotency_key",
                          "idempotency_key must not start with " + " or ".join(RESERVED_KEY_PREFIXES))
    answer = router_answer(router_job, ANSWERABLE)
    message = router_job["input"]["message"] + "\n" + body["message"].strip()
    request = {"workflow_type": ROUTER, "idempotency_key": key,
               "input": {"message": message, "earlier": {"job_id": router_job["job_id"], "question": answer["question"]}}}
    try:
        return admit(store, request, max_queued=max_queued, catalog=catalog, request_id=request_id,
                     trace_parent=trace_parent, internal=True, link=(router_job["job_id"], REPLIED_EVENT))
    except AdmissionError as exc:
        raise IntakeError(exc.status, exc.code, exc.message, **exc.extra) from None


def came_from(job):
    """The router job a person confirmed (``how``: ``confirm``) or replied to (``reply``) to start this job, or
    ``None``. Read from the job's own record: its reserved key, or the router input's ``earlier``."""
    key = job.get("idempotency_key") or ""
    if key.startswith(CONFIRM_PREFIX):
        return {"job_id": key[len(CONFIRM_PREFIX):], "how": "confirm"}
    if job["workflow_type"] == ROUTER and (job.get("input") or {}).get("earlier"):
        return {"job_id": job["input"]["earlier"]["job_id"], "how": "reply"}
    return None


def links(store, job):
    """Where a job came from through the router, and the job a person started from this router job's proposal: ids
    only, for the job's detail view."""
    confirmed = store.job_by_key(confirm_key(job["job_id"])) if job["workflow_type"] == ROUTER else None
    return {"from": came_from(job), "confirmed_job_id": confirmed["job_id"] if confirmed else None}
