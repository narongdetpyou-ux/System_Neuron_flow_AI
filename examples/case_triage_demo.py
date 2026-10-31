"""Run a synthetic support case through the existing core.

From repository root: python -m examples.case_triage_demo
"""
import json
import tempfile

from neuron_flow import Runtime
from app.domains.case_triage import build_workflow, registry


def main():
    case = {"case_id": "SYN-001", "summary": "I cannot upload an attachment"}
    with tempfile.TemporaryDirectory(prefix="neuron-triage-demo-") as workspace:
        with Runtime(workspace, agents=registry()) as runtime:
            runtime.submit(build_workflow("synthetic_case_001", case))
            result = runtime.run("synthetic_case_001")
            print(json.dumps({
                "job_id": result["job_id"],
                "status": result["status"],
                "proposal": result["steps"]["prepare"]["output"],
                "receipt_sha256": result["receipt"]["sha256"] if result["receipt"] else None,
                "data_scope": "SYNTHETIC_EXAMPLE_ONLY",
            }, indent=2))
            if result["status"] != "SUCCEEDED":
                raise SystemExit("Pilot did not complete")


if __name__ == "__main__":
    main()
