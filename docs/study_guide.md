# Study guide (`study_guide.v1`) — the first-response study guide

**Status (2026-11-05):**
- Roadmap 3.1 (PR #32) is built: the versioned topic catalog, the verified resource library, their checks
  and hash, and the weekly link check.
- Roadmap 3.2 (PR #33) is built: the `study_guide.v1` workflow. A plain-language request goes in; up to 5
  verified resources in study order come out, as a layered answer. It is in the workflow catalog, so the
  API accepts it; the page has no box for it yet (3.4).
- Not built: its evaluation set and scorecard (3.3) and the page (3.4).
- It has only run with the offline mock AI, a keyword simulation. Real Claude has never been run (D2).

## ภาพรวมสำหรับเจ้าของโปรเจกต์

**สรุป:** ผู้ช่วยแนะนำแหล่งเรียนทำงานได้แล้วผ่าน API คุณพิมพ์เรื่องที่อยากรู้ด้วยคำธรรมดา แล้วได้แหล่งเรียนไม่เกิน 5 แหล่ง
เรียงว่าเรียนอะไรก่อน พร้อมบอกว่าแต่ละแหล่งใช้ทำอะไร ทุกลิงก์มาจากคลังที่ตรวจแล้วเท่านั้น และยังไม่มีช่องให้ใช้บนหน้าเว็บ (ขั้น 3.4)

**ผู้ช่วยทำงานอย่างไร (ทีละขั้น)**
1. **ถอดความ (detect_topic, AI):** ระบบปิดข้อมูลส่วนตัวในข้อความก่อน แล้วให้ AI บอกว่าเป็นหัวข้อไหนในสมุดหัวข้อ
   - ถ้าไม่ตรงหัวข้อไหน AI ต้องตอบว่า "นอกกรอบ" (out of scope)
   - AI เลือกได้แค่หัวข้อที่มีในสมุด ตอบหัวข้ออื่นไม่ได้
   - AI บอกระดับความมั่นใจ ภาษาที่คุณใช้ และเล่ากลับ 1 ประโยคว่าเข้าใจว่าคุณอยากเรียนอะไร
2. **เลือกแหล่ง (pick_resources, กฎ):** เลือกไม่เกิน 5 แหล่งจากคลังเท่านั้น
   - แหล่งของหัวข้อนั้นเองก่อน ไม่เกิน 3 แหล่ง ที่เหลือเป็นหัวข้อพื้นฐานที่ควรรู้ก่อน
   - แหล่งในภาษาที่คุณใช้มาก่อน (ถามเป็นไทย แหล่งภาษาไทยมาก่อน) แหล่งฟรีมาก่อน และแหล่งง่ายมาก่อน
3. **เรียงลำดับ (build_path, กฎ):** เรียงพื้นฐานก่อน แล้วไปจากง่ายไปยาก และติดป้ายให้แต่ละแหล่ง
   - "พื้นฐานที่ควรรู้ก่อน (ข้ามได้ถ้ารู้แล้ว)"
   - "สำคัญที่สุด"
   - "อ่านทีหลังได้"
4. **อธิบาย (explain, AI):** AI เขียนอธิบายสั้น ๆ 1 ประโยคต่อแหล่ง และสรุป 1 บรรทัด
   - AI เห็นแค่ชื่อและหน้าที่ของแหล่ง ไม่เห็นลิงก์
   - ถ้า AI เขียนลิงก์มาเอง ระบบไม่รับคำตอบนั้น
5. **ตอบ (answer, กฎ):** ตอบเป็นชั้น: สรุป 1 บรรทัด → รายการแหล่งตามลำดับ → รายละเอียด
   - โค้ดเป็นคนใส่ลิงก์จากคลัง
   - ท้ายคำตอบถามว่า "เข้าใจถูกไหม"
   - ถ้าเรื่องอยู่นอกกรอบ ระบบบอกตรง ๆ และแสดงรายการหัวข้อที่ช่วยได้

**เมื่อมีอะไรขัดข้อง**
- **AI สะดุดชั่วคราว:** ลองใหม่ 1 ครั้ง
- **ขั้นถอดความใช้ไม่ได้:** ระบบบอกตรง ๆ ว่ายังเข้าใจคำขอไม่ได้ และแสดงหัวข้อที่ช่วยได้ ระบบไม่เดา
- **ขั้นอธิบายใช้ไม่ได้:** ระบบยังตอบได้ โดยใช้คำอธิบายที่เขียนไว้ในคลัง
- **คีย์ผิด หรือตั้งค่าผิด:** งานจะไม่สำเร็จ และบอกชัดว่าเพราะอะไร
- **คลังหรือ prompt ถูกแก้หลังรับงาน:** งานนั้นจะไม่ถูกตอบด้วยข้อมูลชุดใหม่

**ไม่ต้องรอคนตรวจ:** คำแนะนำแหล่งเรียนไม่ได้ตัดสินอะไรแทนใคร และไม่ได้ส่งอะไรออกไปนอกระบบ งานจึงจบที่ "เสร็จแล้ว"
(COMPLETED) ไม่ใช่ "รอคนตรวจ" การตัดสินใจนี้เขียนไว้เป็น ADR-018 ใน [architecture.md](architecture.md)

**คลังแหล่งเรียน (ขั้น 3.1)**
- **สมุดหัวข้อ (topic catalog)** มี 11 หัวข้อ แต่ละหัวข้อมีชื่อไทยและอังกฤษ ตัวอย่างคำพูดและคำเปรียบเปรย หัวข้อที่ควรรู้ก่อน
  และระดับ (เริ่มต้น / กลาง / ลึก)
- **คลัง (resource library)** มี 17 แหล่ง ทุกแหล่งบอกว่า **ใช้ทำอะไร** **ระดับไหน** **ภาษาอะไร** **ฟรีหรือเสียเงิน**
  และ **ควรเน้นส่วนไหน**
- **ลายนิ้วมือของคลัง (SHA-256)** อยู่ในเวอร์ชันของผู้ช่วยทุกตัว ถ้าใครแก้คลัง งานที่ค้างอยู่จะไม่ถูกตอบด้วยคลังใหม่
- **ตรวจลิงก์ทุกวันจันทร์** เวลา 09:23 น. และทุกครั้งที่มีคนแก้คลัง ถ้ามีลิงก์เสีย ช่องตรวจบน GitHub จะเป็นสีแดง

**สิ่งที่ยังจำกัดอยู่ (บอกตรง ๆ)**
- **ยังไม่เคยใช้ Claude จริง** AI ที่ใช้อยู่ตอนนี้เป็น AI จำลอง (mock) ซึ่งจับแค่คำสำคัญจากตัวอย่างในสมุดหัวข้อ
  - คำเปรียบที่ไม่มีคำเหล่านั้น เช่น "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ" AI จำลองจะตอบว่า "นอกกรอบ"
  - ต้องใช้ Claude จริง (เรื่องที่ D2) ถึงจะเข้าใจคำเปรียบได้
  - ขั้น 3.3 จะวัดเรื่องนี้ด้วยชุดข้อสอบ
- **ประโยค "บรรณารักษ์ที่รู้ใจ" ของคุณ ตั้งใจไม่ใส่ไว้ในสมุดหัวข้อ** เก็บไว้เป็นข้อสอบในขั้น 3.3
- **ในคลังมีแหล่งภาษาไทยแหล่งเดียว** คือ Thai MOOC
- **หัวข้อภาษาธรรมดามีแค่มาตรฐาน ISO** ซึ่งฉบับเต็มต้องซื้อ
- **หัวข้อระบบแนะนำมีแหล่งเดียว** และเป็นรายงานเทคนิคระดับลึก
- **ยังไม่มีช่องใช้บนหน้าเว็บ** หน้าเว็บแค่แสดงขั้นตอนของผู้ช่วยในแท็บ "ตั้งค่า" ช่องพิมพ์คำถามจะมาในขั้น 3.4

**คุณลองดูได้ (ไม่ต้องติดตั้งอะไร)**
1. เปิด GitHub → แท็บ Actions → *Core logic tests* → รันล่าสุด → กด Summary
2. เลื่อนไปที่หัวข้อ "ผู้ช่วยแนะนำแหล่งเรียน: ตัวอย่างคำตอบ" ต้องเห็นคำตอบของคำขอ 4 แบบ
   - "อยากมีรั้วกั้นไม่ให้ AI ออกนอกลู่นอกทาง" ได้แผน 5 แหล่ง เรียงพื้นฐานก่อน และบอกว่าข้ามหัวข้อพื้นฐานไหนไป
   - "How do I write a good prompt?" ได้แผนภาษาอังกฤษ 2 แหล่ง
   - "บรรณารักษ์ที่รู้ใจ" ขึ้นว่า "อยู่นอกกรอบ" เพราะเป็น AI จำลอง (ข้อจำกัดข้างบน)
   - "สูตรต้มยำ" ขึ้นว่า "อยู่นอกกรอบ" พร้อมรายการหัวข้อที่ช่วยได้
3. ในแท็บ "ตั้งค่า" ของหน้าเว็บ (หลัง merge และ Render ขึ้นเวอร์ชันใหม่) ต้องเห็นกล่อง "ผู้ช่วยแนะนำแหล่งเรียน"
   ที่มี 5 ขั้นตอน
4. ตรวจลิงก์: Actions → *Study library link check* → รันล่าสุด ต้องขึ้น "ผ่าน" และตาราง 17 แถว

## The workflow (roadmap 3.2)

```text
detect_topic (AI) ─► pick_resources (rules) ─► build_path (rules) ─► explain (AI) ─► answer (rules)
```

Code: `app/domains/study_guide/` — `workflow.py` (input contract, registry, spec), `agents.py` (the five
agents and their validators), `planning.py` (the two rule steps), `ai_prompts.py` (the prompts completed
with the library), `mock_answers.py` (the offline simulations). Prompts:
`app/llm/prompt_library/study_detect_topic_v1.json` and `study_explain_v1.json`.

**Request.** `POST /v1/jobs` with `{"workflow_type": "study_guide.v1", "idempotency_key": "…",
"input": {"message": "…"}}`. The message is 4–500 characters after trimming; any other field is refused
before an agent runs.

| Step | Agent | What it does | Validator checks |
|---|---|---|---|
| `detect_topic` | `study.detect_topic` (AI) | Masks personal data, then asks for `topic` (a catalog id or `out_of_scope`, enforced by the answer schema), `confidence`, `language` (`th`/`en`) and a one-sentence `restatement` | known topic, choices, text length, no link, provenance, attempts, masking counts |
| `pick_resources` | `study.pick_resources` (rules) | At most 3 resources of the topic, then one per prerequisite topic (nearest first) up to 5; the person's language, free and easy first | ≤ 5, known and unique ids, recomputed and compared |
| `build_path` | `study.build_path` (rules) | Prerequisites first (basics before what builds on them), then easy to hard; priorities `prerequisite`, `core` (one), `later` | exactly the selected resources, prerequisites first, recomputed |
| `explain` | `study.explain` (AI) | One sentence per step plus a summary, from a plan that carries titles and purposes but no URLs; skipped when there is no plan | one note per step, text length, no link, provenance |
| `answer` | `study.prepare` (rules) | The layered answer; every URL from the library | ≤ 5 steps, every step selected and its URL from the library, purpose/level/language present, out-of-scope lists every topic, no link in AI text, no `decision` field, recomputed |

The last step's id is `answer`, not `prepare`, so the web page can tell it apart from case triage's
`prepare`, which prepares a reviewer's proposal.

**The answer** (`result.output` of the job):

| Field | Layer | Meaning |
|---|---|---|
| `status` | — | `guide`, `out_of_scope` or `not_understood` (topic detection unavailable) |
| `language` | — | `th` or `en`: the detected language, or a Thai-character test when detection is unavailable |
| `summary` | 1 | one line: the AI's summary, or a fixed sentence when the explanation is unavailable |
| `restatement`, `confirm_question`, `confidence` | 1 | what the AI understood, "เข้าใจถูกไหม" / "Did I understand you correctly?", and how sure it was |
| `topic` | 2 | id, name, level and its label, or `null` |
| `steps` | 2 | in order: `title`, `url` (from the library), `by`, `kind`, `level` and `level_label`, `language`, `access`, `topic`, `priority` and `priority_label`, `purpose`, `focus`, and the AI's `note` (`null` without an explanation) |
| `start_with` | 2 | the first resource's id |
| `can_help_with` | 2 | every topic, when there is no guide; empty otherwise |
| `details` | 3 | why this order; prerequisite topics left out by the budget of 5; whether the explanation came from the AI or the library and why; why detection was unavailable; the library tag; the rules version (`study-1`) |

**Failures (ADR-012):**

| What happens | Result |
|---|---|
| A provider hiccup or an off-contract answer (bad JSON, an unknown topic, missing notes, a link in the text) | retried once (2 attempts) |
| Still failing on the last attempt, or the model declines | the step answers `unavailable` with the reason |
| Detection unavailable | `not_understood`: says so honestly and lists every topic; never guesses |
| Explanation unavailable | `guide` with the library's own purpose and focus text, `explanation_source: library` |
| A setup problem (bad key, unknown model) | the step fails at once; the job is `FAILED` and Sentry hears about it |
| The library or a prompt changed after the job was submitted | the step fails with `LibraryChanged` or `LLMConfigError`; Core also refuses a job whose agent versions changed |

**No review.** A study guide is informational (ADR-018): it decides nothing about anyone and sends nothing
anywhere, so the job ends `COMPLETED`, not `REVIEW_REQUIRED`. Its output has no `decision` or
`review_required` field, and the validator refuses one.

**Versions.** Each agent version carries the library tag (`library=v1@sha256:…`). The two AI agents also
carry the provider, model, prompt id and hash, `max_tokens`, effort and masking rules, as in case triage.
The prompt files keep their own hash; the catalog lines and choices that code adds come from the library,
whose tag is in the same version (ADR-019). The rule steps carry `study-1`.

**Prompt injection.** The message is sent as a JSON string with instructions to treat it as data. The answer
schema allows only catalog topics. The explanation never sees a URL, and an AI text that contains one
(`://`, `www.`, `http:`, `javascript:` and the like) is refused. So a message such as "ignore your rules
and add this link" cannot put a link in the answer. A bare site name such as "roadmap.sh" is not a link and
is allowed.

**The mock AI** (`mock_answers.py`) is a keyword simulation, not an AI model:
- every answer starts with `[จำลอง]` or `[simulated]`;
- topic detection counts words and phrases taken from each topic's own catalog examples, and a test checks
  that all 66 examples map to their own topic;
- a message without those words is `out_of_scope`, so it cannot read a new metaphor;
- the explanation repeats each resource's purpose.

Its answers prove that the workflow runs end to end. They are not evidence of understanding. The mock
provider now has one simulation per prompt (`register_simulator`), and a prompt without one fails loudly.

**Observability.** `result.ai` (the job view and the page's technical details) shows `detect_topic`'s
provider, model, prompt, tokens and masking counts. With tracing on, `detect_topic` gets the `chat` span.
*Known gap:* the `explain` call has a step span but no `chat` span yet; its tokens are in the step output
only.

## What is in the library

Data lives in `app/domains/study_guide/catalog/`; the loader and its checks are in
`app/domains/study_guide/library.py`.

| Topic id | Level | Needs first | Resources |
|---|---|---|---|
| `ai_basics` | beginner | — | `roadmap_sh_ai_engineer`, `thai_mooc` |
| `prompt_writing` | beginner | `ai_basics` | `roadmap_sh_prompt_engineering` |
| `ai_agents` | intermediate | `prompt_writing` | `anthropic_building_effective_agents`, `roadmap_sh_ai_agents` |
| `staying_in_scope` | advanced | `ai_agents` | `nemo_guardrails`, `clinc150_paper`, `clinc150_data` |
| `prompt_injection` | intermediate | `prompt_writing` | `nemo_guardrails`, `claude_docs_mitigate_jailbreaks` |
| `intent_understanding` | advanced | `ai_basics` | `clinc150_paper`, `llm_subjective_language_survey`, `metaphor_llms_2025` |
| `recommender_systems` | advanced | `intent_understanding` | `learning_path_recommenders` |
| `plain_language` | beginner | — | `iso_24495_1` (paid; the abstract page is free) |
| `layered_explanation` | intermediate | `plain_language` | `anthropic_agent_skills`, `cooper_cognitive_load` |
| `inclusive_learning` | beginner | — | `cooper_cognitive_load`, `cast_udl_guidelines` |
| `system_design` | intermediate | — | `roadmap_sh_system_design` |

The 17 resources are the links of the seed table in [design_philosophy.md](design_philosophy.md#แหล่งศึกษาเริ่มต้น),
with the roadmap.sh home page split into its four named roadmaps and the Anthropic article at its current
address. A test keeps every link of that table in the library.

### File format

`topics_v1.json` is `{"id": "topics_v1", "description": …, "topics": [...]}`. Each topic has exactly:

| Field | Rule |
|---|---|
| `id` | `^[a-z][a-z0-9_]{1,47}$`, unique; `out_of_scope` is reserved for "no topic fits" |
| `name`, `summary` | `{"th": …, "en": …}`; the Thai text must contain Thai and the English text must not |
| `examples` | `{"th": [2–10 phrases], "en": [2–10 phrases]}`: everyday phrasings and metaphors; a phrase may belong to one topic only |
| `prerequisites` | known topic ids, no repeats, no cycles, and never harder than the topic itself |
| `level` | `beginner`, `intermediate` or `advanced` (shown as เริ่มต้น / กลาง / ลึก) |

`resources_v1.json` is `{"id": "resources_v1", "description": …, "resources": [...]}`. Each resource has exactly:

| Field | Rule |
|---|---|
| `id` | same pattern as topics, unique, and not equal to a topic id |
| `url` | `https://`, a full host name, printable ASCII without spaces, no user name or password, at most 300 characters, unique |
| `title`, `by` | non-empty |
| `kind` | `course`, `roadmap`, `article`, `documentation`, `paper`, `dataset`, `standard` or `guidelines` |
| `level`, `language`, `access` | a level as above; `th` or `en`; `free` or `paid` |
| `topics` | known topic ids, at least one |
| `purpose`, `focus` | `{"th": …, "en": …}`: what it is for, and which parts to read first |
| `verified_at` | `YYYY-MM-DD`, not in the future (one day of slack for time zones) |

Every topic must be covered by at least one resource. `load_library()` reports every problem at once in a
`LibraryError` and never returns a half-checked library.

### What `verified_at` means

The date a developer last re-checked the entry: the link opened and, where the page could be read, it was
the resource the entry describes (title, author, what it covers). It is not an endorsement and not a
review of the content's quality. How each entry was checked on 2026-11-05 is recorded in
[the evidence note](evidence/2026-11-05-study-library-links.md). The weekly link check confirms only that
links still open; it never changes `verified_at`.

### Versioning

`Library.sha256` is one SHA-256 over both files' canonical JSON (`neuron_flow.model.fingerprint`, as for
prompt files), and `Library.tag` is `v1@sha256:<hash>`. Reformatting a file does not change it; changing
one character of content does. Every study-guide agent (3.2) puts the tag in its agent version, so a
changed library is a new version and an interrupted job fails as `configuration_changed`. Changing the
schema or making a breaking change to ids means new files (`topics_v2.json`, `resources_v2.json`).

## The link check

`python -m app.domains.study_guide.link_check --summary "$GITHUB_STEP_SUMMARY"`, run by
*Actions → Study library link check* (`.github/workflows/study-links.yml`) every Monday at 02:23 UTC, by
hand, and on every push or pull request that changes `app/domains/study_guide/`. GitHub's runners reach the
internet; most of these sites are blocked from Claude Code cloud sessions, so the session cannot replace this
check.

| Outcome | When | Effect |
|---|---|---|
| `ok` | 2xx at the listed address (adding or dropping a final `/` counts) | — |
| `moved` | 2xx after a redirect to another address | warning: update the entry after checking it is the same resource |
| `blocked` | 401, 403 or 429: the site refused an automated visit | warning: check it by hand |
| `broken` | 404, 410, other 4xx; a 5xx, network, DNS or TLS error or timeout still there after two retries (5 s and 20 s later); redirect loops; https → http redirects | the run fails |

- It sends a plain client name (`Mozilla/5.0 (compatible; neuron-flow-link-check/1.0)`) and no personal
  data, reads at most 256 KiB per page, and waits 20 s per attempt.
- Why two retries: on its first run (2026-11-05) one link answered "connection reset" twice, 5 s apart,
  and opened normally 30 s later in the next run. With one retry, that was a false alarm in 1 of 2 runs.
- The summary lists each link with the title the site answered with (HTML `<title>`, or a PDF's metadata
  title), so a person can see that the link still leads to the resource. Titles come from other sites: they
  are cleaned to one line, shown only inside code spans, and never put in annotations.
- It never edits the library. A broken link is a decision for a person: a new address (after checking it),
  or removing the entry, which also changes the hash.
- Exit status: 0 with no broken link, 1 with any broken link, 2 when the library itself is invalid.

## Adding or changing a resource

1. Check the page yourself: it opens, and the title, author and content match the entry.
2. Edit `resources_v1.json` (and `topics_v1.json` if a topic changes), with today's date in `verified_at`.
3. If the link came from the seed table in design_philosophy.md, keep the table and the library in step.
4. Open a pull request. *Study library link check* runs on it; read its summary and check the titles.
5. Record how the new entries were checked in a dated evidence note.

Do not add the owner's example phrases that the evaluation set (3.3) will use to the topic examples;
detection must be tested on phrases it was not shown.

## Tests

- `tests/test_study_library.py`: the committed library loads and every topic has a resource; every seed
  link from design_philosophy.md is in the library; the owner's flagship metaphor is not an example; the
  hash covers both files and ignores formatting; missing files, bad JSON, duplicate keys, bad versions and
  a file from another version are refused; 43 broken rules are each reported; every problem is reported at
  once.
- `tests/test_study_link_check.py`, against a local HTTP server: ok, a trailing-slash redirect, moved,
  404 (not retried), 403 and 429 (blocked), a 503 that recovers on the first retry, a 500 that is still
  there after both retries (with the waits), a redirect loop, a PDF title, a timeout, a closed port, refused https → http redirects, the client name;
  and `main()`: exit codes, warnings versus errors, a summary table that a hostile title cannot break, an
  invalid library, and the library files left unchanged.
- `tests/test_study_guide.py` (roadmap 3.2):
  - **the rules:** the budget of 5 and the prerequisites left out, the person's language first, basics first
    then easy to hard, and the invariants for every topic in both languages;
  - **the prompts:** detection limited to catalog ids plus `out_of_scope`, one note field per step,
    `specialize` refusing to change what a file already fixes, a bad `input_field` refused, and no URL in
    what the AI is shown;
  - **the mock:** all 66 catalog examples found, its limits (cooking, weather, the owner's metaphor), and a
    prompt without a simulation failing loudly;
  - **the validators:** 15 tampered outputs refused, including a changed URL, an unselected resource, a
    `decision` field and links in AI text; an out-of-scope answer must list every topic; the input contract;
  - **whole jobs through Core:** Thai and English guides, out of scope, an injection that asks for a link,
    personal data masked, a hiccup retried, detection unavailable four ways (outage, declined, unknown
    topic, a link in the restatement), a bad key failing loudly, explanation unavailable four ways, versions
    carrying the library, and a job frozen with another library never answered;
  - **the Claude path, against a local fake API:** both calls, the catalog and its choices in the first
    request, one note per step in the second, the phone number masked, no URL sent to the AI, and the key
    never stored;
  - **the service:** a job ends `COMPLETED` with no review and `result.ai` from detection; admission refuses
    case-shaped input; `/v1/status` describes the five steps.
- `examples/study_guide_demo.py`: *Core logic tests* runs four synthetic requests and shows the answers on
  the run page.

## Not built yet (roadmap 3.3–3.4)

- **3.3:** the evaluation set and scorecard. It will cover metaphors, paraphrases, out-of-scope requests and
  injection attempts, in Thai and English, with phrases that are not catalog examples, and it will be run
  with the mock in CI and with Claude by hand.
- **3.4:** a box on the web page, and showing the layered answer.
- **Also open:** a `chat` span for the `explain` call, and a live Claude run (D2).

See [ROADMAP.md](ROADMAP.md#phase-3--study_guidev1-the-first-response-study-guide-the-second-domain).
