"""Robustness benchmark, stage 1 (docs/benchmarking.md): the data, its licences, the live-AI case file and the gate.

The fast layers (intake, rules, masking, ai_reply, core and their sweeps) run here and must match the committed
baseline. The slower e2e layer runs in CI (*Core logic tests* → "Robustness benchmark"), with the same baseline.
"""

import json
import unittest
from pathlib import Path

from app.eval.triage_shadow_eval import load_golden
from tests.robustness import bench

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "baselines" / "robustness_v1.json"
FAST = ("intake", "rules", "masking", "ai_reply", "core")


class RobustnessDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = bench.load_sets()

    def test_the_sets_load_and_every_item_is_well_formed(self):
        items = self.sets["items"]
        self.assertEqual(len({item["id"] for item in items}), len(items))
        synthetic = [item for item in items if item["source"] == "synthetic"]
        self.assertEqual(len(synthetic), self.sets["sets"]["synthetic"]["items"])
        for item in items:
            with self.subTest(item=item["id"]):
                self.assertIn(item["layer"], bench.LAYERS)
                self.assertIn(item["severity"], bench.SEVERITIES)
                self.assertIn(item["checklist"], ("MFT", "INV", "DIR"))
                self.assertTrue(item["title_th"] and item["title_en"] and item["capability"])
                self.assertIn(item.get("known"), (None, "documented_limitation"))
                if item["expect"].get("same_as"):
                    self.assertIn(item["expect"]["same_as"], {i["id"] for i in items})
        open_set = self.sets["sets"]["open"]
        self.assertEqual((open_set["blns"], open_set["jsontestsuite"]), (515, 318))
        self.assertEqual(len([i for i in items if i["source"] != "synthetic"]), open_set["labelled"])

    def test_every_open_source_is_pinned_and_attributed_in_the_notice(self):
        notice = (ROOT / "tests" / "robustness" / "NOTICE.md").read_text(encoding="utf-8")
        for source in self.sets["sets"]["open"]["sources"]:
            with self.subTest(source=source["id"]):
                self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
                self.assertIn(source["commit"], notice)
                self.assertIn(source["license"], notice)
        for line in ("Copyright (c) 2015-2020 Max Woolf", "Copyright (c) 2016 Nicolas Seriot",
                     "creativecommons.org/licenses/by/3.0", "creativecommons.org/licenses/by/4.0"):
            self.assertIn(line, notice)

    def test_the_live_ai_case_file_matches_the_sets(self):
        committed = bench.GOLDEN.read_text(encoding="utf-8")
        self.assertEqual(committed, bench.dump_golden(bench.golden_export(self.sets)),
                         "regenerate it: python -m tests.robustness.bench --export-golden "
                         "tests/robustness/triage_edge_golden_v1.json")
        golden = load_golden(bench.GOLDEN)  # the scorecard that *Shadow eval with Typhoon* runs accepts it
        self.assertEqual(len(golden["cases"]), len([i for i in self.sets["items"] if i["layer"] == "rules"]))

    def test_the_helpers_expand_recipes_and_keep_reports_readable(self):
        self.assertEqual(bench.expand({"$repeat": "ab", "count": 3}), "ababab")
        self.assertEqual(len(bench.expand({"$repeat": "อัป ", "count_chars": 11, "suffix": "!"})), 11)
        self.assertEqual(bench.expand({"$concat": ["[", {"$repeat": "0", "count": 2}, "]"]}), "[00]")
        self.assertEqual(bench.safe("ok \ud800 ​ ไทย"), "ok \\ud800 \\u200b ไทย")
        self.assertTrue(bench.has_format_chars("a‮b") and not bench.has_format_chars("ไทย"))


class RobustnessGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = bench.run(FAST)
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_the_fast_layers_match_the_committed_baseline(self):
        changes = bench.compare(self.report, self.baseline)
        self.assertEqual(changes, [], "outcomes changed; if on purpose, regenerate with "
                                      "python -m tests.robustness.bench --write-baseline tests/baselines/robustness_v1.json")

    def test_no_input_was_run_as_a_shell_command(self):
        self.assertFalse(self.report["canary"]["exists_after"])

    def test_the_gate_reports_a_changed_item_and_a_changed_set(self):
        changed = json.loads(json.dumps(self.baseline))
        changed["items"]["SYN-INT-001"]["passed"] = False
        changed["sets"]["synthetic"]["sha256"] = "0" * 64
        changes = bench.compare(self.report, changed)
        self.assertTrue(any(c.startswith("SYN-INT-001: now passes") for c in changes), changes)
        self.assertTrue(any("synthetic set changed" in c for c in changes), changes)

    def test_the_summary_names_every_bug_in_thai(self):
        text = bench.summary(self.report, [])
        for row in self.report["items"]:
            if not row["passed"] and row["severity"] == "bug":
                self.assertIn(row["id"], text)
        self.assertIn("ด่านตรวจผลรายรายการ (gate): **ผ่าน**", text)


if __name__ == "__main__":
    unittest.main()
