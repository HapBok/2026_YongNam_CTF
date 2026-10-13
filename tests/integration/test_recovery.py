import os
import signal
import subprocess
import sys
import time
import unittest

from tests.support import problem,workspace
from ctf_engine.common import now
from ctf_engine.supervisor import Supervisor


@unittest.skipUnless(os.name=="posix","Linux process control required")
class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp,self.root,self.state,self.h=workspace();self.addCleanup(self.temp.cleanup)

    def test_supervisor_crash_recovery_preserves_queue(self):
        for i in range(3):problem(self.root,self.state,self.h,f"c{i:03d}",description="mock-delay:30")
        proc=subprocess.Popen([sys.executable,str(self.root/"ctfctl.py"),"--root",str(self.root),"start","--workers","2","--mock"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            running=self.state.rows("SELECT * FROM tasks WHERE status='RUNNING'")
            if len(running)==2:break
            time.sleep(.05)
        else:self.fail("Two workers not running")
        proc.kill();proc.wait(timeout=5)
        # Explicitly expire the persisted heartbeat to avoid a 15s test sleep.
        self.state.setmeta("supervisor_heartbeat",now()-20)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            active=self.state.rows("SELECT * FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')")
            if not active:break
            time.sleep(.1)
        else:self.fail("Workers did not fence themselves after Supervisor loss")
        self.assertEqual(len(self.state.rows("SELECT * FROM tasks WHERE status='READY'")),1)
        self.assertEqual(len(self.state.rows("SELECT * FROM challenges WHERE state='FROZEN'")),2)
        self.assertEqual(self.state.one("PRAGMA integrity_check")["integrity_check"],"ok")
        restarted=Supervisor(self.root,True)
        restarted.initialize();restarted.tick()
        self.assertEqual(len(self.state.rows("SELECT * FROM tasks WHERE status='READY'")),1)
        self.state.setmeta("shutdown",True)
