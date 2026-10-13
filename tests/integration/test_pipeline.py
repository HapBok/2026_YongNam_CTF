import asyncio
import json
import os
import subprocess
import sys
import time
import unittest

from tests.support import ROOT,now,problem,workspace
from ctf_engine.cli import main
from ctf_engine.common import digest
from ctf_engine.profiles import load
from ctf_engine.supervisor import Supervisor


@unittest.skipUnless(os.name=="posix","Linux process groups required")
class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp,self.root,self.state,self.h=workspace();self.addCleanup(self.temp.cleanup)

    def test_eight_micro_challenges_full_pipeline(self):
        for i in range(8):problem(self.root,self.state,self.h,f"c{i:03d}",["web","pwn","rev","crypto","forensics","mobile","ai","misc"][i])
        started=time.monotonic()
        asyncio.run(asyncio.wait_for(Supervisor(self.root,True).run(8,until_idle=True),90))
        states=self.state.rows("SELECT state FROM challenges")
        self.assertEqual([x["state"] for x in states],["VERIFIED"]*8)
        self.assertLessEqual(self.state.meta("peak_active"),8)
        self.assertGreaterEqual(self.state.meta("peak_active"),7)
        self.assertEqual(self.state.one("PRAGMA integrity_check")["integrity_check"],"ok")
        self.assertFalse(self.state.rows("SELECT * FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')"))
        for ch in self.state.rows("SELECT * FROM challenges"):
            original=self.root/".local/inputs"/ch["id"]/"payload.txt"
            manifest=json.loads((self.root/"challenges"/ch["id"]/"input-manifest.json").read_text())
            self.assertEqual(digest(original),manifest[0]["sha256"])
            self.assertTrue((self.root/ch["candidate_ref"]).exists())
        self.assertLess(time.monotonic()-started,90)
        self.assertEqual(main(["--root",str(self.root),"solved","c000","--by","self"]),0)
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c000'")["state"],"ACCEPTED_SELF")

    def test_cancel_team_then_refill(self):
        for i in range(9):problem(self.root,self.state,self.h,f"c{i:03d}",description="mock-delay:2")
        proc=subprocess.Popen([sys.executable,str(self.root/"ctfctl.py"),"--root",str(self.root),"start","--workers","8","--mock","--until-idle"],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            task=self.state.one("SELECT * FROM tasks WHERE challenge_id='c000' AND status='RUNNING'")
            if task:break
            time.sleep(.05)
        else:self.fail("Worker did not start")
        began=time.monotonic();self.state.control("c000","ACCEPTED_TEAM","TEAM_SOLVE")
        while time.monotonic()-began<10:
            ninth=self.state.one("SELECT * FROM tasks WHERE challenge_id='c008' AND status IN ('RUNNING','COMMITTING','SUCCEEDED')")
            if ninth:break
            time.sleep(.05)
        else:self.fail("Ninth problem was not refilled")
        self.assertLess(time.monotonic()-began,5)
        self.state.setmeta("shutdown",True)
        proc.communicate(timeout=20)
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c000'")["state"],"ACCEPTED_TEAM")
        self.assertFalse(self.state.rows("SELECT * FROM artifacts WHERE generation=0 AND task_id IN (SELECT task_id FROM tasks WHERE challenge_id='c000')"))

    def test_cli_resume_and_self_gate(self):
        problem(self.root,self.state,self.h)
        self.assertEqual(main(["--root",str(self.root),"solved","c001","--by","self"]),2)
        self.assertEqual(main(["--root",str(self.root),"pause","c001"]),0)
        self.assertEqual(main(["--root",str(self.root),"resume","c001"]),0)
        self.assertEqual(len(self.state.rows("SELECT * FROM tasks WHERE status='READY'")),1)
