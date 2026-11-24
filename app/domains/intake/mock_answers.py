"""Offline stand-in for the router's AI step (``intake_understand_v1``). A keyword simulation, NOT an AI model.

It exists so the router's whole workflow (retries, the rules, every kind of answer, the scorecard) runs on GitHub
and on the free Render page without an API key. What it gets right says nothing about a real model, and it cannot
read a metaphor or a paraphrase whose words it does not list.

* A customer's problem: the triage simulation's own keyword lists (``app/llm/providers/mock.py``), plus the words
  for "customer". A wish to learn: a short list of phrases for wanting to learn or understand. Neither list was
  chosen from the router's evaluation sets.
* The task with more matches wins (``high`` when only one task matched, ``medium`` when both did, ``low`` on a tie,
  where the frame's order decides). No match is ``out_of_scope``.
* A matched message shorter than ``SHORT`` visible characters is taken as saying too little (``needs_more``).
* ``also_study`` is always ``no``: the simulation cannot judge it.

Every restatement starts with "[จำลอง]" or "[simulated]", so nobody takes it for an AI answer.
"""

import re

from app.llm.providers import mock

from .contracts import OUT_OF_SCOPE, UNDERSTAND_PROMPT_ID, language_of, visible_length

CASE_WORDS = tuple(word for words in mock.KEYWORDS.values() for word in words) + ("ลูกค้า", "customer")
STUDY_WORDS = ("อยากเรียน", "อยากรู้", "อยากเข้าใจ", "เริ่มเรียน", "ศึกษา", "learn", "study", "understand how",
               "where should i start")
WORDS = {"case_triage": CASE_WORDS, "study_guide": STUDY_WORDS}
SHORT = 15
# One frame line of the completed prompt: "- <task id>: <English name> / <Thai name> - ..."
_LINE = re.compile(r"^- ([a-z][a-z0-9_]*): (.+?) / (.+?) - ")


def understand(prompt, text):
    names = {match.group(1): {"en": match.group(2), "th": match.group(3)}
             for match in map(_LINE.match, prompt.system.splitlines()) if match}
    tasks = [task for task in prompt.output_schema["properties"]["task"]["enum"] if task != OUT_OF_SCOPE]
    lowered = " ".join(text.casefold().split())
    scores = {task: sum(word in lowered for word in WORDS.get(task, ())) for task in tasks}
    language = language_of(text)
    best = max(scores.values(), default=0)
    if best == 0:
        restatement = {"th": "[จำลอง] ข้อความนี้ไม่ตรงกับงานที่ระบบช่วยได้",
                       "en": "[simulated] This message does not match a task the system can help with."}[language]
        return {"task": OUT_OF_SCOPE, "confidence": "medium", "language": language, "needs_more": "no",
                "also_study": "no", "restatement": restatement}
    winners = [task for task in tasks if scores[task] == best]  # the frame's order
    task = winners[0]
    if len(winners) > 1:
        confidence = "low"
    elif any(score for other, score in scores.items() if other != task):
        confidence = "medium"
    else:
        confidence = "high"
    name = names.get(task, {"th": task, "en": task})
    restatement = {"th": f"[จำลอง] เข้าใจว่าเป็นเรื่อง: {name['th']}",
                   "en": f"[simulated] This looks like: {name['en']}."}[language]
    return {"task": task, "confidence": confidence, "language": language,
            "needs_more": "yes" if visible_length(text) < SHORT else "no", "also_study": "no",
            "restatement": restatement}


mock.register_simulator(UNDERSTAND_PROMPT_ID, understand)
