import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor

from tests.support import now,problem,result,workspace
from ctf_engine import artifacts
from ctf_engine.common import atomic_json,digest
from ctf_engine.prescan import archive_listing
from ctf_engine.process_control import group_alive,process_token,terminate
from ctf_engine.profiles import load
from ctf_engine.supervisor import Supervisor


class FaultTest(unittest.TestCase):
    def setUp(self):
        self.temp,self.root,self.state,self.h=workspace();self.addCleanup(self.temp.cleanup)
        problem(self.root,self.state,self.h)
        self.profiles=load(self.root)

    def claim(self):
        self.state.enqueue("c001",self.profiles["intake-luna"])
        self.state.register("w01","token",os.getpid(),15)
        return self.state.claim("w01","token",15)

    def test_late_commit_and_artifact_collision(self):
        task=self.claim();dest=artifacts.prepare(self.root,task)
        value=result(task);atomic_json(dest/"result.json",value)
        self.state.ready_result(task,dest/"result.json")
        task=self.state.one("SELECT * FROM tasks WHERE task_id=?",(task["task_id"],))
        self.state.control("c001","ACCEPTED_TEAM")
        Supervisor(self.root,True).commit(task)
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c001'")["state"],"ACCEPTED_TEAM")
        self.assertFalse(self.state.rows("SELECT * FROM artifacts"))
        p=dest/"evidence.txt";p.write_text("first")
        value["artifacts"]=[{"path":"evidence.txt","kind":"evidence","sha256":digest(p)}]
        checked=artifacts.check(self.root,task,value)
        artifacts.promote(self.root,task,value,checked)
        target=self.root/"challenges/c001/evidence"/task["task_id"]/"evidence.txt"
        target.write_text("different")
        with self.assertRaises(ValueError):artifacts.promote(self.root,task,value,checked)

    def test_archive_traversal_and_bomb(self):
        p=self.root/"bad.zip"
        with zipfile.ZipFile(p,"w") as z:z.writestr("../outside","bad")
        with self.assertRaises(ValueError):archive_listing(p)
        p=self.root/"bomb.zip"
        with zipfile.ZipFile(p,"w",compression=zipfile.ZIP_DEFLATED) as z:z.writestr("data",b"0"*3000000)
        with self.assertRaises(ValueError):archive_listing(p,max_bytes=1000)

    def test_model_retry_fallback_and_quota(self):
        task=self.claim();s=Supervisor(self.root,True)
        self.state.ready_result(task,"",json.dumps({"kind":"MODEL_NOT_FOUND","delay":0}))
        s.commit(self.state.one("SELECT * FROM tasks WHERE task_id=?",(task["task_id"],)))
        ready=self.state.one("SELECT * FROM tasks WHERE status='READY'")
        self.assertEqual(ready["profile_id"],"intake-fallback")
        task=self.state.claim("w01","token",15)
        self.state.ready_result(task,"",json.dumps({"kind":"QUOTA","delay":120}))
        s.commit(self.state.one("SELECT * FROM tasks WHERE task_id=?",(task["task_id"],)))
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c001'")["state"],"QUOTA_WAIT")

    def test_expired_orphan_recovery(self):
        task=self.claim()
        with self.state.tx() as c:c.execute("UPDATE tasks SET lease_until=?",(now()-1,))
        Supervisor(self.root,True).cancel_and_recover()
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c001'")["state"],"FROZEN")
        self.assertEqual(self.state.one("SELECT status FROM tasks WHERE task_id=?",(task["task_id"],))["status"],"CANCELLED")

    def test_partial_files_never_become_downstream_inputs(self):
        task=self.claim()
        orphan=self.root/"challenges/c001/solution"/"orphan-task"/"uncommitted.py"
        orphan.parent.mkdir(parents=True);orphan.write_text("uncommitted")
        dest=artifacts.prepare(self.root,task)
        self.assertFalse((dest/"previous/solution/orphan-task/uncommitted.py").exists())

    def test_secret_cannot_be_published(self):
        task=self.claim();dest=artifacts.prepare(self.root,task)
        (dest/"candidate.flag").write_bytes(b"TEST{secret}")
        p=dest/"proof.txt";p.write_bytes(b"decoded = TEST{secret}")
        value=result(task);value["candidate_flag_ref"]="candidate.flag"
        value["artifacts"]=[{"path":"proof.txt","kind":"evidence","sha256":digest(p)}]
        with self.assertRaises(ValueError):artifacts.check(self.root,task,value)

    def test_cumulative_gate_survives_pause(self):
        task=self.claim()
        with self.state.tx() as c:
            c.execute("UPDATE tasks SET started=?,finished=?,status='PAUSED' WHERE task_id=?",(now()-2800,now(),task["task_id"]))
            c.execute("UPDATE challenges SET state='SOLVING'")
        Supervisor(self.root,True).gates()
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c001'")["state"],"FROZEN")

    def test_rollback_and_quota_reserve(self):
        with self.assertRaises(RuntimeError):
            with self.state.tx() as c:
                c.execute("UPDATE challenges SET state='DROPPED'")
                raise RuntimeError("injected failure")
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c001'")["state"],"PRESCANNED")
        self.state.setmeta("quota_remaining",15)
        self.state.enqueue("c001",self.profiles["general-sol"])
        self.state.enqueue("c001",self.profiles["verify-general"],priority=100)
        self.state.register("w01","token",os.getpid(),15)
        self.assertEqual(self.state.claim("w01","token",15)["stage"],"verify-general")

    def test_transient_retry_once(self):
        task=self.claim();s=Supervisor(self.root,True)
        self.state.ready_result(task,"",json.dumps({"kind":"TRANSIENT","delay":5}))
        s.commit(self.state.one("SELECT * FROM tasks WHERE task_id=?",(task["task_id"],)))
        with self.state.tx() as c:c.execute("UPDATE tasks SET available_at=0 WHERE status='READY'")
        task=self.state.claim("w01","token",15)
        self.state.ready_result(task,"",json.dumps({"kind":"TRANSIENT","delay":5}))
        s.commit(self.state.one("SELECT * FROM tasks WHERE task_id=?",(task["task_id"],)))
        self.assertFalse(self.state.rows("SELECT task_id FROM tasks WHERE status='READY'"))
        self.assertEqual(self.state.one("SELECT state FROM challenges WHERE id='c001'")["state"],"FROZEN")

    def test_five_second_db_lock_does_not_lose_claim(self):
        self.state.enqueue("c001",self.profiles["intake-luna"])
        self.state.register("w01","token",os.getpid(),15)
        c=self.state.connect();c.execute("BEGIN IMMEDIATE")
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.state.claim,"w01","token",15)
                time.sleep(5)
                c.rollback()
                task=future.result(timeout=10)
                self.assertIsNotNone(task)
        finally:c.close()
        self.assertEqual(self.state.one("PRAGMA integrity_check")["integrity_check"],"ok")

    @unittest.skipUnless(os.name=="posix","Linux process group test")
    def test_group_kill(self):
        async def test():
            proc=await asyncio.create_subprocess_exec(sys.executable,"-c","import subprocess,time,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)",start_new_session=True,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(.1)
            self.assertTrue(process_token(proc.pid))
            await terminate(proc,.1)
            self.assertIsNotNone(proc.returncode)
            await asyncio.sleep(.1)
            # Zombies can retain a group briefly; none may be executing.
            for statfile in Path("/proc").glob("[0-9]*/stat"):
                try:
                    raw=statfile.read_text();parts=raw[raw.rfind(")")+2:].split()
                    self.assertFalse(int(parts[2])==proc.pid and parts[0]!="Z")
                except (OSError,ValueError):pass
        asyncio.run(test())
