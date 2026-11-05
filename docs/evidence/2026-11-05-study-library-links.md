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
- ผลการตรวจของ GitHub อยู่ในหัวข้อ 2

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

## 2. The link check on the pull request

To be filled in from the first run of *Study library link check* on this branch: the run link, the commit,
and each link's outcome and page title.
