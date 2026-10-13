#!/usr/bin/env python3
"""Queue/lease stress test; no model requests and no claim of LLM throughput."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"src"))
from tests.support import workspace
from ctf_engine.common import atomic_json,now
from ctf_engine.profiles import load


def execute(count=1000):
    temp,root,state,h=workspace()
    try:
        profile=load(root)["intake-luna"]
        with state.tx() as c:
            for i in range(count):
                cid=f"c{i:05d}"
                c.execute("INSERT INTO challenges(id,title,created,scope_hash,state) VALUES(?,?,?,?,?)",(cid,cid,now(),h,"PRESCANNED"))
                state.enqueue(cid,profile,c=c)
        durations=[];completed=[]
        began=time.monotonic()
        def consume(i):
            wid=f"w{i:02d}";token=f"token{i}"
            state.register(wid,token,100+i,15)
            while True:
                state.setmeta("supervisor_heartbeat",now())
                t=time.monotonic();task=state.claim(wid,token,15)
                durations.append(time.monotonic()-t)
                if not task:
                    pending=state.one("SELECT COUNT(*) n FROM tasks WHERE status IN ('READY','LEASED','RUNNING','COMMITTING')")["n"]
                    if not pending:break
                    time.sleep(.001);continue
                time.sleep(.005)
                state.release(task["task_id"],"SUCCEEDED")
                completed.append(task["task_id"])
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(consume,range(1,9)))
        integrity=state.one("PRAGMA integrity_check")["integrity_check"]
        p95=sorted(durations)[int(len(durations)*.95)]
        report={"kind":"mock_queue_lease_stress","tasks":count,"completed":len(completed),"unique_completed":len(set(completed)),"peak_active":state.meta("peak_active"),"claim_p95_seconds":p95,"elapsed_seconds":time.monotonic()-began,"db_integrity":integrity,"passed":len(completed)==count and len(set(completed))==count and state.meta("peak_active")<=8 and integrity=="ok" and p95<=.5}
        return report
    finally:temp.cleanup()


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tasks",type=int,default=1000);a=p.parse_args()
    report=execute(a.tasks);atomic_json(ROOT/"reports/stress.json",report)
    print(json.dumps(report,indent=2));raise SystemExit(0 if report["passed"] else 1)
