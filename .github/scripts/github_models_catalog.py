"""Write the GitHub Models catalog (model id and free rate-limit tier) to the run summary.

Used by the manual "... with GitHub Models" workflows, so the owner can see which model ids exist today when
the default one is retired. Reads the token from GITHUB_MODELS_TOKEN and never prints it. Any problem only
writes a short note: the scorecard step runs either way.

Run: ``python .github/scripts/github_models_catalog.py "$GITHUB_STEP_SUMMARY"``
"""

import json
import os
import sys
import urllib.request

URL = "https://models.github.ai/catalog/models"


def rows(models):
    found = []
    for model in models if isinstance(models, list) else []:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str):
            continue
        outputs = model.get("supported_output_modalities")
        if isinstance(outputs, list) and outputs and "text" not in outputs:
            continue  # embeddings and other non-chat models
        tier = model.get("rate_limit_tier") if isinstance(model.get("rate_limit_tier"), str) else "?"
        found.append((model["id"][:100], tier[:20]))
    return sorted(set(found))


def main(summary_path):
    token = os.environ.get("GITHUB_MODELS_TOKEN", "").strip()
    request = urllib.request.Request(URL, headers={"authorization": f"Bearer {token}",
                                                   "accept": "application/vnd.github+json",
                                                   "x-github-api-version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            found = rows(json.loads(response.read(2_000_000).decode("utf-8")))
        lines = ["<details><summary>รุ่นที่ GitHub Models มีให้ตอนนี้ (Models available now)</summary>", "",
                 "ระดับ low ใช้ฟรีได้มากกว่าระดับ high (Low-tier models allow more free requests.)", "",
                 "| model id | rate limit tier |", "|---|---|"]
        lines += [f"| `{model_id}` | {tier} |" for model_id, tier in found]
        lines += ["", "</details>", ""]
    except Exception as exc:  # the list is a convenience; never fail the run for it
        lines = [f"_Could not read the GitHub Models catalog ({type(exc).__name__})._", ""]
    with open(summary_path, "a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.devnull))
