import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

from tests.support import ROOT,now,problem,workspace
from ctf_engine.cli import main
from ctf_engine.common import digest
from ctf_engine.profiles import load
from ctf_engine.supervisor import Supervisor
from ctf_engine import metadata


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

    def test_metadata_generation_shares_eight_live_mock_worker_slots(self):
        for index in range(12):problem(self.root,self.state,self.h,f'c{index:03d}',description='mock-delay:0.5')
        folder=self.root/'incoming/c100';(folder/'info').mkdir(parents=True)
        (folder/'info/01.png').write_bytes(b'\x89PNG\r\n\x1a\nunit-fixture')
        binary=self.root/'.local/toolchains/codex/bin/codex';binary.parent.mkdir(parents=True)
        shutil.copyfile(ROOT/'tests/fixtures/mock_metadata.py',binary);binary.chmod(0o700)

        async def exercise():
            supervisor=asyncio.create_task(Supervisor(self.root,True).run(8,until_idle=True))
            try:
                deadline=time.monotonic()+20
                while self.state.one("SELECT COUNT(*) n FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')")['n']<8:
                    if time.monotonic()>deadline:self.fail('Eight workers did not claim tasks')
                    await asyncio.sleep(.05)
                with contextlib.redirect_stdout(io.StringIO()):
                    generation=asyncio.create_task(metadata.generate(self.root,self.state,folder))
                    while not generation.done():
                        snapshot=self.state.one("SELECT (SELECT COUNT(*) FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')) n, (SELECT value FROM meta WHERE key='metadata_slot') metadata")
                        slot=json.loads(snapshot['metadata']) if snapshot['metadata'] else None
                        self.assertLessEqual(snapshot['n']+int(bool(slot and slot['phase']=='running')),8)
                        await asyncio.sleep(.05)
                    report=await generation
                self.assertTrue(report['passed'])
                self.assertIsNone(self.state.meta('metadata_slot'))
                await asyncio.wait_for(supervisor,40)
            finally:
                if not supervisor.done():
                    self.state.setmeta('shutdown',True)
                    await asyncio.wait_for(supervisor,15)
        import contextlib
        import io
        asyncio.run(exercise())
        self.assertEqual(self.state.meta('peak_active'),8)
        self.assertEqual(self.state.one("SELECT COUNT(*) n FROM challenges WHERE state='VERIFIED'")['n'],12)
