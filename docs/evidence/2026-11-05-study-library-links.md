# Study library: how each link was checked (roadmap 3.1)

**Date:** 2026-11-05. **What:** the 17 resources of `app/domains/study_guide/catalog/resources_v1.json`
(library `v1`), seeded from the table in `docs/design_philosophy.md`. **Sources:** this Claude Code cloud
session (curl through its proxy, a web-fetch tool, and the alphaXiv paper service) and the first run of
*Actions → Study library link check* on the pull request (section 2).

## สรุปสำหรับเจ้าของโปรเจกต์

- เครือข่ายของเซสชัน Claude เปิดลิงก์ได้แค่ 4 จาก 17 ลิงก์ (บทความ Anthropic 2 ลิงก์ คู่มือ Claude และ GitHub) ที่เหลือถูกปิดกั้น
  จึงต้องให้ GitHub เป็นคนเปิดตรวจแทน
- งานวิจัยบน arXiv 3 ชิ้นตรวจชื่อเรื่องและผู้เขียนผ่านบริการ alphaXiv ได้
- เจอลิงก์ที่ย้ายที่อยู่ 1 ลิงก์: บทความ "Building effective agents" ย้ายจาก `/engineering/` ไป `/research/`
  คลังใช้ที่อยู่ใหม่แล้ว และแก้ตารางในเอกสารปรัชญาให้ตรงกัน
- GitHub เปิดตรวจให้ 2 รอบ รอบแรก 16 จาก 17 ลิงก์เปิดได้ ลิงก์ที่ 17 (บทความ Cooper ไฟล์ PDF) ถูกตัดการเชื่อมต่อ 2 ครั้งติด
  รอบที่สอง 30 วินาทีต่อมา เปิดได้ครบ 17 ลิงก์ จึงปรับให้ลองซ้ำ 2 ครั้ง (รอ 5 และ 20 วินาที) เพื่อไม่ให้ช่องตรวจแดงเพราะเน็ตสะดุดชั่วคราว
- ชื่อหน้าที่ทุกเว็บตอบกลับมาตรงกับแหล่งในคลัง แก้ชื่อในคลัง 2 แห่งให้ตรงกับที่เว็บใช้จริง (รายงานเรื่องเส้นทางการเรียน และแนวปฏิบัติ UDL)
- บทความ Cooper เปิดได้ แต่ไฟล์ PDF ไม่มีชื่อเรื่องในข้อมูลไฟล์ จึงยังไม่ได้ยืนยันชื่อเรื่องและผู้เขียนจากตัวไฟล์ ข้อมูลนี้มาจากตารางตั้งต้นของคุณ

## 1. Checks from this session

The session's network allowed only some hosts. `curl -L` answered `000` (blocked by the proxy) for
roadmap.sh, thaimooc.ac.th, arxiv.org, aclanthology.org, ajet.org.au, committee.iso.org and
udlguidelines.cast.org. The web-fetch tool failed on the same hosts (DNS not resolved), and on
www.iso.org and the AJET landing page `article/view/2322`. The reference-lookup service (OpenAlex) was
also blocked.

| Resource | How it was checked here | What was seen |
|---|---|---|
| `anthropic_building_effective_agents` | curl and web-fetch | 200. The listed seed address `/engineering/building-effective-agents` redirects to `/research/building-effective-agents`, which the library now uses. Heading "Building effective agents", published 19 Dec 2024; it separates workflows (prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer) from agents, with two appendices. A banner says the tooling has changed since December 2024 |
| `anthropic_agent_skills` | curl and web-fetch | 200, no redirect. Heading "Equipping agents for the real world with Agent Skills", published 16 Oct 2025; covers SKILL.md, progressive disclosure, code execution, guidelines and security |
| `claude_docs_mitigate_jailbreaks` | curl and web-fetch | 200, no redirect. Title "Mitigate jailbreaks and prompt injections"; covers jailbreaks and direct injection, indirect injection in tool results (keeping untrusted content apart, JSON-encoding), and chained safeguards |
| `clinc150_data` | web-fetch (curl got 403 from the proxy) | 200, no redirect. "Repository that accompanies 'An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction' (EMNLP 2019)"; 150 in-scope intent classes plus out-of-scope queries; the README's citation names Larson et al., EMNLP-IJCNLP 2019 |
| `clinc150_paper` | not reachable; the title, authors and venue come from the citation in the `clinc150_data` README | — |
| `nemo_guardrails` | alphaXiv (arXiv 2310.10501) | "NeMo Guardrails: A Toolkit for Controllable and Safe LLM Applications with Programmable Rails", Rebedea, Dinu, Sreedhar, Parisien, Cohen (NVIDIA); topical rails, and moderation rails against jailbreaks |
| `llm_subjective_language_survey` | alphaXiv (arXiv 2508.07959) | A survey by Song, Zhang, Gao, Yao and Zhang (Tianjin University; The Hong Kong Polytechnic University) of eight subjective-language tasks, among them metaphor recognition and intent detection. The exact title on arXiv is confirmed by the link check (section 2) |
| `learning_path_recommenders` | alphaXiv (arXiv 2406.10245) | "On Conceptualisation and an Overview of Learning Path Recommender Systems in E-Learning", technical report, Fuster-López et al., June 2024; five recommenders (concept-map walk, collaborative filtering, clustering, supervised learning, reinforcement learning) and a summary table |
| the other 9 | not reachable from this session | checked by the link check (section 2) |

## 2. The link check on GitHub

Commit `c5f7d5a` (the first commit of PR #32), GitHub-hosted `ubuntu-latest` runners, Python 3.12, one
retry 5 s after a network error or a 5xx (the setting at that commit).

| Run | Event | Time (UTC) | Result |
|---|---|---|---|
| [42089813688](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42089813688) | push | 19:01:11–19:01:26 | failed: 16 ok, 1 broken (`cooper_cognitive_load`: "connection reset" on both attempts) |
| [42089904833](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42089904833) | pull_request | 19:01:45–19:01:52 | passed: 17 ok, 0 moved, 0 blocked, 0 broken |

Every link answered 200 at its listed address, with no redirect, in the passing run. The titles the sites
answered with:

| Resource | Page title (as answered) | Matches the entry |
|---|---|---|
| `roadmap_sh_ai_engineer` | AI Engineer Roadmap | yes |
| `thai_mooc` | Thai MOOC - แพลตฟอร์มการเรียนรู้ออนไลน์ | yes (the publisher comes from the seed table) |
| `roadmap_sh_prompt_engineering` | Prompt Engineering Roadmap | yes |
| `anthropic_building_effective_agents` | Building effective AI agents \ Anthropic | yes (on-page heading "Building effective agents", section 1) |
| `roadmap_sh_ai_agents` | AI Agents Roadmap | yes |
| `anthropic_agent_skills` | Equipping agents with Agent Skills \ Anthropic | yes (on-page heading, section 1) |
| `nemo_guardrails` | [2310.10501] NeMo Guardrails: A Toolkit for Controllable and Safe LLM Applications with Programmable Rails | yes |
| `clinc150_paper` | An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction - ACL Anthology | yes |
| `clinc150_data` | GitHub - clinc/oos-eval: Repository that accompanies "An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction" (EMNLP 2019) · GitHub | yes |
| `llm_subjective_language_survey` | [2508.07959] Large Language Models for Subjective Language Understanding: A Survey | yes; the seed table's "LLMs for …" was corrected to this title |
| `metaphor_llms_2025` | Metaphor and Large Language Models: When Surface Features Matter More than Deep Understanding - ACL Anthology | yes |
| `learning_path_recommenders` | [2406.10245] On conceptualisation and an overview of learning path recommender systems in e-learning | yes; the entry's title was changed to arXiv's capitalisation |
| `cooper_cognitive_load` | none: the PDF has no metadata title in its first 256 KiB | **not confirmed**: the title and author come from the seed table |
| `claude_docs_mitigate_jailbreaks` | Mitigate jailbreaks and prompt injections - Claude Platform Docs | yes |
| `iso_24495_1` | ISO 24495-1:2023 - Plain language — Part 1: Governing principles and guidelines | yes |
| `cast_udl_guidelines` | CAST Universal Design for Learning Guidelines | yes; the entry's title was "The UDL Guidelines" and is now "Universal Design for Learning Guidelines", and "version 3.0, 2024" was dropped from `by` because the page title does not show it |
| `roadmap_sh_system_design` | System Design Roadmap | yes |

What changed because of these runs:
- **Retries.** The Cooper PDF failed twice 5 s apart and opened 30 s later, so one retry gave a false alarm
  in 1 of 2 runs. The check now retries network errors and 5xx twice, 5 s and 20 s later, and the job may
  take up to 30 minutes.
- **Two titles** were corrected (see the table). That changes the library's hash; nothing uses it yet.

Not checked by anyone: whether each resource's `purpose` and `focus` describe its content well. They
come from the pages read in section 1, the paper reports, the page titles above and general knowledge
of these well-known resources. A person should read the pages before relying on them, which is why
`verified_at` means only what [study_guide.md](../study_guide.md#what-verified_at-means) says.
