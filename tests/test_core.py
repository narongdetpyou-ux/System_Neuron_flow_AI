"""Domain-independent end-to-end checks for the extracted runtime."""
import tempfile
import unittest
from pathlib import Path
from neuron_flow import AgentDefinition, Runtime, SpecError
from neuron_flow.case_memory import CaseMemory
from neuron_flow.evaluation import candidate_gate, route_variant
from neuron_flow.integrity import write_manifest, verify_manifest
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
                with self.assertRaises(SpecError):
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
    def test_telemetry_and_manifest(self):
        telemetry=Telemetry()
        telemetry.record("generic_phase",1)
        self.assertEqual(telemetry.snapshot()["phases"]["generic_phase"]["total_count"],1)
        with tempfile.TemporaryDirectory() as temp:
            Path(temp,"sample.txt").write_text("evidence",encoding="utf-8")
            write_manifest(temp)
            result=verify_manifest(temp)
            self.assertIsNotNone(result)

if __name__=="__main__":
    unittest.main()
