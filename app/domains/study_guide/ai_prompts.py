"""The study guide's two prompts, completed with versioned data before each call (ADR-019).

* ``detect_prompt``: the file ``study_detect_topic_v1`` plus one line per catalog topic, and the answer's
  ``topic`` limited to the catalog's ids and ``out_of_scope``. The AI cannot answer a topic that does not
  exist.
* ``explain_prompt``: the file ``study_explain_v1`` plus one ``note_N`` field per step of the plan. The
  AI writes one note per step that code chose; it cannot add a step.
* ``explain_payload``: what the AI is told about the plan. It carries titles, purposes and levels, never a
  URL, so there is no link for the AI to copy or change; code adds the links afterwards.

Both prompt files keep their own SHA-256; the library's tag goes into the agent version next to it.
"""

import json

from app.llm import load_prompt
from app.llm.prompts import specialize

from .contracts import DETECT_PROMPT_ID, EXPLAIN_PROMPT_ID
from .library import OUT_OF_SCOPE


def detect_prompt(library):
    lines = []
    for topic in library.topics:
        examples = "; ".join(f'"{phrase}"' for phrase in topic.examples_en + topic.examples_th)
        lines.append(f"- {topic.id}: {topic.name.en} / {topic.name.th} - {topic.summary.en} "
                     f"Examples: {examples}")
    return specialize(load_prompt(DETECT_PROMPT_ID), extra_system_lines=lines,
                      enums={"topic": [topic.id for topic in library.topics] + [OUT_OF_SCOPE]})


def note_fields(count):
    return [f"note_{number}" for number in range(1, count + 1)]


def explain_prompt(step_count):
    return specialize(load_prompt(EXPLAIN_PROMPT_ID), extra_properties={
        name: f"One sentence, at most 200 characters, about step {name.split('_')[1]} of the plan only."
        for name in note_fields(step_count)})


def explain_payload(library, language, restatement, planned):
    """The plan as the AI sees it (a JSON text; the caller masks it like any other AI input)."""
    by_id = {resource.id: resource for resource in library.resources}
    topic = library.topic(planned["topic"])
    steps = []
    for step in planned["steps"]:
        resource = by_id[step["resource_id"]]
        steps.append({"step": step["order"], "title": resource.title, "by": resource.by, "kind": resource.kind,
                      "level": resource.level, "resource_language": resource.language,
                      "cost": resource.access, "priority": step["priority"],
                      "purpose": getattr(resource.purpose, language), "focus": getattr(resource.focus, language)})
    return json.dumps({"language": language, "request": restatement,
                       "topic": {"name": getattr(topic.name, language), "summary": getattr(topic.summary, language)},
                       "steps": steps}, ensure_ascii=False)
