"""Portable deterministic assignment and paired candidate-regression gates."""
import hashlib
from .supervision import number, wire
from .telemetry import percentile

def route_variant(cluster_id, fraction=.1, salt="neuron-trial-v1"):
    number(fraction, 0, 1, "fraction")
    if not isinstance(cluster_id, str) or not cluster_id or not isinstance(salt, str) or not salt:
        raise ValueError("Explicit stable cluster identity and salt required")
    uniform = int.from_bytes(hashlib.sha256((salt + ":" + cluster_id).encode()).digest()[:8], "big") / 2**64
    return "candidate" if uniform < fraction else "reference"

def candidate_gate(reference, candidate, *, training_clusters=(), max_p95_ratio=None, max_attempt_ratio=None):
    """Compare matching case IDs and source hashes; metrics are caller-supplied."""
    required = {"case_id","cluster_id","split","source_sha256","group","outcome","latency_ms","attempts","first_method_success"}
    def collection(rows):
        if not isinstance(rows, list) or not rows:
            raise ValueError("A non-empty evaluation population is required")
        indexed = {}
        for row in rows:
            if (not isinstance(row, dict) or set(row) != required
                    or any(not isinstance(row[k],str) or not row[k] for k in
                           ("case_id","cluster_id","source_sha256","group","outcome"))
                    or row["case_id"] in indexed or row["split"] not in {"validation","holdout"}
                    or type(row["first_method_success"]) is not bool or type(row["attempts"]) is not int):
                raise ValueError("Invalid or duplicate evaluation case")
            number(row["latency_ms"], 0, 1e12, "latency_ms")
            number(row["attempts"], 1, 100, "attempts")
            indexed[row["case_id"]] = row
        return indexed
    ref, cur = collection(reference), collection(candidate)
    if ref.keys() != cur.keys():
        raise ValueError("Different evaluation case identities")
    splits, sources, groups, group_ids, comparisons = {}, {}, {}, {}, []
    for identifier, before in ref.items():
        after = cur[identifier]
        if any(before[k] != after[k] for k in ("cluster_id","split","source_sha256","group")):
            raise ValueError("Different population identity or source bytes")
        cluster, split, source = before["cluster_id"], before["split"], before["source_sha256"]
        if cluster in training_clusters or (cluster in splits and splits[cluster] != split):
            raise ValueError("Training/validation/holdout cluster leakage")
        if source in sources and sources[source] != split:
            raise ValueError("Source overlaps validation and holdout")
        splits[cluster], sources[source] = split, split
        agreement = before["outcome"] == after["outcome"]
        comparisons.append({"case_id": identifier, "agreement": agreement})
        group = before["group"]
        groups.setdefault(group, {"cases":0,"regressions":0})
        group_ids.setdefault(group, []).append(identifier)
        groups[group]["cases"] += 1
        groups[group]["regressions"] += not agreement
    failures = []
    if any(not c["agreement"] for c in comparisons):
        failures.append("SEMANTIC_REGRESSION")
    for name, limit, field, aggregate in [
        ("LATENCY_REGRESSION",max_p95_ratio,"latency_ms",lambda v: percentile(v,.95)),
        ("ATTEMPT_REGRESSION",max_attempt_ratio,"attempts",sum)
    ]:
        if limit is None:
            continue
        number(limit, 1, 100, name)
        if (any(aggregate([cur[i][field] for i in ids]) >
                aggregate([ref[i][field] for i in ids])*limit for ids in group_ids.values())
                or aggregate([r[field] for r in candidate]) > aggregate([r[field] for r in reference])*limit):
            failures.append(name)
    if sum(r["first_method_success"] for r in candidate) < sum(r["first_method_success"] for r in reference):
        failures.append("FIRST_METHOD_REGRESSION")
    population = sorted((key,row["cluster_id"],row["split"],row["source_sha256"]) for key,row in ref.items())
    return {"schema":"portable-candidate-gate-v1","accepted":not failures,"failure_reasons":failures,
            "dataset_sha256":hashlib.sha256(wire(population)).hexdigest(),
            "cases":len(ref),"independent_clusters":len(splits),"groups":groups,"comparisons":comparisons,
            "scope":"Paired declared outcomes and metrics; no independently authenticated ground truth"}
