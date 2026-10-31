"""Domain-independent, evidence-bound retrieval of reviewer-labelled cases.

Similarity is advisory; never treat nearest-neighbour retrieval as certification.
A caller is responsible for authenticating its human-review process.
"""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from .supervision import number, wire

PROFILE_DIMENSIONS = 6

def profile_vector(value):
    if not isinstance(value, list) or len(value) != PROFILE_DIMENSIONS:
        raise ValueError("Process profile requires exactly six numeric dimensions")
    for entry in value:
        number(entry, 0, 1, "profile dimension")
    return list(value)

def _bounded_bytes(value, label):
    if not isinstance(value, bytes) or not 1 <= len(value) <= 16 * 1024 * 1024:
        raise ValueError(f"{label} must be nonempty bytes <=16 MiB")
    return value

class CaseMemory:
    def __init__(self, workspace, max_records=1000):
        if type(max_records) is not int or not 1 <= max_records <= 10000:
            raise ValueError("max_records must be 1-10000")
        Path(workspace).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(workspace) / "case_memory.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS reviewed_cases (id TEXT PRIMARY KEY, evidence TEXT NOT NULL)")
        self.maximum = max_records

    def learn(self, source, reviewed, candidate, *, reviewer, profile, method, policy_version, cluster_id, split="train"):
        """Bind supplied bytes to a declared review; does not authenticate the reviewer."""
        vector = profile_vector(profile)
        if split != "train":
            raise ValueError("Only training evidence can enter case memory")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in
               (reviewer, method, policy_version, cluster_id)):
            raise ValueError("Reviewer, method, policy version and cluster identity are required")
        source = _bounded_bytes(source, "source")
        reviewed = _bounded_bytes(reviewed, "reviewed")
        candidate = _bounded_bytes(candidate, "candidate")
        record = {
            "schema": "portable-reviewed-case-v1", "split": split, "profile": vector,
            "method": method, "policy_version": policy_version, "cluster_id": cluster_id,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "review_sha256": hashlib.sha256(reviewed).hexdigest(),
            "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
            "reviewer": reviewer, "outcome": "MATCH" if candidate == reviewed else "MISMATCH",
            "label_scope": "Caller-declared review; reviewer identity is not authenticated"
        }
        content = wire(record).decode("utf-8")
        identifier = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self.db:
            previous = self.db.execute("SELECT evidence FROM reviewed_cases WHERE id=?", (identifier,)).fetchone()
            if previous is None:
                if self.db.execute("SELECT count(*) FROM reviewed_cases").fetchone()[0] >= self.maximum:
                    raise ValueError("MEMORY_FULL: archive reviewed cases explicitly")
                self.db.execute("INSERT INTO reviewed_cases VALUES (?,?)", (identifier, content))
            elif previous[0] != content:
                raise ValueError("Contradictory evidence")
        return {"case_id": identifier, "outcome": record["outcome"], "created": previous is None}

    def retrieve(self, profile, policy_version, *, limit=5, excluded_clusters=()):
        vector = profile_vector(profile)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1-100")
        results = []
        for identifier, content in self.db.execute("SELECT id,evidence FROM reviewed_cases"):
            record = json.loads(content)
            if (hashlib.sha256(content.encode()).hexdigest() != identifier
                    or record.get("schema") != "portable-reviewed-case-v1" or record.get("split") != "train"):
                raise ValueError("Invalid stored memory evidence")
            past = profile_vector(record["profile"])
            if record["policy_version"] != policy_version or record["cluster_id"] in excluded_clusters:
                continue
            distance = math.sqrt(sum((a-b)**2 for a,b in zip(vector,past)))
            results.append({
                "case_id": identifier, "distance": distance, "method": record["method"],
                "outcome": record["outcome"], "source_sha256": record["source_sha256"],
                "scope": "Advisory caller-labelled case; not a certification"
            })
        return sorted(results, key=lambda row: (row["distance"], row["case_id"]))[:limit]

    def close(self):
        self.db.close()
