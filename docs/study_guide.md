# Study guide (`study_guide.v1`) — topic catalog and verified resource library

**Status (2026-11-05):** roadmap 3.1 is built: the versioned topic catalog, the verified resource library,
their checks and hash, and the weekly link check. The workflow that answers people (3.2), its scorecard
(3.3) and the web page (3.4) are not built yet. Nothing in the running service uses the library yet.

## ภาพรวมสำหรับเจ้าของโปรเจกต์

**สรุป:** ระบบมี "คลังแหล่งเรียน" ที่ตรวจแล้ว 17 แหล่งใน 11 หัวข้อ และ GitHub เปิดทุกลิงก์ให้ทุกวันจันทร์
เพื่อจับลิงก์เสีย นี่คือฐานของผู้ช่วยแนะนำแหล่งเรียน ซึ่งจะสร้างในขั้นถัดไป (3.2)

**ทำงานอย่างไร (ทีละขั้น)**
1. **สมุดหัวข้อ (topic catalog)** บอกว่าผู้ช่วยช่วยเรื่องไหนได้บ้าง แต่ละหัวข้อมีชื่อไทยและอังกฤษ ตัวอย่างคำพูดและคำเปรียบเปรย
   ทั้งสองภาษา หัวข้อที่ควรรู้ก่อน และระดับ (เริ่มต้น / กลาง / ลึก)
2. **คลังแหล่งเรียน (resource library)** คือรายการลิงก์เดียวที่ผู้ช่วยจะแสดงได้ ทุกแหล่งบอกว่า **ใช้ทำอะไร**
   **ระดับไหน** **ภาษาอะไร** **ฟรีหรือเสียเงิน** และ **ควรเน้นส่วนไหน**
3. **ตัวตรวจคลัง** ไม่ยอมโหลดคลังที่ผิดกติกา เช่น ลิงก์ที่ไม่ใช่ https หัวข้อที่ไม่มีแหล่งเรียน หัวข้อที่ต้องรู้ก่อนวนกันเป็นวง
   หรือช่องภาษาไทยที่ไม่มีภาษาไทย
4. **ลายนิ้วมือของคลัง (SHA-256)** เปลี่ยนทุกครั้งที่มีคนแก้คลังแม้ตัวอักษรเดียว ขั้น 3.2 จะใส่ค่านี้ไว้ในเวอร์ชันของผู้ช่วย
   เหมือนที่ทำกับ prompt งานที่ค้างอยู่จึงไม่ถูกรันซ้ำด้วยคลังที่เปลี่ยนไปแล้ว
5. **ตรวจลิงก์ทุกสัปดาห์** ทุกวันจันทร์ 09:23 น. GitHub เปิดทุกลิงก์ในคลัง ถ้ามีลิงก์เสีย ช่องตรวจจะเป็นสีแดงและบอกว่าลิงก์ไหน
   ตัวตรวจไม่แก้คลังเอง คนเป็นคนตัดสินว่าจะเปลี่ยนที่อยู่หรือเอาแหล่งนั้นออก ลิงก์จะถูกตรวจทุกครั้งที่มีคนแก้คลังด้วย
   จึงไม่มีลิงก์ใหม่ที่ยังไม่ได้ตรวจหลุดเข้าไป

**หลักที่ทำให้ลิงก์มั่วไม่ได้:** ในขั้น 3.2 AI จะเลือกได้แค่ "รหัส" ของแหล่งเรียนจากคลัง ไม่ได้เขียนลิงก์เอง โค้ดเป็นคนใส่ลิงก์จากคลัง
ลิงก์ที่ AI แต่งขึ้นเองจึงไปถึงผู้ใช้ไม่ได้

**สิ่งที่ยังจำกัดอยู่ (บอกตรง ๆ)**
- มีแหล่งภาษาไทยแหล่งเดียว (Thai MOOC) ที่เหลือเป็นภาษาอังกฤษ
- หัวข้อภาษาธรรมดา (plain language) มีแค่มาตรฐาน ISO ซึ่งฉบับเต็มต้องซื้อ หน้าที่ลิงก์ไปอ่านคำอธิบายย่อได้ฟรี
- หัวข้อระบบแนะนำ (recommender systems) มีแหล่งเดียว และเป็นรายงานเทคนิคระดับลึก
- ตัวอย่าง "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ" ของคุณตั้งใจไม่ใส่ไว้ในสมุดหัวข้อ เก็บไว้เป็นข้อสอบในขั้น 3.3
  เพื่อวัดว่าระบบเข้าใจคำเปรียบที่ไม่เคยเห็นได้จริง

**คุณลองดูได้ (ไม่ต้องติดตั้งอะไร)**
1. เปิด GitHub → แท็บ Actions → *Study library link check* → รันล่าสุด
2. ดูหัวข้อ "ตรวจลิงก์คลังแหล่งเรียน (study library link check)" ในหน้าสรุป
3. ถ้าทำงานปกติ ต้องเห็นคำว่า "ผ่าน" และตาราง 17 แถว แต่ละแถวมีชื่อหน้าที่เว็บนั้นตอบกลับมา

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
one character of content does. The study-guide agents (3.2) will put the tag in their agent version, so a
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

## Not built yet (roadmap 3.2–3.4)

The `study_guide.v1` workflow (`detect_topic` → `pick_resources` → `build_path` → `explain` → `prepare`),
its prompts and validators, its catalog entry, the evaluation set and scorecard, and the page. See
[ROADMAP.md](ROADMAP.md#phase-3--study_guidev1-the-first-response-study-guide-the-second-domain).
