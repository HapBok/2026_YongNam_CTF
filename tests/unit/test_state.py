from concurrent.futures import ThreadPoolExecutor
import unittest

from tests.support import now,problem,workspace
from ctf_engine.profiles import load


class StateTest(unittest.TestCase):
    def setUp(self):
        self.temp,self.root,self.state,self.h=workspace()
        self.addCleanup(self.temp.cleanup)
        self.profiles=load(self.root)

    def test_atomic_eight_cap_and_generation(self):
        for i in range(12):
            cid=f"c{i:03d}";problem(self.root,self.state,self.h,cid)
            self.state.enqueue(cid,self.profiles["intake-luna"])
            self.state.register(f"w{i}",f"token{i}",100+i,15)
        def claim(i):return self.state.claim(f"w{i}",f"token{i}",15)
        with ThreadPoolExecutor(max_workers=12) as pool:tasks=list(pool.map(claim,range(12)))
        tasks=[t for t in tasks if t]
        self.assertEqual(len(tasks),8)
        self.assertEqual(self.state.meta("peak_active"),8)
        task=tasks[0]
        self.state.control(task["challenge_id"],"ACCEPTED_TEAM","team solved")
        self.assertFalse(self.state.heartbeat(task["worker_id"],"token"+task["worker_id"][1:],task,15))
        self.assertFalse(self.state.ready_result(task,"ignored"))
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id=?",(task["challenge_id"],))["state"],"ACCEPTED_TEAM")

    def test_one_problem_breadth_and_distinct_depth(self):
        problem(self.root,self.state,self.h)
        for hypothesis in ("one","one","two"):
            self.state.enqueue("c001",self.profiles["general-sol"],hypothesis=hypothesis)
        for i in range(3):self.state.register(f"w{i}",str(i),100+i,15)
        self.assertIsNotNone(self.state.claim("w0","0",15,depth=False))
        self.assertIsNone(self.state.claim("w1","1",15,depth=False))
        self.assertEqual(self.state.claim("w1","1",15,depth=True)["hypothesis_key"],"two")
        self.assertIsNone(self.state.claim("w2","2",15,depth=True))

    def test_expired_lease_and_terminal(self):
        problem(self.root,self.state,self.h)
        self.state.enqueue("c001",self.profiles["intake-luna"])
        self.state.register("w01","token",100,15)
        task=self.state.claim("w01","token",15)
        with self.state.tx() as c:c.execute("UPDATE tasks SET lease_until=?",(now()-1,))
        self.assertFalse(self.state.heartbeat("w01","token",task,15))
        self.assertFalse(self.state.ready_result(task,"ignored"))
        self.state.control("c001","ACCEPTED_TEAM")
        with self.assertRaises(ValueError):self.state.control("c001","PAUSED_MANUAL")
