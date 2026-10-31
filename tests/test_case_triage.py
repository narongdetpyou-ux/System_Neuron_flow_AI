"""A domain-proof acceptance slice; intentionally no Core source changes."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from neuron_flow import Runtime, SpecError
from app.domains.case_triage import build_workflow, registry
from app.domains.case_triage import agents


SYNTHETIC = {"case_id": "SYN-001", "summary": "I cannot upload an attachment"}


class CaseTriagePilotTests(unittest.TestCase):
    def test_end_to_end_and_verified_receipt(self):
        with tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=registry()) as rt:
                submitted = rt.submit(build_workflow("demo_001", SYNTHETIC))
                self.assertTrue(submitted["created"])
                result = rt.run("demo_001")
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["steps"]["classify"]["output"]["category"], "upload")
                proposal = result["steps"]["prepare"]["output"]
                self.assertEqual(proposal["suggested_queue"], "upload_review")
                self.assertEqual(proposal["decision"], "PENDING_HUMAN_REVIEW")
                self.assertTrue(proposal["review_required"])
                receipt = result["receipt"]
                self.assertEqual(hashlib.sha256(Path(receipt["path"]).read_bytes()).hexdigest(),
                                 receipt["sha256"])
                self.assertFalse(rt.submit(build_workflow("demo_001", SYNTHETIC))["created"])
            with Runtime(work, agents=registry()) as rt:
                self.assertEqual(rt.status("demo_001")["status"], "SUCCEEDED")

    def test_two_categories_use_one_core_registry(self):
        with tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=registry()) as rt:
                for name, summary, expected in [
                    ("password_case", "My password is not working", "access_review"),
                    ("billing_case", "This invoice has an issue", "billing_review"),
                ]:
                    rt.submit(build_workflow(name, {"case_id": name, "summary": summary}))
                    result = rt.run(name)
                    self.assertEqual(result["status"], "SUCCEEDED")
                    self.assertEqual(result["steps"]["prepare"]["output"]["suggested_queue"],
                                     expected)

    def test_invalid_inputs_are_rejected_before_execution(self):
        with self.assertRaises(SpecError):
            build_workflow("bad id", SYNTHETIC)
        with self.assertRaises(SpecError):
            build_workflow("ok", {"case_id": "S", "summary": "short"})
        with self.assertRaises(SpecError):
            build_workflow("ok", {**SYNTHETIC, "agent": "untrusted:path"})
        with tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=registry()) as rt:
                with self.assertRaises(SpecError):
                    rt.submit({"job_id": "unknown_agent", "input": SYNTHETIC,
                               "steps": [{"id": "x", "agent": "not.registered"}]})

    def test_mismatched_job_spec_rejected_and_bad_output_detected(self):
        with tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=registry()) as rt:
                rt.submit(build_workflow("same_id", SYNTHETIC))
                with self.assertRaisesRegex(ValueError, "job_id already exists"):
                    rt.submit(build_workflow("same_id", {"case_id": "SYN-001",
                                                        "summary": "Different request text"}))
        message = {"input": SYNTHETIC}
        with self.assertRaises(ValueError):
            agents.validate_classification(message, {"category": "other", "queue": "unknown"})
        with self.assertRaises(ValueError):
            agents.validate_preparation(
                {"input": SYNTHETIC, "dependencies": {"classify": agents.classify(message)}},
                {"decision": "APPROVED"})


if __name__ == "__main__":
    unittest.main()
