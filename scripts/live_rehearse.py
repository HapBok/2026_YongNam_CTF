#!/usr/bin/env python3
"""Small real-model, offline-owned puzzle test through Worker and Supervisor.

Creates its own immutable authorization scope, never uses contest targets and
never marks contest readiness. Uses the existing account and consumes quota.
"""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ctf_engine.common import atomic_json,digest,now,uid
from ctf_engine.prescan import import_problem
from ctf_engine.profiles import load
from ctf_engine.scope import load as load_scope
from ctf_engine.state import State
from ctf_engine.supervisor import Supervisor
from ctf_engine.worker import Worker
from ctf_engine.fingerprint import calculate


async def execute(category="crypto"):
    build_fingerprint=calculate(ROOT)
    root=ROOT/".runtime/live-rehearsals"/uid("owned-puzzle")
    root.mkdir(parents=True)
    for folder in ("src","config","prompts","schemas","tests","scripts"):
        shutil.copytree(ROOT/folder,root/folder,ignore=shutil.ignore_patterns("__pycache__","scope.toml","contest.toml"))
    shutil.copy2(ROOT/"ctfctl.py",root/"ctfctl.py")
    limits=root/"config/limits.toml"
    text=limits.read_text().replace('codex_binary = ".local/toolchains/codex/bin/codex"','codex_binary = '+json.dumps(str(ROOT/".local/toolchains/codex/bin/codex")))
    limits.write_text(text)
    (root/"config/scope.toml").write_text('version = 1\nauthorized = true\nrules_reference = "Self-authored local base64 puzzle; owner-authorized development test"\nchallenge_ids = ["c001"]\nallow_remote = false\nallowed_endpoints = []\n')
    scope,h=load_scope(root)
    state=State(root);state.setmeta("scope_hash",h);state.setmeta("mock",False);state.setmeta("workers",1)
    state.setmeta("shutdown",False);state.setmeta("supervisor_heartbeat",now())
    binary=ROOT/".local/toolchains/codex/bin/codex"
    preflight=json.loads((ROOT/"reports/preflight.json").read_text())
    if not preflight.get("models_ready",preflight.get("ready")):
        raise ValueError("Live canary must pass before real-model rehearsal")
    state.setmeta("daybreak_attestation",{"scope_hash":h,"binary_sha256":digest(binary),"args":["--cyber-access-program","daybreak_blue"],"timestamp":now()})
    source=root/"fixture";source.mkdir()
    expected=b"LOCALTEST{owned_offline_pipeline_check}"
    (source/"payload.txt").write_bytes(base64.b64encode(expected))
    description="This is a self-authored offline pipeline test. Decode payload.txt as standard base64. Save the decoded bytes ONLY in candidate.flag; reproduce with a small Python solver, hash-based evidence and handoff. There is no remote target."
    import_problem(root,state,source,"c001","Owned offline integration puzzle",category,description,h)
    if category=="web":
        # Explicit security-adapter fixture: exercise Daybreak solve/verify,
        # not a claim that a base64 puzzle is a real web vulnerability.
        state.enqueue("c001",load(root)["security-daybreak"],70)
    supervisor=Supervisor(root,False)
    worker=Worker(root,"w01",False)
    state.register("w01",worker.token,1,15)
    async def heartbeat():
        while True:
            state.setmeta("supervisor_heartbeat",now());await asyncio.sleep(.2)
    pulse=asyncio.create_task(heartbeat())
    try:
        for _ in range(8):
            supervisor.tick()
            ch=state.one("SELECT * FROM challenges WHERE id='c001'")
            if ch["state"] in {"VERIFIED","FROZEN","FAILED_CLOSED","MANUAL_DAYBREAK_REQUIRED","QUOTA_WAIT"}:break
            task=state.claim("w01",worker.token,15,cap=1)
            if not task:break
            await asyncio.wait_for(worker.execute(task),180)
            supervisor.tick()
        ch=state.one("SELECT * FROM challenges WHERE id='c001'")
        matched=bool(ch["candidate_ref"] and (root/ch["candidate_ref"]).read_bytes().strip()==expected)
        report={"timestamp":now(),"build_fingerprint":build_fingerprint,"kind":"REAL_MODEL_OWNED_OFFLINE_REHEARSAL","category":category,"workspace":str(root),"state":ch["state"],"expected_hash_match":matched,"tasks":state.rows("SELECT stage,profile_id,status,error FROM tasks ORDER BY created"),"passed":ch["state"]=="VERIFIED" and matched}
        atomic_json(ROOT/"reports/rehearsal"/("live-"+category+".json"),report)
        return report
    finally:
        pulse.cancel()
        await asyncio.gather(pulse,return_exceptions=True)
        if worker.proc and worker.proc.returncode is None:
            from ctf_engine.process_control import terminate
            await terminate(worker.proc,0)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--category",choices=["crypto","web"],default="crypto");a=p.parse_args()
    report=asyncio.run(execute(a.category));print(json.dumps(report,indent=2));raise SystemExit(0 if report["passed"] else 1)
