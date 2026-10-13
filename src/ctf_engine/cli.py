from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import tomllib

from . import doctor,scope
from .common import INACTIVE,ROOT,TERMINAL,atomic_json,now,read_json,safe_id,uid
from .prescan import import_problem
from .profiles import load
from .state import State


def parser():
    p=argparse.ArgumentParser(prog="ctfctl",description="Eight-worker dynamic Codex pipeline")
    p.add_argument("--root",type=Path,default=ROOT)
    sub=p.add_subparsers(dest="command",required=True)
    d=sub.add_parser("doctor"); d.add_argument("--live",action="store_true")
    r=sub.add_parser("init-run"); r.add_argument("--mock",action="store_true")
    i=sub.add_parser("import"); i.add_argument("path",type=Path); i.add_argument("--id",required=True); i.add_argument("--title",required=True); i.add_argument("--category",default="unknown"); i.add_argument("--description",default="")
    b=sub.add_parser("import-batch"); b.add_argument("directory",type=Path); b.add_argument("--skip-existing",action="store_true")
    m=sub.add_parser("make-toml",help="Generate challenge.toml from statement screenshots; never edits scope.toml")
    m.add_argument("directory",type=Path); m.add_argument("--batch",action="store_true"); m.add_argument("--id")
    s=sub.add_parser("start"); s.add_argument("--workers",type=int,default=8); s.add_argument("--mock",action="store_true"); s.add_argument("--external-workers",action="store_true"); s.add_argument("--until-idle",action="store_true")
    w=sub.add_parser("worker"); w.add_argument("--id",required=True,choices=[f"w{i:02d}" for i in range(1,9)]); w.add_argument("--mock",action="store_true"); w.add_argument("--once",action="store_true")
    st=sub.add_parser("status"); st.add_argument("--watch",action="store_true"); st.add_argument("--json",action="store_true")
    for cmd in ("pause","resume","freeze","export","drop"):
        c=sub.add_parser(cmd); c.add_argument("challenge_id")
    stop=sub.add_parser("stop"); stop.add_argument("challenge_id"); stop.add_argument("--hard",action="store_true",required=True)
    solved=sub.add_parser("solved"); solved.add_argument("challenge_id"); solved.add_argument("--by",choices=["self","team"],required=True)
    q=sub.add_parser("requeue"); q.add_argument("challenge_id"); q.add_argument("--profile",required=True); q.add_argument("--hypothesis",default="main")
    e=sub.add_parser("extend"); e.add_argument("challenge_id"); e.add_argument("--reason",required=True)
    sh=sub.add_parser("shutdown"); sh.add_argument("--graceful",action="store_true",required=True)
    quota=sub.add_parser("quota"); quota.add_argument("--remaining",type=float,required=True)
    snap=sub.add_parser("snapshot")
    sub.add_parser("recover")
    return p


def status(state):
    metadata=state.meta('metadata_slot')
    return {"mode":state.meta("mode","breadth"),"peak_active":state.meta("peak_active",0),"supervisor_live":now()-state.meta("supervisor_heartbeat",0)<15,"dispatch_blocked":state.meta("dispatch_blocked"),"quota_remaining":state.meta("quota_remaining"),"usage_by_profile":state.meta("usage_by_profile",{}),"metadata":{k:metadata.get(k) for k in ('phase','profile','heartbeat')} if metadata else None,"challenges":state.rows("SELECT id,title,category,state,generation,last_error,solve_seconds FROM challenges ORDER BY id"),"active":state.rows("SELECT worker_id,challenge_id,stage,profile_id,status,lease_until FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING') ORDER BY worker_id")}


def main(argv=None):
    args=parser().parse_args(argv); root=args.root.resolve()
    try:
        state=State(root); profiles=load(root)
        if args.command=="make-toml":
            from .metadata import generate
            report=asyncio.run(generate(root,state,args.directory,args.batch,args.id))
            print(json.dumps({"passed":report["passed"],"scope_modified":False},ensure_ascii=False))
            return 0 if report["passed"] else 2
        if args.command=="doctor":
            report=doctor.run(root,args.live)
            print(json.dumps({"models_ready":report["models_ready"],"ready":report["ready"],"scope_error":report.get("scope_error"),"linux":report["linux"],"login":report["checks"]["login"],"canaries":report["canaries"],"report":str(root/"reports/preflight.json")},ensure_ascii=False,indent=2))
            return 0 if report["ready"] else 2
        if args.command=="init-run":
            if state.meta("run_id"):
                raise ValueError("Run already initialized; reuse it or use a separate workspace")
            s,h=scope.load(root,args.mock)
            if s.get("authorized") is not True:
                raise ValueError("SCOPE_NOT_AUTHORIZED")
            state.setmeta("scope_hash",h); state.setmeta("mock",args.mock); state.setmeta("run_id",uid("run"))
            for path in (".local/inputs",".local/secrets",".local/submissions",".runtime/attempts",".runtime/quarantine",".runtime/logs",".runtime/runs","reports/rehearsal","reports/run-snapshots","reports/postmortem"):
                (root/path).mkdir(parents=True,exist_ok=True)
            atomic_json(root/".runtime/runs"/(state.meta("run_id")+".json"),{"run_id":state.meta("run_id"),"scope_hash":h,"mock":args.mock,"scope":s,"timestamp":now()})
            print(state.meta("run_id"));return 0
        if args.command in {"import","import-batch"}:
            s,h=scope.load(root,state.meta("mock",False))
            if args.command=="import":
                scope.validate(s,args.id)
                print(json.dumps(import_problem(root,state,args.path,args.id,args.title,args.category,args.description,h),ensure_ascii=False));return 0
            for directory in sorted(args.directory.iterdir()):
                if not directory.is_dir():continue
                meta=directory/"challenge.toml"
                if not meta.exists():raise ValueError("Each batch folder needs challenge.toml")
                info=tomllib.loads(meta.read_text(encoding="utf-8"))
                scope.validate(s,info["id"])
                if args.skip_existing and state.one("SELECT id FROM challenges WHERE id=?",(info["id"],)):
                    print(json.dumps({"id":info["id"],"status":"ALREADY_IMPORTED"},ensure_ascii=False));continue
                import_problem(root,state,directory/"files",info["id"],info["title"],info.get("category","unknown"),info.get("description",""),h)
            return 0
        if args.command=="start":
            if args.mock!=state.meta("mock",False): raise ValueError("Mock/live run mismatch")
            from .supervisor import Supervisor
            asyncio.run(Supervisor(root,args.mock).run(args.workers,args.external_workers,args.until_idle));return 0
        if args.command=="worker":
            if args.mock!=state.meta("mock",False):raise ValueError("Mock/live worker mismatch")
            from .worker import Worker
            asyncio.run(Worker(root,args.id,args.mock).run(args.once));return 0
        if args.command=="status":
            while True:
                data=status(state)
                if args.json:print(json.dumps(data,ensure_ascii=False))
                else:
                    metadata_active=int(bool(data['metadata'] and data['metadata']['phase']=='running'))
                    print(f"mode={data['mode']} active={len(data['active'])+metadata_active}/8 peak={data['peak_active']} supervisor={data['supervisor_live']}")
                    if data['metadata']:print(f"  metadata {data['metadata']['phase']} {data['metadata']['profile']}")
                    for row in data["challenges"]:print(f"{row['id']:<12} {row['category']:<10} {row['state']:<26} {row['last_error']}")
                    for row in data["active"]:print(f"  {row['worker_id']} {row['challenge_id']} {row['stage']} {row['profile_id']}")
                if not args.watch:return 0
                time.sleep(2)
        if args.command=="shutdown":state.setmeta("shutdown",True);return 0
        if args.command=="quota":
            if not 0<=args.remaining<=100:raise ValueError("Remaining quota must be 0..100")
            state.setmeta("quota_remaining",args.remaining);return 0
        if args.command=="snapshot":
            dest=root/"reports/run-snapshots"/(uid("snapshot")+".db");state.backup(dest);print(dest);return 0
        if args.command=="recover":
            from .process_control import group_alive,recover_metadata
            from .supervisor import Supervisor
            Supervisor(root,state.meta("mock",False)).cancel_and_recover()
            for task in state.rows("SELECT pid FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')"):
                if task["pid"] and group_alive(task["pid"]):raise ValueError("Live process group still exists; recovery not confirmed")
            if state.one("SELECT task_id FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')"):
                raise ValueError("Active lease remains; wait for it to expire or cancel it")
            recover_metadata(state)
            state.setmeta("dispatch_blocked",None);print("RECOVERY_CONFIRMED");return 0
        ch=state.one("SELECT * FROM challenges WHERE id=?",(safe_id(args.challenge_id),))
        if not ch:raise ValueError("Unknown challenge")
        if args.command in {"pause","freeze","drop","stop","solved"}:
            target={"pause":"PAUSED_MANUAL","freeze":"FROZEN","drop":"DROPPED","stop":"DIRTY_PAUSED"}.get(args.command)
            if args.command=="solved":
                if args.by=="self" and ch["state"]!="VERIFIED":raise ValueError("Self solve requires independent VERIFIED state")
                target="ACCEPTED_SELF" if args.by=="self" else "ACCEPTED_TEAM"
            state.control(ch["id"],target,"MANUAL_"+args.command.upper(),args.command=="stop")
            print(target);return 0
        if args.command in {"resume","requeue"}:
            if ch["state"] in TERMINAL or ch["state"]=="DIRTY_PAUSED":raise ValueError("Terminal/dirty run requires explicit review in a new attempt workspace")
            active=state.one("SELECT task_id FROM tasks WHERE challenge_id=? AND status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')",(ch["id"],))
            if active and (args.command=="resume" or state.meta("mode")!="depth"):
                raise ValueError("Wait for process cancellation before resume; alternate branches require depth mode")
            s,h=scope.load(root,state.meta("mock",False));scope.validate(s,ch["id"])
            if h!=state.meta("scope_hash"):raise ValueError("Scope changed")
            previous=state.one("SELECT * FROM tasks WHERE challenge_id=? ORDER BY created DESC LIMIT 1",(ch["id"],))
            profile_id=args.profile if args.command=="requeue" else previous["profile_id"] if previous else "intake-luna"
            if profile_id not in profiles:raise ValueError("Unknown profile")
            hypothesis=getattr(args,"hypothesis","main")
            if active and hypothesis=="main":raise ValueError("Alternate branch needs a distinct hypothesis")
            with state.tx() as c:
                c.execute("UPDATE challenges SET state='SOLVING',last_error='',evidence_at=? WHERE id=?",(now(),ch["id"]))
                state.enqueue(ch["id"],profiles[profile_id],70,previous["task_id"] if previous else None,hashlib.sha256(hypothesis.encode()).hexdigest() if hypothesis!="main" else "main",previous["session_id"] if previous and profiles[profile_id].resumable and previous["profile_id"]==profile_id else None,c)
            return 0
        if args.command=="extend":
            if ch["extension"] or not (ch["candidate_ref"] or ch["primitive"]):raise ValueError("One extension only, requires candidate or primitive evidence")
            with state.tx() as c:
                c.execute("UPDATE challenges SET extension=1 WHERE id=?",(ch["id"],));state.event(c,"EXTENSION_APPROVED",ch["id"],reason=args.reason)
            return 0
        if args.command=="export":
            dest=root/"reports/postmortem"/(ch["id"]+"-"+uid("export"));dest.mkdir(parents=True)
            shutil.copytree(root/"challenges"/ch["id"],dest/"challenge")
            events=state.rows("SELECT * FROM events WHERE challenge_id=? ORDER BY event_seq",(ch["id"],))
            for event in events:event["details"]=json.loads(event["details"])
            atomic_json(dest/"events.json",events)
            print(dest);return 0
    except (ValueError,OSError,KeyError,sqlite_error()) as e:
        print("ERROR:",str(e),file=sys.stderr);return 2
    except KeyboardInterrupt:
        return 130


def sqlite_error():
    import sqlite3
    return sqlite3.Error
