from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys

from .common import atomic_json,digest,now,settings,uid
from .profiles import load
from .state import State
from .fingerprint import calculate
from . import scope


def command(args,timeout=20):
    try:
        r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        return {"ok":r.returncode==0,"returncode":r.returncode,"stdout":r.stdout[:50000],"stderr":r.stderr[:2048]}
    except (OSError,subprocess.TimeoutExpired) as e:
        return {"ok":False,"error":str(e)}


async def canary(root,profile,binary,sem):
    async with sem:
        directory=root/".runtime/canaries"/uid(profile.id)
        directory.mkdir(parents=True)
        schema={"type":"object","properties":{"value":{"type":"integer"}},"required":["value"],"additionalProperties":False}
        atomic_json(directory/"schema.json",schema)
        args=[str(binary),"-a","never","exec","--ignore-user-config","--skip-git-repo-check","--ephemeral","--json","-C",str(directory),"-s","read-only","-m",profile.model,"-c",f'model_reasoning_effort="{profile.effort}"',"-c",'service_tier="default"',"--cyber-access-program","daybreak_blue" if profile.daybreak else "standard","--output-schema",str(directory/"schema.json"),"-o",str(directory/"result.json"),"Return JSON value 2. Do not use tools."]
        proc=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True)
        try:
            out,err=await asyncio.wait_for(proc.communicate(),120)
            result=json.loads((directory/"result.json").read_text()) if (directory/"result.json").exists() else None
            # Store no authentication values or model response text.
            return {"profile":profile.id,"model":profile.model,"effort":profile.effort,"daybreak_requested":profile.daybreak,"ok":proc.returncode==0 and result=={"value":2},"returncode":proc.returncode,"quota_error":b"429" in err or b"usage limit" in err.lower(),"error_summary":err.decode(errors="replace")[-1024:] if proc.returncode else ""}
        except asyncio.TimeoutError:
            from .process_control import terminate
            await terminate(proc,0)
            return {"profile":profile.id,"ok":False,"error":"CANARY_TIMEOUT"}


def run(root,live=False):
    root=Path(root).resolve(); lim=settings(root); profiles=load(root)
    binary=root/lim["codex_binary"]
    report={"report_version":2,"timestamp":now(),"python":platform.python_version(),"linux":sys.platform.startswith("linux"),"binary_exists":binary.is_file(),"checks":{},"live_requested":live,"models_ready":False,"ready":False}
    report["checks"]["version"]=command([str(binary),"--version"])
    report["checks"]["login"]=command([str(binary),"login","status"])
    report["checks"]["exec_help"]=command([str(binary),"exec","--help"])
    report["checks"]["resume_help"]=command([str(binary),"exec","resume","--help"])
    report["checks"]["models"]=command([str(binary),"debug","models"])
    report["tools"]={name:shutil.which(name) for name in ["file","strings","exiftool","gcc","gdb","readelf","objdump","checksec","python3"]}
    state=State(root)
    report["db_integrity"]=state.one("PRAGMA integrity_check")["integrity_check"]
    helptext=report["checks"]["exec_help"].get("stdout","")
    report["features"]={flag:flag in helptext for flag in ["--output-schema","--cyber-access-program","--ignore-user-config","--json"]}
    report["canaries"]=[]
    if live and report["linux"] and report["checks"]["login"]["ok"] and all(report["features"].values()):
        async def all_canaries():
            sem=asyncio.Semaphore(8)
            chosen=[profiles[x] for x in ["intake-luna","quick-luna","triage-sol","general-sol","security-daybreak","rescue-astra","verify-general","verify-security"]]
            first=await asyncio.gather(*(canary(root,p,binary,sem) for p in chosen))
            fallback=[p for p in profiles.values() if p.id not in {x.id for x in chosen}]
            rest=await asyncio.gather(*(canary(root,p,binary,sem) for p in fallback))
            return first+rest
        report["canaries"]=asyncio.run(all_canaries())
        report["models_ready"]=len(report["canaries"])==len(profiles) and all(x["ok"] for x in report["canaries"]) and report["db_integrity"]=="ok"
        try:
            current_scope,current_hash=scope.load(root)
            if current_scope.get("authorized") is not True or current_hash!=state.meta("scope_hash"):
                raise ValueError("Initialize the authorized contest scope first")
            for cid in current_scope.get("challenge_ids",[]):
                if cid!="*":scope.validate(current_scope,cid)
            report["scope_ready"]=True
        except ValueError as e:
            report["scope_ready"]=False;report["scope_error"]=str(e)
        report["ready"]=report["models_ready"] and report["scope_ready"]
        if report["ready"]:
            scope_hash=state.meta("scope_hash")
            state.setmeta("daybreak_attestation",{"scope_hash":scope_hash,"binary_sha256":digest(binary),"args":["--cyber-access-program","daybreak_blue"],"timestamp":now()})
    report["profile_fingerprint"]={p.id:{"model":p.model,"effort":p.effort,"daybreak":p.daybreak} for p in profiles.values()}
    report["build_fingerprint"]=calculate(root)
    report["binary_sha256"]=digest(binary) if binary.is_file() else None
    atomic_json(root/"reports/preflight.json",report)
    return report
