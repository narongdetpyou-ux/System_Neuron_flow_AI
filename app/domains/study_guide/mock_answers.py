"""Offline stand-ins for the study guide's two AI steps. They are keyword simulations, NOT AI models.

They exist so the whole workflow (retries, fallbacks, validators, the layered answer) runs on GitHub and
on the free Render service without an API key. What they get right says nothing about a real model.

* Topic detection: each topic has a short list of words and phrases taken from its own catalog examples.
  The topic with the most matches wins (``high`` confidence if no other topic matched, ``medium`` if one
  did, ``low`` on a tie, where the earlier topic in the catalog wins). No match means ``out_of_scope``.
  It cannot understand a metaphor whose words are not in the list; that is what a real model is for.
* Explanation: one sentence per step, built from the plan's own purpose text.

Every answer starts with "[จำลอง]" or "[simulated]", so nobody takes it for an AI answer.
"""

import json
import re

from app.llm.errors import InvalidModelOutput
from app.llm.providers import mock

from .contracts import DETECT_PROMPT_ID, EXPLAIN_PROMPT_ID
from .library import OUT_OF_SCOPE, load_library

_THAI = re.compile(r"[฀-๿]")
KEYWORDS = {
    "ai_basics": ("ai ทำงานยังไง", "เอา ai มา", "เรียนเรื่อง ai", "พื้นฐาน ai", "how does ai", "add ai",
                  "learning about ai", "machine learning"),
    "prompt_writing": ("prompt engineering", "เขียน prompt", "สั่ง ai", "เขียนสั่ง", "ตอบไม่ตรง", "สั่งงานเด็กใหม่",
                       "good prompt", "write a prompt", "misunderstanding", "briefing"),
    "ai_agents": ("agent", "เอเจนต์", "ทำงานแทน", "เป็นขั้น", "ทำต่อจนจบ", "เลขา", "ส่งงานต่อ", "หลายขั้น",
                  "step by step", "personal assistant", "assembly line", "workflow"),
    "staying_in_scope": ("ไม่เกี่ยวกับงาน", "ไม่ใช่หน้าที่", "รั้ว", "นอกลู่นอกทาง", "นอกกรอบ", "off-topic",
                         "not its job", "fence", "guardrail", "out of scope", "out-of-scope"),
    "prompt_injection": ("prompt injection", "injection", "หลอกให้ ai", "แอบซ่อนคำสั่ง", "ซ่อนคำสั่ง",
                         "จดหมายปลอม", "tricked", "hidden instruction", "forged", "jailbreak"),
    "intent_understanding": ("คำพูดธรรมดา", "พูดไม่เหมือนกัน", "จับใจความ", "เพื่อนสนิท", "คำเปรียบ",
                             "understand everyday words", "same thing in different ways", "get what i mean",
                             "old friend", "intent", "metaphor"),
    "recommender_systems": ("ระบบแนะนำ", "ก่อนหลัง", "จำได้ว่า", "อ่านอะไรต่อ", "เรียนอะไรต่อ", "recommender",
                            "recommend what", "learn next", "remembers what", "reading order"),
    "plain_language": ("คู่มือ", "อ่านรู้เรื่อง", "อ่านง่าย", "ภาษาคน", "ภาษาธรรมดา", "anyone can follow",
                       "full of jargon", "talk like a human", "plain language"),
    "layered_explanation": ("อธิบายสั้น", "ลงรายละเอียด", "มือใหม่ไม่งง", "ซูม", "ทีละชั้น", "explain briefly",
                            "go deeper", "overwhelming", "zoom", "layer by layer", "progressive disclosure"),
    "inclusive_learning": ("ทุกคนเรียนได้", "พื้นฐานไม่เท่ากัน", "ไม่ท้อ", "ทางลาด", "เท่าเทียม",
                           "different backgrounds", "not just experts", "ramp", "universal design"),
    "system_design": ("วางโครงระบบ", "รับงานเยอะ", "แบบแปลน", "ไม่พังง่าย", "system design", "fall over",
                      "much more work", "blueprint", "scalab"),
}


def language_of(text):
    return "th" if _THAI.search(text) else "en"


def detect(text, library=None):
    library = library or load_library()
    lowered = " ".join(text.casefold().split())
    scores = {topic.id: sum(word in lowered for word in KEYWORDS.get(topic.id, ())) for topic in library.topics}
    language = language_of(text)
    best = max(scores.values())
    if best == 0:
        restatement = {"th": "[จำลอง] คำขอนี้ไม่ตรงกับหัวข้อที่ผู้ช่วยแนะนำแหล่งเรียนได้",
                       "en": "[simulated] This request does not match a topic the study guide covers."}[language]
        return {"topic": OUT_OF_SCOPE, "confidence": "medium", "language": language, "restatement": restatement}
    winners = [topic_id for topic_id, score in scores.items() if score == best]  # catalog order
    topic = library.topic(winners[0])
    if len(winners) > 1:
        confidence = "low"
    elif any(score for topic_id, score in scores.items() if topic_id != topic.id):
        confidence = "medium"
    else:
        confidence = "high"
    restatement = {"th": f"[จำลอง] คุณอยากเรียนเรื่อง{topic.name.th}",
                   "en": f"[simulated] You want to learn about {topic.name.en}."}[language]
    return {"topic": topic.id, "confidence": confidence, "language": language, "restatement": restatement}


def _simulate_detect(prompt, text):
    return detect(text)


def _simulate_explain(prompt, text):
    try:
        plan = json.loads(text)
        language, steps = plan["language"], plan["steps"]
    except (ValueError, KeyError, TypeError):
        raise InvalidModelOutput("The mock could not read the study plan") from None
    notes = [name for name in prompt.output_schema["properties"] if name.startswith("note_")]
    if len(notes) != len(steps) or not steps:
        raise InvalidModelOutput("The mock got a plan whose steps do not match the answer fields")
    if language == "th":
        answer = {"summary": f"[จำลอง] เริ่มที่ {steps[0]['title']} แล้วค่อยไปต่อตามลำดับ"}
        answer.update({name: f"[จำลอง] {step['purpose']}" for name, step in zip(notes, steps)})
    else:
        answer = {"summary": f"[simulated] Start with {steps[0]['title']}, then follow the order."}
        answer.update({name: f"[simulated] {step['purpose']}" for name, step in zip(notes, steps)})
    return answer


mock.register_simulator(DETECT_PROMPT_ID, _simulate_detect)
mock.register_simulator(EXPLAIN_PROMPT_ID, _simulate_explain)
