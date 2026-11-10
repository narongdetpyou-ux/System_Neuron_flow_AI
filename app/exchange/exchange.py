"""The exchange: the one go-between of the skills (ADR-030).

For a job that has just reached ``COMPLETED`` or ``APPROVED``, :meth:`Exchange.prepare` looks up the route for its
skill and state and returns a *plan*, a plain dict the queue store writes in the same transaction as the job's new
state (``QueueStore.finish`` and ``QueueStore.decide`` take it as their ``handoff`` builder):

1. the source's out-translator turns the job's record into facts;
2. every fact is checked against the vocabulary, and only the facts the route needs are kept (the rest, such as a
   person's words, never travel);
3. the target's in-translator turns the kept facts into the target's own input, which must pass the target's own
   ``check_input``, exactly as a request from outside would;
4. the plan carries the target's queue row: a new job id, the idempotency key ``handoff:<source>:<route>`` and the
   request fingerprint of normal admission.

A step that cannot be done refuses the handoff with a reason code and nothing is guessed; the source keeps its
outcome. ``prepare`` never raises for a translation problem. The exchange never opens Core's ``Runtime`` and reads
nothing but the queue record it is given (ADR-001).
"""

import secrets

from neuron_flow import SpecError
from neuron_flow.model import fingerprint

from app.persistence.queue_store import iso
from app.services.admission import new_job_id, request_fingerprint

from .common import FactInvalid, Vocabulary
from .routes import RouteTable
from .translators import TRANSLATORS, SourceIncomplete, SourceView

ENVELOPE_VERSION = "handoff-envelope-v1"
REASONS = ("source_incomplete", "fact_invalid", "fact_missing", "target_input_invalid", "chain_too_long",
           "translator_error")
STARTED, REFUSED = "STARTED", "REFUSED"


class ExchangeConfigError(ValueError):
    """The route table does not fit what this process runs. Raised at start; the committed table is tested."""


class Exchange:
    def __init__(self, catalog, *, table=None, vocabulary=None, translators=None):
        self.catalog = catalog
        self.table = table or RouteTable.load()
        self.vocabulary = vocabulary or Vocabulary.load()
        self.translators = TRANSLATORS if translators is None else translators
        # Routes whose source this process does not run can never fire here; a test catalog may leave them out.
        self.routes = tuple(route for route in self.table.routes if route.source in catalog)
        self._by_source = {}
        self._check()

    # -- checks at start -------------------------------------------------------------------------

    def _check(self):
        for route in self.routes:
            where = f"Route {route.id}"
            if route.target not in self.catalog:
                raise ExchangeConfigError(f"{where}: its target {route.target} is not in the catalog")
            if (route.source, route.on) in self._by_source:
                raise ExchangeConfigError(f"{where}: one route per skill and state ({route.source}, {route.on})")
            out, inp = self.translators.get(route.out), self.translators.get(route.inp)
            if out is None or out.direction != "out" or out.workflow_type != route.source or route.on not in out.states:
                raise ExchangeConfigError(f"{where}: {route.out} is not an out-translator of {route.source} for {route.on}")
            if inp is None or inp.direction != "in" or inp.workflow_type != route.target:
                raise ExchangeConfigError(f"{where}: {route.inp} is not an in-translator of {route.target}")
            unknown = set(route.needs) - set(self.vocabulary.facts)
            if unknown:
                raise ExchangeConfigError(f"{where}: facts outside the vocabulary: {sorted(unknown)}")
            if not set(route.needs) <= set(out.facts):
                raise ExchangeConfigError(f"{where}: {route.out} cannot give {sorted(set(route.needs) - set(out.facts))}")
            if not set(inp.facts) <= set(route.needs):
                raise ExchangeConfigError(f"{where}: {route.inp} reads facts the route does not carry")
            self._by_source[(route.source, route.on)] = route
        self._check_no_cycle()

    def _check_no_cycle(self):
        edges = {}
        for route in self.routes:
            edges.setdefault(route.source, set()).add(route.target)
        done, path = set(), []

        def visit(node):
            if node in path:
                raise ExchangeConfigError("Routes form a cycle: " + " -> ".join(path[path.index(node):] + [node]))
            if node in done:
                return
            path.append(node)
            for nxt in sorted(edges.get(node, ())):
                visit(nxt)
            path.pop()
            done.add(node)

        for node in sorted(edges):
            visit(node)

    # -- views -----------------------------------------------------------------------------------

    def route_for(self, workflow_type, state):
        return self._by_source.get((workflow_type, state))

    def view(self):
        """The routes and the language in plain words, for ``/v1/status`` and the page; never a fact value."""
        return {"routes_version": self.table.tag, "vocabulary_version": self.vocabulary.tag,
                "envelope_version": ENVELOPE_VERSION, "max_depth": self.table.max_depth,
                "routes": [route.view() for route in self.routes], "origins": dict(self.vocabulary.origins),
                "facts": self.vocabulary.view(), "reasons": list(REASONS)}

    def handoff_view(self, row):
        """One recorded handoff for the API and the page: ids, versions, state and the facts it carried.

        A ``choice`` or ``id`` fact shows its value (a fixed code or an id); a ``text`` fact only its length, because
        it may be a person's words. The envelope itself stays in the queue database.
        """
        envelope = row.get("envelope") or {}
        facts = []
        for name, item in (envelope.get("facts") or {}).items():
            shown = {"name": name, "origin": item.get("origin")}
            if (self.vocabulary.facts.get(name) or {}).get("type") == "text":
                shown["chars"] = len(item.get("value") or "")
            else:
                shown["value"] = item.get("value")
            facts.append(shown)
        return {"handoff_id": row["handoff_id"], "route_id": row["route_id"], "state": row["state"],
                "reason": row["reason"], "source_job_id": row["source_job_id"], "source_state": row["source_state"],
                "target_job_id": row["target_job_id"], "target_workflow_type": row["target_workflow_type"],
                "depth": row["depth"], "translator_out": row["translator_out"], "translator_in": row["translator_in"],
                "routes_version": row["routes_tag"], "vocabulary_version": row["vocabulary_tag"],
                "envelope_sha256": row["envelope_sha256"], "facts": facts, "left_out": list(envelope.get("left_out", [])),
                "created_at": iso(row["created_at"])}

    # -- one handoff -----------------------------------------------------------------------------

    def prepare(self, job, *, decision=None, depth=0):
        """The handoff plan for ``job`` in its current state, or ``None`` when no route starts from it.

        ``job`` is the queue record (its ``status`` already the new state), ``decision`` the decision row for
        ``APPROVED``, ``depth`` how many handoffs led to ``job`` (0 for a job admitted from outside).
        """
        route = self.route_for(job["workflow_type"], job["status"])
        if route is None:
            return None
        plan = {"handoff_id": "hof_" + secrets.token_hex(12), "route_id": route.id, "routes_tag": self.table.tag,
                "vocabulary_tag": self.vocabulary.tag, "translator_out": route.out, "translator_in": route.inp,
                "source_job_id": job["job_id"], "source_state": job["status"], "target_workflow_type": route.target,
                "depth": depth + 1, "state": REFUSED, "reason": None, "error_type": None, "envelope": None,
                "target": None}

        def refuse(reason, error=None):
            plan["reason"], plan["error_type"] = reason, error
            return plan

        if depth + 1 > self.table.max_depth:
            return refuse("chain_too_long")
        out, inp = self.translators[route.out], self.translators[route.inp]
        source = SourceView(job["workflow_type"], job["status"], job["input"], job.get("result"), decision)
        try:
            given = out.function(source)
        except SourceIncomplete:
            return refuse("source_incomplete")
        except Exception as exc:  # a bug in a translator refuses this handoff; it never breaks the decision
            return refuse("translator_error", type(exc).__name__)
        if not isinstance(given, dict):
            return refuse("translator_error", type(given).__name__)
        for name in sorted(given):
            if name not in out.facts:  # a translator gives only what it declares
                return refuse("fact_invalid")
            try:
                self.vocabulary.check(name, given[name])
            except FactInvalid:
                return refuse("fact_invalid")
        if any(name not in given for name in route.needs):
            return refuse("fact_missing")
        facts = {name: dict(given[name]) for name in route.needs}
        plan["envelope"] = {
            "envelope": ENVELOPE_VERSION, "route": route.id, "routes": self.table.tag,
            "vocabulary": self.vocabulary.tag,
            "source": {"job_id": job["job_id"], "workflow_type": job["workflow_type"], "state": job["status"],
                       "result_sha256": fingerprint(job.get("result"))},
            "out": route.out, "depth": depth + 1, "facts": facts,
            "left_out": sorted(set(given) - set(route.needs)),  # given by the translator, not needed: not carried
        }
        try:
            raw = inp.function({name: facts[name] for name in inp.facts})
        except Exception as exc:
            return refuse("translator_error", type(exc).__name__)
        target = self.catalog[route.target]
        try:
            normalized = target.check_input(raw)
            digest = request_fingerprint(target.name, normalized)
        except SpecError:
            return refuse("target_input_invalid")
        plan.update(state=STARTED, target={
            "job_id": new_job_id(), "idempotency_key": f"handoff:{job['job_id']}:{route.id}",
            "request_fingerprint": digest, "workflow_type": target.name, "input": normalized})
        return plan
