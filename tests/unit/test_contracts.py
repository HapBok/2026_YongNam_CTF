import json
import random
import unittest

from tests.support import ROOT,result
from ctf_engine import adapter,contracts
from ctf_engine.common import contained,strict_json
from ctf_engine.profiles import load
from ctf_engine.scheduler import Scheduler


class ContractsTest(unittest.TestCase):
    def test_handoff_and_fuzz(self):
        task={"task_id":"t1","challenge_id":"c001","generation":0}
        self.assertEqual(contracts.handoff(json.dumps(result(task)).encode(),ROOT,task)["generation"],0)
        rng=random.Random(42)
        for _ in range(10000):
            raw=bytes(rng.randrange(256) for _ in range(rng.randrange(0,100)))
            try:contracts.handoff(raw,ROOT,task)
            except (ValueError,RecursionError):pass
            else:self.fail("Random malformed bytes accepted")
        for raw in [b'{"x":1,"x":2}',b'{"x":NaN}',b'"'+b'x'*32769+b'"']:
            with self.assertRaises(ValueError):strict_json(raw)

    def test_routing_and_verify_boundary(self):
        profiles=load(ROOT);s=Scheduler(ROOT,profiles)
        task={"stage":"intake","profile_id":"intake-luna","task_id":"t1","challenge_id":"c001","generation":0}
        value=result(task)
        self.assertEqual(s.next(task,value)[0],"quick-luna")
        task.update(stage="triage",profile_id="triage-sol")
        value["classification"]["category"]="pwn"
        self.assertEqual(s.next(task,value)[0],"security-daybreak")
        value["stage_status"]="verified"
        with self.assertRaises(ValueError):s.next(task,value)

    def test_argv_and_fresh_verification(self):
        profiles=load(ROOT)
        args=adapter.build_command("codex",profiles["verify-general"],ROOT,ROOT/"schema.json","old-session")
        self.assertNotIn("resume",args)
        self.assertIn('service_tier="default"',args)
        self.assertIn("standard",args)
        with self.assertRaises(ValueError):adapter.build_command("codex",profiles["security-daybreak"],ROOT,ROOT/"schema.json")
        args=adapter.build_command("codex",profiles["general-sol"],ROOT,ROOT/"schema.json","old-session")
        self.assertIn("resume",args)

    def test_path_escape(self):
        for p in ["../outside","/tmp/outside","C:/outside","a\\b"]:
            with self.assertRaises(ValueError):contained(ROOT,p)

    def test_provider_errors(self):
        self.assertEqual(adapter.error_kind("429 Retry-After: 30"),("QUOTA",30))
        self.assertEqual(adapter.error_kind("404 model not found")[0],"MODEL_NOT_FOUND")
        self.assertEqual(adapter.error_kind("503 service unavailable")[0],"TRANSIENT")
