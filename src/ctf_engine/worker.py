from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time

from . import adapter,artifacts,contracts,scope
from .common import atomic_json,contained,digest,now,read_json,settings,uid
from .process_control import process_token,terminate
from .profiles import load
from .state import State
from .permissions import policy,protect


class Worker:
    def __init__(self,root,worker_id,mock=False):
        self.root=Path(root).resolve(); self.id=worker_id; self.mock=mock
        self.state=State(root); self.limits=settings(root); self.profiles=load(root)
        self.token=uid("worker"); self.current=None; self.proc=None
        self.stopping=False; self.last_interrupt=0
        self.last_heartbeat=0

    def interrupt(self):
        if self.current:
            hard=time.monotonic()-self.last_interrupt<5
            self.last_interrupt=time.monotonic()
            self.state.control(self.current["challenge_id"],"DIRTY_PAUSED" if hard else "PAUSED_MANUAL","USER_INTERRUPT",hard)
            print(f"[{self.id}] {'hard stop' if hard else 'pause'} {self.current['challenge_id']}",flush=True)
        else:
            self.stopping=True

    async def run(self,once=False):
        self.state.register(self.id,self.token,os.getpid(),self.limits["lease_seconds"])
        loop=asyncio.get_running_loop()
        if os.name=="posix":
            loop.add_signal_handler(signal.SIGINT,self.interrupt)
            loop.add_signal_handler(signal.SIGTERM,lambda:setattr(self,"stopping",True))
        try:
            while not self.stopping and not self.state.meta("shutdown",False):
                if now()-self.last_heartbeat>=self.limits["heartbeat_seconds"]:
                    self.state.heartbeat(self.id,self.token,None,self.limits["lease_seconds"])
                    self.last_heartbeat=now()
                task=self.state.claim(self.id,self.token,self.limits["lease_seconds"],self.state.meta("workers",8),self.state.meta("mode","breadth")=="depth")
                if not task:
                    if once: return
                    await asyncio.sleep(self.limits["poll_seconds"]); continue
                self.current=task
                print(f"[{self.id}] {task['challenge_id']} {task['stage']} {task['profile_id']}",flush=True)
                try:
                    await self.execute(task)
                except Exception as e:
                    if self.proc:
                        await terminate(self.proc,0)
                    self.state.ready_result(task,"",type(e).__name__+":"+str(e)[:160])
                finally:
                    self.current=None; self.proc=None
                if once: return
        finally:
            if self.proc: await terminate(self.proc,0)
            with self.state.tx() as c:
                c.execute("DELETE FROM workers WHERE id=? AND token=?",(self.id,self.token))

    async def execute(self,task):
        profile=self.profiles[task["profile_id"]]
        current_scope,scope_hash=scope.load(self.root,self.mock)
        if scope_hash!=self.state.meta("scope_hash"):
            raise ValueError("SCOPE_HASH_CHANGED")
        scope.validate(current_scope,task["challenge_id"])
        ch=self.state.one("SELECT * FROM challenges WHERE id=?",(task["challenge_id"],))
        workspace=artifacts.prepare(self.root,task)
        request={"task":task,"challenge":{k:ch[k] for k in ("id","title","category","description")},"scope":current_scope,"scope_hash":scope_hash,"previous":[],"candidate_flag_ref":None}
        request["storage_policy"]=policy(workspace)
        request["previous_artifact_index"]=[]
        for item in self.state.rows("SELECT path,kind,sha256 FROM artifacts WHERE task_id=?",(task["parent_task_id"],)):
            parts=Path(item["path"]).parts
            # canonical challenges/<id>/<kind>/... was copied to previous/<kind>/...
            request["previous_artifact_index"].append({**item,"workspace_path":(Path("previous")/Path(*parts[2:])).as_posix()})
        if task["parent_task_id"]:
            prior=self.root/"challenges"/task["challenge_id"]/"evidence"/task["parent_task_id"]/"handoff.json"
            parent=self.state.one("SELECT status FROM tasks WHERE task_id=?",(task["parent_task_id"],))
            if prior.exists() and parent and parent["status"]=="SUCCEEDED":
                h=read_json(prior)
                if profile.stage.startswith("verify"):
                    request["previous"]=[{k:h[k] for k in ("artifacts","reproduction_steps","verified_facts")}]
                else:
                    request["previous"]=[h]
        if profile.stage.startswith("verify") and ch["candidate_ref"]:
            source=contained(self.root,ch["candidate_ref"])
            target=workspace/"candidate.flag"
            target.write_bytes(source.read_bytes()); protect(target)
            request["candidate_flag_ref"]="candidate.flag"
        atomic_json(workspace/"request.json",request)
        daybreak_args=None
        if profile.daybreak and not self.mock:
            attestation=self.state.meta("daybreak_attestation")
            binary=self.root/self.limits["codex_binary"]
            if not attestation or attestation.get("scope_hash")!=scope_hash or attestation.get("binary_sha256")!=digest(binary) or now()-attestation.get("timestamp",0)>86400:
                self.state.ready_result(task,"","MANUAL_DAYBREAK_REQUIRED"); return
            daybreak_args=attestation["args"]
        for repair_attempt in range(2):
            if self.mock:
                cmd=[sys.executable,str(self.root/"tests/fixtures/mock_codex.py"),str(workspace)]
            else:
                binary=self.root/self.limits["codex_binary"]
                cmd=adapter.build_command(binary,profile,workspace,self.root/"schemas/handoff.schema.json",task["session_id"],daybreak_args,bool(current_scope.get("allow_remote")))
            self.proc=await asyncio.create_subprocess_exec(*cmd,cwd=workspace,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=os.name=="posix",limit=1024*1024)
            if not self.state.running(task,self.proc.pid,process_token(self.proc.pid)):
                await terminate(self.proc,0)
                self.state.release(task["task_id"],"CANCELLED","FENCED_BEFORE_SPAWN"); return
            text=adapter.prompt(self.root,profile,request,repair if repair_attempt else None)
            try:
                self.proc.stdin.write(text.encode()); await self.proc.stdin.drain()
            except (BrokenPipeError,ConnectionResetError):
                pass
            self.proc.stdin.close()
            chunks=[]; session=[None]
            async def consume(stream,logname,events=False):
                size=0
                pending=b""
                with (workspace/logname).open("w",encoding="utf-8") as log:
                    while data:=await stream.read(65536):
                        raw=data.decode(errors="replace")
                        if events:
                            pending+=data
                            raw=""
                            while b"\n" in pending:
                                line,pending=pending.split(b"\n",1)
                                try:
                                    obj=json.loads(line)
                                    if obj.get("type")=="thread.started": session[0]=obj.get("thread_id")
                                    if obj.get("type")=="turn.completed" and isinstance(obj.get("usage"),dict):
                                        usage={k:v for k,v in obj["usage"].items() if isinstance(v,(int,float))}
                                        with self.state.tx() as c:
                                            current=c.execute("SELECT generation FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()
                                            if current and current[0]==task["generation"]:
                                                self.state.event(c,"USAGE",task=task,profile=profile.id,usage=usage)
                                                totals=self.state.meta("usage_by_profile",{})
                                                prior=totals.setdefault(profile.id,{})
                                                for key,value in usage.items():prior[key]=prior.get(key,0)+value
                                                self.state.setmeta("usage_by_profile",totals,c)
                                    # No tool commands, prompts or model messages in shared logs.
                                    raw+=json.dumps({k:obj[k] for k in ("type","usage","thread_id") if k in obj})+"\n"
                                except (ValueError,AttributeError):
                                    raw+="[non-json event omitted]\n"
                            if len(pending)>65536:
                                pending=b""
                        else:
                            if sum(map(len,chunks))<32768: chunks.append(raw[:4096])
                            raw=adapter.redact(raw)
                        if size<self.limits["log_bytes"]:
                            piece=raw[:self.limits["log_bytes"]-size]; log.write(piece); size+=len(piece)
            readers=[asyncio.create_task(consume(self.proc.stdout,"events.jsonl",True)),asyncio.create_task(consume(self.proc.stderr,"stderr.log"))]
            began=time.monotonic(); last_progress_hash=None; error=""
            while self.proc.returncode is None:
                alive=self.state.live(task)
                if now()-self.last_heartbeat>=self.limits["heartbeat_seconds"]:
                    alive=self.state.heartbeat(self.id,self.token,task,self.limits["lease_seconds"])
                    self.last_heartbeat=now()
                if now()-self.state.meta("supervisor_heartbeat",0)>self.limits["lease_seconds"]:
                    self.state.control(task["challenge_id"],"FROZEN","SUPERVISOR_LOST")
                    alive=False
                if not alive or self.stopping or self.state.meta("shutdown",False):
                    await terminate(self.proc,0 if self.stopping else self.limits["cancel_grace_seconds"])
                    self.state.release(task["task_id"],"PAUSED","CANCEL_CONFIRMED")
                    await asyncio.gather(*readers,return_exceptions=True); return
                if time.monotonic()-began>profile.timeout:
                    error="TIMEOUT"; await terminate(self.proc,0); break
                progress=workspace/"progress.json"
                if progress.exists() and progress.stat().st_size<=32768:
                    try:
                        h=digest(progress)
                        if h!=last_progress_hash:
                            p=read_json(progress)
                            facts=p.get("evidence_delta",[])
                            # A changing sentence alone does not count as progress.
                            actual=[f for f in facts if f.get("evidence_path") and contained(workspace,f["evidence_path"]).is_file()]
                            if actual:
                                with self.state.tx() as c:
                                    new=0
                                    for fact in actual:
                                        key=digest(contained(workspace,fact["evidence_path"]))
                                        new+=c.execute("INSERT OR IGNORE INTO evidence_seen VALUES(?,?,?)",(task["challenge_id"],task["generation"],key)).rowcount
                                    if new:
                                        c.execute("UPDATE challenges SET evidence_at=?,primitive=MAX(primitive,?) WHERE id=? AND generation=?",(now(),int(bool(p.get("primitive"))),task["challenge_id"],task["generation"]))
                                        self.state.event(c,"EVIDENCE_DELTA",task=task,count=new)
                            last_progress_hash=h
                    except (OSError,ValueError,TypeError,KeyError):
                        pass
                await asyncio.sleep(min(.2,self.limits["heartbeat_seconds"]))
            await self.proc.wait()
            await asyncio.gather(*readers,return_exceptions=True)
            # Ensure daemonized children cannot outlive a stage.
            if os.name=="posix": await terminate(self.proc,0)
            if session[0] and profile.resumable:
                with self.state.tx() as c:
                    c.execute("UPDATE tasks SET session_id=? WHERE task_id=? AND lease_id=?",(session[0],task["task_id"],task["lease_id"]))
                task["session_id"]=session[0]
            if error or self.proc.returncode:
                kind,delay=("TIMEOUT",5) if error else adapter.error_kind("".join(chunks))
                self.state.ready_result(task,"",json.dumps({"kind":kind,"delay":delay})); return
            result=workspace/"result.json"
            try:
                value=contracts.handoff(result.read_bytes(),self.root,task)
                artifacts.check(self.root,task,value)
                from .scheduler import Scheduler
                Scheduler(self.root,self.profiles).next(task,value)
            except (OSError,ValueError,RecursionError) as e:
                repair=type(e).__name__+":"+str(e)[:160]
                if repair_attempt==0:
                    with self.state.tx() as c:
                        c.execute("UPDATE tasks SET status='LEASED',pid=NULL,process_token=NULL WHERE task_id=? AND status='RUNNING'",(task["task_id"],))
                    continue
                self.state.ready_result(task,"","INVALID_OUTPUT:"+repair); return
            self.state.ready_result(task,result); return
