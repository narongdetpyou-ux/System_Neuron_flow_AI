# Third-party data in the robustness benchmark

`open_extract_v1.json` holds excerpts of four openly licensed datasets, pinned to exact upstream commits. Their
SHA-256 values are recorded in that file. `python -I tests/robustness/build_open_extract.py verify` downloads
the upstream files again, checks every hash and rebuilds the extract byte for byte. The rest of this folder
(`synthetic_v1.json`, `bench.py`, `build_open_extract.py`) is this project's own work under its GPL-3.0-only
licence.

None of these datasets contains real customer records:
- BLNS and JSONTestSuite are hand-made test strings and files.
- CLINC150 was written by crowd workers for the dataset.
- BANKING77 was written by experts for the dataset.

This project treats such made-for-the-dataset text like its own synthetic data (ADR-024 in
`docs/architecture.md`).

## Big List of Naughty Strings

- Source: https://github.com/minimaxir/big-list-of-naughty-strings, commit `db33ec7b1d5d9616a88c76394b7d0897bd0b97eb`.
- Used: every string of `blns.json`, unchanged (`corpora.blns`).
- Licence: MIT. Its full text:

```
The MIT License (MIT)

Copyright (c) 2015-2020 Max Woolf

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
SOFTWARE.
```

## JSON Parsing Test Suite

- Source: https://github.com/nst/JSONTestSuite, commit `1ef36fa01286573e846ac449e8683f8833c5b26a`.
- Used: every file in `test_parsing/` (`corpora.jsontestsuite`). The bytes are unchanged. They are stored
  zlib-compressed and base64-encoded because many files are deliberately not valid UTF-8.
- Licence: MIT. Its full text:

```
MIT License

Copyright (c) 2016 Nicolas Seriot

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
SOFTWARE.
```

## CLINC150

- Work: "An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction", by Stefan Larson,
  Anish Mahendran, Joseph J. Peper, Christopher Clarke, Andrew Lee, Parker Hill, Jonathan K. Kummerfeld,
  Kevin Leach, Michael A. Laurenzano, Lingjia Tang and Jason Mars. EMNLP-IJCNLP 2019.
  https://www.aclweb.org/anthology/D19-1131/
- Source: https://github.com/clinc/oos-eval, commit `828f8093932c8fe6ca7936c3d2e52903b1c523de`,
  file `data/data_full.json`.
- Licence: Creative Commons Attribution 3.0 Unported (CC BY 3.0),
  https://creativecommons.org/licenses/by/3.0/
- Changes made: 39 requests were selected by the rules in `build_open_extract.py`. Each was given a label in
  this project's four triage categories (`CLINC_MAP`; intents not listed become `other`). Those labels are
  this project's mapping. They are not part of CLINC150, and its authors do not endorse them.

## BANKING77

- Work: "Efficient Intent Detection with Dual Sentence Encoders", by Iñigo Casanueva, Tadas Temcinas,
  Daniela Gerz, Matthew Henderson and Ivan Vulić. 2nd Workshop on NLP for ConvAI, ACL 2020.
  https://arxiv.org/abs/2003.04807 (PolyAI).
- Source: https://github.com/PolyAI-LDN/task-specific-datasets, commit
  `57ec275d8078af65b7731c2a98be812d844a6d6b`, file `banking_data/test.csv`.
- Licence: Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- Changes made: 34 requests were selected (the first two of each intent listed in `BANKING_MAP`). Each was
  given a label in this project's four triage categories. Those labels are this project's mapping, not part
  of BANKING77, and its authors do not endorse them.
