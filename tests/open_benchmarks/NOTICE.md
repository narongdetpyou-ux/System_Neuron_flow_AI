# Third-party data in the open benchmarks (roadmap 5.6)

`build_sets.py` downloads four openly licensed sources at run time, checks each against the SHA-256 written in
it, and builds case files from them. **No copy of these sources is committed.** `manifest_v1.json` records the
pinned sources and the SHA-256 of every case file built from them, so a run can show it used the same cases.
The rest of this folder (`build_sets.py`, `manifest_v1.json`, this notice) is this project's own work under
its GPL-3.0-only licence.

None of these sources contains real customer records, so this project treats them like its own synthetic
data (ADR-024 in `docs/architecture.md`):
- CLINC150 was written by crowd workers for the dataset.
- BANKING77 was written by experts for the dataset.
- MASSIVE was translated and localised by professional translators from SLURP's English prompts, which were
  themselves written for that dataset.
- BIPIA's text attacks were written by its authors as attack instructions.

**Changes made, for every source:** a fixed sample is selected by the rules in `build_sets.py`, and each
selected item is given a label in this project's four triage categories (`access`, `upload`, `billing`,
`other`) by the tables `CLINC_MAP`, `CLINC_EXCLUDED` and `BANKING_MAP`; every MASSIVE utterance becomes
`other`. Those labels are this project's mapping. They are not part of the datasets, and their authors do not
endorse them. Leading and trailing spaces are removed; the text is otherwise unchanged. BIPIA's attacks are
placed, unchanged, before or after one of this project's own synthetic cases.

## CLINC150

- Work: "An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction", by Stefan Larson,
  Anish Mahendran, Joseph J. Peper, Christopher Clarke, Andrew Lee, Parker Hill, Jonathan K. Kummerfeld,
  Kevin Leach, Michael A. Laurenzano, Lingjia Tang and Jason Mars. EMNLP-IJCNLP 2019.
  https://www.aclweb.org/anthology/D19-1131/
- Source: https://github.com/clinc/oos-eval, commit `828f8093932c8fe6ca7936c3d2e52903b1c523de`,
  file `data/data_full.json` (the same file as the robustness benchmark's extract).
- Licence: Creative Commons Attribution 3.0 Unported (CC BY 3.0),
  https://creativecommons.org/licenses/by/3.0/
- Used: 300 requests of the `test` and `oos_test` splits.

## BANKING77

- Work: "Efficient Intent Detection with Dual Sentence Encoders", by Iñigo Casanueva, Tadas Temcinas,
  Daniela Gerz, Matthew Henderson and Ivan Vulić. 2nd Workshop on NLP for ConvAI, ACL 2020.
  https://arxiv.org/abs/2003.04807 (PolyAI).
- Source: https://github.com/PolyAI-LDN/task-specific-datasets, commit
  `57ec275d8078af65b7731c2a98be812d844a6d6b`, file `banking_data/test.csv` (the same file as the robustness
  benchmark's extract).
- Licence: Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- Used: 300 requests of the test file, from the intents listed in `BANKING_MAP`.

## MASSIVE 1.1

- Work: "MASSIVE: A 1M-Example Multilingual Natural Language Understanding Dataset with 51
  Typologically-Diverse Languages", by Jack FitzGerald, Christopher Hench, Charith Peris, Scott Mackie, Kay
  Rottmann, Ana Sanchez, Aaron Nash, Liam Urbach, Vishesh Kakarala, Richa Singh, Swetha Ranganath, Laurie
  Crist, Misha Britan, Wouter Leeuwis, Gokhan Tur and Prem Natarajan. 2022. https://arxiv.org/abs/2204.08582
  (Amazon). Copyright Amazon.com Inc. or its affiliates.
- Source: the release archive
  `https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz`, SHA-256
  `4cba5faa11c71437928e17cb1b9b3d8b8e727e7ea363a3a9a8045e19c0491577`, members `1.1/data/th-TH.jsonl` and
  `1.1/data/en-US.jsonl` (read in memory; nothing is unpacked to disk). Repository:
  https://github.com/alexa/massive.
- Licence: Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- MASSIVE's own notice: it was created by translating and localising the English text of SLURP, which is
  also licensed CC BY 4.0 (https://github.com/pswietojanski/slurp/blob/master/LICENSE.txt). SLURP: "SLURP: A
  Spoken Language Understanding Resource Package", by Emanuele Bastianelli, Andrea Vanzo, Pawel Swietojanski
  and Verena Rieser, EMNLP 2020, https://aclanthology.org/2020.emnlp-main.588
- Used: 150 `test` utterances in Thai and the same 150 ids in English; only the id, scenario, intent and
  utterance are read (not the annotators' ids or judgements).

## BIPIA

- Work: "Benchmarking and Defending Against Indirect Prompt Injection Attacks on Large Language Models", by
  Jingwei Yi, Yueqi Xie, Bin Zhu, Keegan Hines, Emre Kiciman, Guangzhong Sun, Xing Xie and Fangzhao Wu.
  2023. https://arxiv.org/abs/2312.14197 (Microsoft).
- Source: https://github.com/microsoft/BIPIA, commit `a004b69ec0dd446e0afd461d98cb5e96e120a5d0`, file
  `benchmark/text_attack_test.json`. The repository's licence lists third-party datasets with their own
  licences (WikiTableQuestions, Stack Exchange answers, OpenAI Evals invoices); the attack file is not among
  them, so it is under the repository's MIT licence. None of those third-party datasets is used here.
- Used: all 75 test text attacks.
- Licence: MIT. Its full text:

```
MIT License

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE
```
