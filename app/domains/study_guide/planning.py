"""The two rule steps of the study guide: which resources (``pick``) and in what order (``path``).

Both are pure functions of the library, the detected topic and the answer language, so a validator can
recompute them and compare. Nothing here reads the person's message or any other part of an AI answer.

**pick** (at most ``MAX_RESOURCES`` = 5, never anything outside the library):
1. the topic's own resources first, at most ``MAX_MAIN_RESOURCES`` = 3, ranked: in the person's language
   first (so Thai first for a Thai request), then free first, then easy first, then library order;
2. then one resource for each prerequisite topic (direct prerequisites before their own prerequisites),
   ranked the same way, while the budget lasts. A resource already chosen is not chosen twice;
3. prerequisite topics that got no resource are listed in ``prerequisites_left_out``, so the answer can
   say so honestly.

**path**: prerequisites first, basics before what builds on them; then the topic's own resources from easy
to hard. Each step gets a priority: ``prerequisite`` (skip it if you know it), ``core`` (the first of the
topic's own resources: the most important one) and ``later`` (can wait).
"""

from .contracts import MAX_MAIN_RESOURCES, MAX_RESOURCES
from .library import LEVELS


def _ranking(language):
    return lambda resource: (resource.language != language, resource.access != "free", LEVELS.index(resource.level))


def topic_chain(library, topic_id):
    """``topic_id`` and all its prerequisites, each after its own prerequisites (basics first), with the
    distance from ``topic_id`` (0 for itself, 1 for a direct prerequisite, …)."""
    order = []

    def visit(current):  # the library refuses prerequisite cycles, so this always ends
        for prerequisite in library.topic(current).prerequisites:
            if prerequisite not in order:
                visit(prerequisite)
        if current not in order:
            order.append(current)

    visit(topic_id)
    distance, frontier = {topic_id: 0}, [topic_id]
    while frontier:  # breadth first: the shortest number of prerequisite links
        following = []
        for current in frontier:
            for prerequisite in library.topic(current).prerequisites:
                if prerequisite not in distance:
                    distance[prerequisite] = distance[current] + 1
                    following.append(prerequisite)
        frontier = following
    return order, distance


def pick(library, topic_id, language):
    """The resources for ``topic_id`` (``None``: nothing to pick, for out_of_scope or no answer), for a
    person who wrote in ``language`` (``th`` or ``en``)."""
    if topic_id is None:
        return {"topic": None, "selection": [], "prerequisites_left_out": []}
    rank = _ranking(language)
    main = sorted(library.resources_for(topic_id), key=rank)[:MAX_MAIN_RESOURCES]
    selection = [{"resource_id": r.id, "topic": topic_id, "role": "main"} for r in main]
    chosen = {r.id for r in main}
    order, distance = topic_chain(library, topic_id)
    prerequisites = sorted((t for t in order if t != topic_id), key=lambda t: (distance[t], order.index(t)))
    left_out = []
    for prerequisite in prerequisites:
        candidates = [r for r in sorted(library.resources_for(prerequisite), key=rank) if r.id not in chosen]
        if len(selection) >= MAX_RESOURCES or not candidates:
            left_out.append(prerequisite)
            continue
        selection.append({"resource_id": candidates[0].id, "topic": prerequisite, "role": "prerequisite"})
        chosen.add(candidates[0].id)
    return {"topic": topic_id, "selection": selection,
            "prerequisites_left_out": sorted(left_out, key=order.index)}


def path(library, picked):
    """The study order for a :func:`pick` result."""
    topic_id = picked["topic"]
    if topic_id is None:
        return {"topic": None, "steps": [], "start_with": None}
    order, _ = topic_chain(library, topic_id)
    by_id = {resource.id: resource for resource in library.resources}
    prerequisites = [item for item in picked["selection"] if item["role"] == "prerequisite"]
    main = [item for item in picked["selection"] if item["role"] == "main"]
    prerequisites.sort(key=lambda item: order.index(item["topic"]))
    main.sort(key=lambda item: LEVELS.index(by_id[item["resource_id"]].level))  # stable: ties keep rank
    steps = []
    for item in prerequisites + main:
        if item["role"] == "prerequisite":
            priority = "prerequisite"
        else:
            priority = "core" if not any(step["priority"] == "core" for step in steps) else "later"
        steps.append({"order": len(steps) + 1, "resource_id": item["resource_id"], "topic": item["topic"],
                      "priority": priority})
    return {"topic": topic_id, "steps": steps, "start_with": steps[0]["resource_id"] if steps else None}
