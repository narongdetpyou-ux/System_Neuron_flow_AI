"""Domain-independent end-to-end checks for the extracted runtime."""
import tempfile
import unittest
from pathlib import Path
from neuron_flow import AgentDefinition, Runtime, SpecError
from neuron_flow.case_memory import CaseMemory
from neuron_flow.evaluation import candidate_gate, route_variant
from neuron_flow.integrity import write_manifest, verify_manifest
from neuron_flow.model import MAX_MESSAGE_BYTES, MessageSizeError, decode
from neuron_flow.telemetry import Telemetry
from tests import core_agents

def registry():
    return [
        AgentDefinition("echo","tests.core_agents:echo",core_agents.validate_echo),
        AgentDefinition("copy","tests.core_agents:copy_dependency",core_agents.validate_copy),
        AgentDefinition("retry","tests.core_agents:transient",core_agents.validate_ok),
        AgentDefinition("permanent","tests.core_agents:permanent",core_agents.validate_ok)
    ]
def workflow(job_id="portable"):
    return {"job_id":job_id,"input":{"value":"hello"},
            "steps":[{"id":"first","agent":"echo"},
                     {"id":"second","agent":"copy","depends_on":["first"]}]}

class CoreLogicTests(unittest.TestCase):
    def test_workflow_and_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            with Runtime(temp,agents=registry()) as runtime:
                self.assertTrue(runtime.ingest(workflow())["created"])
                result=runtime.run("portable")
                self.assertEqual(result["status"],"SUCCEEDED")
                self.assertEqual(result["steps"]["second"]["output"],{"copied":"hello"})
                self.assertFalse(runtime.submit(workflow())["created"])
                with self.assertRaisesRegex(ValueError, "job_id already exists"):
                    runtime.submit({"job_id":"portable","input":{"value":"different"},"steps":workflow()["steps"]})
            with Runtime(temp,agents=registry()) as restarted:
                self.assertEqual(restarted.status("portable")["status"],"SUCCEEDED")
                self.assertEqual(restarted.run("portable")["status"],"SUCCEEDED")
    def test_retry_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with Runtime(temp,agents=registry()) as rt:
                rt.submit({"job_id":"retry_job","input":{},"steps":[{"id":"a","agent":"retry","max_attempts":2}]})
                self.assertEqual(rt.run("retry_job")["steps"]["a"]["attempts"],2)
                rt.submit({"job_id":"bad_job","input":{},"steps":[{"id":"a","agent":"permanent","max_attempts":2}]})
                self.assertEqual(rt.run("bad_job")["status"],"FAILED")
    def test_case_memory_and_non_leakage(self):
        with tempfile.TemporaryDirectory() as temp:
            memory=CaseMemory(temp)
            try:
                value=memory.learn(b"source",b"approved",b"approved",reviewer="operator",profile=[0,0,0,0,0,0],
                                   method="extract",policy_version="v1",cluster_id="one")
                self.assertEqual(value["outcome"],"MATCH")
                self.assertEqual(memory.retrieve([0,0,0,0,0,0],"v1")[0]["case_id"],value["case_id"])
                with self.assertRaises(ValueError):
                    memory.learn(b"s",b"a",b"a",reviewer="operator",profile=[0]*6,method="x",
                                 policy_version="v1",cluster_id="two",split="holdout")
            finally: memory.close()
    def test_evaluation(self):
        record={"case_id":"a","cluster_id":"a","split":"holdout","source_sha256":"hash",
                "group":"generic","outcome":"OK","latency_ms":5,"attempts":1,"first_method_success":True}
        self.assertTrue(candidate_gate([record],[dict(record)])["accepted"])
        self.assertFalse(candidate_gate([record],[dict(record,outcome="WRONG")])["accepted"])
        self.assertEqual(route_variant("x"),route_variant("x"))
    def test_telemetry_phases_are_step_ids(self):
        # Roadmap 1.1: every agent step is recorded under its own step id; no legacy names remain.
        with tempfile.TemporaryDirectory() as temp:
            telemetry=Telemetry()
            with Runtime(temp,agents=registry(),telemetry=telemetry) as rt:
                self.assertEqual(rt.run(rt.submit(workflow())["job_id"])["status"],"SUCCEEDED")
                rt.submit({"job_id":"bad_job","input":{},"steps":[{"id":"doomed","agent":"permanent","max_attempts":2}]})
                self.assertEqual(rt.run("bad_job")["status"],"FAILED")
            phases=telemetry.snapshot()["phases"]
            self.assertEqual(phases["first"]["total_count"],1)
            self.assertEqual(phases["second"]["total_count"],1)
            self.assertEqual((phases["doomed"]["total_count"],phases["doomed"]["errors_retained"]),(1,1))  # permanent: no retry
            self.assertIn("contract_validation",phases)
            self.assertNotIn("agent",phases)
            self.assertFalse({"validation","calculation","verification"} & set(phases))
    def test_telemetry_and_manifest(self):
        telemetry=Telemetry()
        telemetry.record("generic_phase",1)
        self.assertEqual(telemetry.snapshot()["phases"]["generic_phase"]["total_count"],1)
        with tempfile.TemporaryDirectory() as temp:
            Path(temp,"sample.txt").write_text("evidence",encoding="utf-8")
            write_manifest(temp)
            result=verify_manifest(temp)
            self.assertIsNotNone(result)


class JsonContractTests(unittest.TestCase):
    """decode() refuses every input it cannot read with SpecError (ADR-025), so a caller that catches SpecError
    never meets another error type (robustness benchmark: SYN-COR-040, SYN-COR-041)."""

    def test_numbers_too_long_to_read_and_broken_text_raise_spec_error(self):
        unreadable = (b'{"a":1' + b"0" * 5000 + b"}",   # past Python's 4,300-digit limit: was ValueError
                      '"\ud800"',                      # text holding a lone surrogate: was UnicodeEncodeError
                      b"\xff\xfe", b"{not json", b"[" * 100000)
        for data in unreadable:
            with self.subTest(data=repr(data)[:40]):
                with self.assertRaises(SpecError):
                    decode(data)

    def test_specific_refusals_keep_their_messages_and_good_json_still_reads(self):
        with self.assertRaisesRegex(SpecError, "Duplicate JSON field: a"):
            decode(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(SpecError, "Non-finite JSON number"):
            decode(b"[NaN]")
        with self.assertRaises(MessageSizeError):
            decode(b'"' + b"x" * MAX_MESSAGE_BYTES + b'"')
        self.assertEqual(decode(b'{"a":[1,2.5,"x\\u0e01"],"n":' + b"9" * 4000 + b"}"),
                         {"a": [1, 2.5, "x\u0e01"], "n": int("9" * 4000)})

if __name__=="__main__":
    unittest.main()
