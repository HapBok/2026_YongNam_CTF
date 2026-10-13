from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal

from . import artifacts,contracts,scope
from .common import INACTIVE,atomic_json,contained,now,read_json,settings,uid
from .process_control import InstanceLock,group_alive,process_token,same_process
from .profiles import load
from .scheduler import Scheduler
from .state import State
from .fingerprint import calculate


class Supervisor:
    def __init__(self,root,mock=False):
        self.root=Path(root).resolve(); self.mock=mock
        self.state=State(root); self.profiles=load(root); self.limits=settings(root)
        self.scheduler=Scheduler(root,self.profiles); self.stopping=False

    def initialize(self):
        if not self.mock:
            preflight=self.root/"reports/preflight.json"
            acceptance=self.root/"reports/acceptance.json"
            if not preflight.exists() or not acceptance.exists():
                raise ValueError("NO_GO: live preflight and local acceptance evidence required")
            live,local=read_json(preflight),read_json(acceptance)
            build=calculate(self.root)
            if not live.get("ready") or not local.get("passed") or live.get("build_fingerprint")!=build or local.get("build_fingerprint")!=build:
                raise ValueError("NO_GO: failed/stale readiness evidence; run acceptance.py and doctor --live")
            if now()-live["timestamp"]>86400:
                raise ValueError("NO_GO: live canary is older than 24 hours")
        current,h=scope.load(self.root,self.mock)
        for ch in self.state.rows("SELECT id,scope_hash FROM challenges WHERE state NOT IN ('ACCEPTED_SELF','ACCEPTED_TEAM','DROPPED')"):
            scope.validate(current,ch["id"])
            if ch["scope_hash"]!=h:
                raise ValueError("IMPORTED_SCOPE_HASH_MISMATCH")
        old=self.state.meta("scope_hash")
        if old and old!=h:
            raise ValueError("RUN_SCOPE_HASH_MISMATCH: initialize a new authorized run")
        self.state.setmeta("scope_hash",h)
        self.state.setmeta("mock",self.mock)
        self.state.setmeta("shutdown",False)
        self.state.setmeta("supervisor_heartbeat",now())
        self.state.setmeta("supervisor_pid",os.getpid())
        self.state.setmeta("supervisor_process_token",process_token(os.getpid()))

    def cancel_and_recover(self):
        for task in self.state.rows("SELECT * FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')"):
            expired=(task["lease_until"] or 0)<now()
            if task["status"]!="CANCELLING" and not expired:
                continue
            if task["status"]=="CANCELLING" and task["error"]!="HARD_STOP" and now()-task["available_at"]<self.limits["cancel_grace_seconds"]:
                continue
            pid=task["pid"]
            if pid and same_process(pid,task["process_token"]):
                try:
                    os.killpg(pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                continue
            # A leader may exit before its descendants. Its stored process group
            # remains reserved until group absence is positively confirmed.
            if pid and group_alive(pid):
                self.state.setmeta("dispatch_blocked","UNCONFIRMED_PROCESS_GROUP")
                continue
            if expired and task["status"]!="CANCELLING":
                ch=self.state.one("SELECT state FROM challenges WHERE id=?",(task["challenge_id"],))
                if ch and ch["state"] not in INACTIVE:
                    self.state.control(task["challenge_id"],"FROZEN","ORPHAN_LEASE_REVIEW_REQUIRED")
            self.state.release(task["task_id"],"CANCELLED","PROCESS_EXIT_CONFIRMED")

    def fail(self,task,error):
        try:
            parsed=json.loads(error)
            kind=parsed.get("kind","PROVIDER_ERROR"); delay=parsed.get("delay",0)
        except (ValueError,TypeError):
            kind=error.split(":",1)[0]; delay=0
        profile=self.profiles[task["profile_id"]]
        target=None; wait=0; terminal="FROZEN"
        if kind=="MODEL_NOT_FOUND" and profile.fallback:
            target=profile.fallback
        elif kind in {"TRANSIENT","TIMEOUT"} and task["retries"]<1:
            target=profile.id; wait=5
        elif kind=="QUOTA" and delay<=60 and task["retries"]<1:
            target=profile.id; wait=max(1,delay)
        elif kind=="QUOTA": terminal="QUOTA_WAIT"
        elif kind=="MANUAL_DAYBREAK_REQUIRED": terminal=kind
        elif kind.startswith("SCOPE") or kind in {"AUTH_REQUIRED","ORIGINAL_HASH_MISMATCH"}: terminal="FAILED_CLOSED"
        with self.state.tx() as c:
            row=c.execute("SELECT generation FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()
            if not row or row[0]!=task["generation"]:
                c.execute("UPDATE tasks SET status='CANCELLED',finished=? WHERE task_id=?",(now(),task["task_id"]))
                return
            status="TIMED_OUT" if kind=="TIMEOUT" else "INVALID_OUTPUT" if kind=="INVALID_OUTPUT" else "FAILED"
            c.execute("UPDATE tasks SET status=?,finished=?,error=? WHERE task_id=?",(status,now(),kind,task["task_id"]))
            self.state.event(c,"RUN_FAILED",task=task,kind=kind,retry_profile=target)
            if target:
                self.state.enqueue(task["challenge_id"],self.profiles[target],task["priority"],task["task_id"],task["hypothesis_key"],task["session_id"] if target==profile.id else None,c,task["retries"]+1,wait)
            else:
                c.execute("UPDATE challenges SET state=?,last_error=? WHERE id=?",(terminal,kind,task["challenge_id"]))

    def commit(self,task):
        if task["error"]:
            self.fail(task,task["error"]); return
        try:
            expected=self.root/".runtime/attempts"/task["task_id"]/"result.json"
            if Path(task["result_path"]).resolve()!=expected.resolve():
                raise ValueError("RESULT_PATH_MISMATCH")
            value=contracts.handoff(expected.read_bytes(),self.root,task)
            checked=artifacts.check(self.root,task,value)
            next_id,priority,newstate=self.scheduler.next(task,value)
            with self.state.tx() as c:
                ch=c.execute("SELECT * FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()
                lease=c.execute("SELECT status,lease_id FROM tasks WHERE task_id=?",(task["task_id"],)).fetchone()
                if not ch or ch["generation"]!=task["generation"] or ch["state"] in INACTIVE or not lease or lease[0]!="COMMITTING" or lease[1]!=task["lease_id"] or (task["lease_until"] or 0)<now():
                    self.state.event(c,"STALE_COMMIT_REJECTED",task=task)
                    c.execute("UPDATE tasks SET status='CANCELLED',finished=? WHERE task_id=?",(now(),task["task_id"]))
                    artifacts.quarantine(self.root,task,"STALE_COMMIT")
                    return
                promoted,secret=artifacts.promote(self.root,task,value,checked)
                artifacts.notes(self.root,task,value,newstate)
                for a in promoted:
                    c.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)",(task["task_id"],a["canonical"],a["sha256"],a["kind"],task["generation"]))
                elapsed=max(0,now()-(task["started"] or now()))
                solve=elapsed if task["stage"] not in {"intake","triage"} else 0
                classification=elapsed if task["stage"] in {"intake","triage"} else 0
                c.execute("UPDATE tasks SET status='SUCCEEDED',finished=? WHERE task_id=?",(now(),task["task_id"]))
                c.execute("UPDATE challenges SET state=?,category=?,candidate_ref=COALESCE(?,candidate_ref),last_error='',solve_seconds=solve_seconds+?,classification_seconds=classification_seconds+?,evidence_at=CASE WHEN ? THEN ? ELSE evidence_at END WHERE id=?",(newstate,value["classification"]["category"],secret,solve,classification,bool(value["evidence_delta"]),now(),task["challenge_id"]))
                self.state.event(c,"COMMITTED",task=task,state=newstate,artifact_count=len(promoted))
                if newstate=="VERIFIED":
                    # Fence any alternate solve before it can overwrite verification.
                    c.execute("UPDATE challenges SET generation=generation+1 WHERE id=?",(task["challenge_id"],))
                    c.execute("UPDATE tasks SET status='CANCELLING',error='VERIFIED' WHERE challenge_id=? AND status IN ('LEASED','STARTING','RUNNING','COMMITTING')",(task["challenge_id"],))
                    c.execute("UPDATE tasks SET status='CANCELLED',finished=? WHERE challenge_id=? AND status='READY'",(now(),task["challenge_id"]))
                if next_id:
                    p=self.profiles[next_id]
                    session=task["session_id"] if p.resumable and task["profile_id"]==p.id else None
                    self.state.enqueue(task["challenge_id"],p,priority,task["task_id"],task["hypothesis_key"],session,c)
        except (ValueError,OSError,KeyError,TypeError,RecursionError) as e:
            artifacts.quarantine(self.root,task,type(e).__name__+":"+str(e)[:160])
            self.fail(task,"INVALID_OUTPUT:"+str(e)[:160])

    def gates(self):
        for ch in self.state.rows("SELECT * FROM challenges"):
            if ch["state"] in INACTIVE: continue
            tasks=self.state.rows("SELECT * FROM tasks WHERE challenge_id=? AND generation=? AND status IN ('LEASED','STARTING','RUNNING','COMMITTING')",(ch["id"],ch["generation"]))
            timings=self.state.rows("SELECT stage,started,finished FROM tasks WHERE challenge_id=? AND started IS NOT NULL",(ch["id"],))
            duration=lambda t:max(0,(t["finished"] or now())-t["started"])
            total=sum(duration(t) for t in timings)
            hard=self.limits["hard_gate_seconds"]+ch["extension"]*self.limits["extension_seconds"]
            if total>=hard:
                self.state.control(ch["id"],"FROZEN","HARD_GATE",True); continue
            classified=ch["category"]!="unknown"
            classification=sum(duration(t) for t in timings if t["stage"] in {"intake","triage"})
            if not classified and classification>=self.limits["classification_gate_seconds"]:
                self.state.control(ch["id"],"FROZEN","CLASSIFICATION_GATE"); continue
            solving=[t for t in tasks if t["stage"] not in {"intake","triage"} and not t["stage"].startswith("verify")]
            solve=sum(duration(t) for t in timings if t["stage"] not in {"intake","triage"} and not t["stage"].startswith("verify"))
            if solving and solve>=self.limits["progress_gate_seconds"] and not ch["primitive"] and not ch["candidate_ref"]:
                self.state.control(ch["id"],"FROZEN","NO_PRIMITIVE_GATE"); continue
            if solving and now()-(ch["evidence_at"] or now())>=self.limits["evidence_gate_seconds"]:
                task=solving[0]
                if ch["rotation"]:
                    self.state.control(ch["id"],"FROZEN","NO_EVIDENCE_AFTER_ROTATION")
                else:
                    self.state.control(ch["id"],"PAUSED_MANUAL","EVIDENCE_ROTATION")
                    with self.state.tx() as c:
                        c.execute("UPDATE challenges SET state='SOLVING',rotation=1,evidence_at=? WHERE id=?",(now(),ch["id"]))
                        profile=self.profiles["security-daybreak" if self.profiles[task["profile_id"]].daybreak else "rescue-astra"]
                        self.state.enqueue(ch["id"],profile,50,task["task_id"],"rotation-1",None,c)

    def tick(self):
        if now()-self.state.meta("supervisor_heartbeat",0)>=self.limits["heartbeat_seconds"]:
            self.state.setmeta("supervisor_heartbeat",now())
        self.cancel_and_recover()
        for task in self.state.rows("SELECT * FROM tasks WHERE status='COMMITTING' ORDER BY started,task_id"):
            self.commit(task)
        self.gates()
        mode=self.scheduler.mode(self.state)
        if self.state.meta("mode")!=mode:self.state.setmeta("mode",mode)
        if not self.state.meta("dispatch_blocked"):
            for ch in self.state.rows("SELECT * FROM challenges WHERE state IN ('NEW','PRESCANNED') ORDER BY created,id"):
                exists=self.state.one("SELECT task_id FROM tasks WHERE challenge_id=? AND generation=? AND status IN ('READY','LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')",(ch["id"],ch["generation"]))
                if not exists:
                    self.state.enqueue(ch["id"],self.profiles["intake-luna"],90)

    async def run(self,workers=8,external=False,until_idle=False):
        if not 1<=workers<=8: raise ValueError("Workers must be 1..8")
        with InstanceLock(self.root/".runtime/supervisor.lock"):
            self.initialize(); self.state.setmeta("workers",workers)
            loop=asyncio.get_running_loop()
            if os.name=="posix":
                loop.add_signal_handler(signal.SIGTERM,lambda:setattr(self,"stopping",True))
                loop.add_signal_handler(signal.SIGINT,lambda:setattr(self,"stopping",True))
            children=[]
            worker_commands=[]
            if not external:
                import sys
                for i in range(workers):
                    cmd=[sys.executable,str(self.root/"ctfctl.py"),"--root",str(self.root),"worker","--id",f"w{i+1:02d}"]
                    if self.mock:cmd.append("--mock")
                    worker_commands.append(cmd)
                    children.append(await asyncio.create_subprocess_exec(*cmd))
            idle=0
            try:
                while not self.stopping and not self.state.meta("shutdown",False):
                    self.tick()
                    if not external:
                        for i,child in enumerate(children):
                            if child.returncode is not None:
                                worker_id=f"w{i+1:02d}"
                                old=self.state.one("SELECT heartbeat FROM workers WHERE id=?",(worker_id,))
                                owns=self.state.one("SELECT task_id FROM tasks WHERE worker_id=? AND status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')",(worker_id,))
                                if not owns and (not old or old["heartbeat"]<now()-self.limits["lease_seconds"]):
                                    children[i]=await asyncio.create_subprocess_exec(*worker_commands[i])
                    pending=self.state.one("SELECT COUNT(*) AS n FROM tasks WHERE status IN ('READY','LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')")["n"]
                    idle=idle+1 if pending==0 else 0
                    if until_idle and idle>=5:break
                    await asyncio.sleep(self.limits["poll_seconds"])
            finally:
                self.state.setmeta("shutdown",True)
                for ch in self.state.rows("SELECT DISTINCT ch.id FROM challenges ch JOIN tasks t ON t.challenge_id=ch.id WHERE t.status IN ('LEASED','STARTING','RUNNING')"):
                    self.state.control(ch["id"],"PAUSED_MANUAL","SUPERVISOR_SHUTDOWN")
                for child in children:
                    try: await asyncio.wait_for(child.wait(),10)
                    except asyncio.TimeoutError: child.kill(); await child.wait()
                for _ in range(20):
                    self.cancel_and_recover()
                    if not self.state.one("SELECT task_id FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING')"):break
                    await asyncio.sleep(.1)
                self.state.backup(self.root/"reports/run-snapshots"/(uid("state")+".db"))
                self.state.setmeta("supervisor_heartbeat",0)
