#!/usr/bin/env python3
"""Eight process-based local fixture workflows, explicitly MOCK not live."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"src"))
from tests.support import problem,workspace
from ctf_engine.common import atomic_json
from ctf_engine.supervisor import Supervisor


def execute():
    temp,root,state,h=workspace()
    try:
        for i,category in enumerate(["web","pwn","rev","crypto","forensics","mobile","ai","misc"]):problem(root,state,h,f"c{i:03d}",category)
        began=time.monotonic()
        asyncio.run(asyncio.wait_for(Supervisor(root,True).run(8,until_idle=True),90))
        challenges=state.rows("SELECT id,category,state FROM challenges ORDER BY id")
        active=state.one("SELECT COUNT(*) n FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')")["n"]
        report={"kind":"MOCK_STAGE_REHEARSAL_NOT_LIVE_SOLVES","elapsed_seconds":time.monotonic()-began,"challenges":challenges,"peak_active":state.meta("peak_active"),"orphan_active":active,"db_integrity":state.one("PRAGMA integrity_check")["integrity_check"],"passed":all(c["state"]=="VERIFIED" for c in challenges) and active==0 and state.meta("peak_active")<=8}
        atomic_json(ROOT/"reports/rehearsal/mock.json",report)
        return report
    finally:temp.cleanup()


if __name__=="__main__":
    report=execute();print(json.dumps(report,indent=2));raise SystemExit(0 if report["passed"] else 1)
