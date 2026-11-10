"""The route table: which skill hands work to which, in which state, through which translators (ADR-030).

Versioned data, ``routes_v1.json``, with the complete SHA-256 of the file in its tag (``routes-v1@sha256:…``). A
route has no condition in this version: it applies to every job of its source skill that reaches its state.
The checks against the catalog, the translators and the vocabulary are in :class:`app.exchange.Exchange`.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .common import HERE, tagged

ROUTES_FILE = HERE / "routes_v1.json"
START_STATES = ("COMPLETED", "APPROVED")  # informational (ADR-018) or decided by a person (ADR-027)
ROUTE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")  # fits the target's idempotency key handoff:<job>:<route>
MAX_DEPTH_LIMIT = 3
_FIELDS = {"id", "from", "on", "to", "out", "in", "needs", "why"}


@dataclass(frozen=True)
class Route:
    id: str
    source: str
    on: str
    target: str
    out: str
    inp: str
    needs: tuple
    why: dict

    def view(self):
        return {"id": self.id, "from": self.source, "on": self.on, "to": self.target, "out": self.out,
                "in": self.inp, "needs": list(self.needs), "why": dict(self.why)}


@dataclass(frozen=True)
class RouteTable:
    version: str
    tag: str
    max_depth: int
    routes: tuple

    @classmethod
    def load(cls, path=ROUTES_FILE):
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("version"), str):
            raise ValueError("A route table names its version")
        return cls.parse(data, tagged(data["version"], raw))

    @classmethod
    def parse(cls, data, tag):
        """Shape checks only; :class:`app.exchange.Exchange` checks the table against what the process runs."""
        if set(data) != {"version", "max_depth", "routes"}:
            raise ValueError("A route table holds exactly version, max_depth and routes")
        depth = data["max_depth"]
        if type(depth) is not int or not 1 <= depth <= MAX_DEPTH_LIMIT:
            raise ValueError(f"max_depth must be 1-{MAX_DEPTH_LIMIT}")
        routes = []
        for item in data["routes"]:
            if not isinstance(item, dict) or set(item) != _FIELDS:
                raise ValueError("A route holds exactly: " + ", ".join(sorted(_FIELDS)))
            if not isinstance(item["id"], str) or not ROUTE_ID.fullmatch(item["id"]):
                raise ValueError("A route id is 3-64 lower-case letters, digits or '-'")
            if item["on"] not in START_STATES:
                raise ValueError(f"Route {item['id']} may start only from {', '.join(START_STATES)}")
            needs = item["needs"]
            if not isinstance(needs, list) or not needs or len(set(needs)) != len(needs):
                raise ValueError(f"Route {item['id']} needs a list of distinct facts")
            if set(item["why"]) != {"en", "th"}:
                raise ValueError(f"Route {item['id']} says why in English and Thai")
            routes.append(Route(item["id"], item["from"], item["on"], item["to"], item["out"], item["in"],
                                tuple(needs), dict(item["why"])))
        ids = [route.id for route in routes]
        if len(set(ids)) != len(ids):
            raise ValueError("Route ids must be unique")
        return cls(data["version"], tag, depth, tuple(routes))
