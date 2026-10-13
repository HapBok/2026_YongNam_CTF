#!/usr/bin/env python3
"""Deterministic TEST ONLY adapter; never presented as a live model solve."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import time

workspace=Path(sys.argv[1])
request=json.loads((workspace/"request.json").read_text())
task=request["task"]
time.sleep(float(request["challenge"]["description"].removeprefix("mock-delay:") or .02) if request["challenge"]["description"].startswith("mock-delay:") else .02)
stage=task["stage"]
category=request["challenge"]["category"]
if category=="unknown":category="crypto"
value={"schema_version":1,"challenge_id":task["challenge_id"],"task_id":task["task_id"],"generation":task["generation"],"stage_status":"partial","classification":{"category":category,"confidence":.95},"verified_facts":[],"hypotheses":["Read deterministic local fixture"],"discarded_hypotheses":[],"evidence_delta":[],"artifacts":[],"reproduction_steps":[],"blockers":[],"next_action":"decode fixture","recommended_next_profile":None,"candidate_flag_ref":None}
if stage=="intake":value["recommended_next_profile"]="quick-luna"
elif stage in {"quick-solve","solve-general","solve-security"} or stage.startswith("verify"):
    source=workspace/"input/payload.txt"
    flag=base64.b64decode(source.read_bytes(),validate=True)
    if stage.startswith("verify"):
        assert (workspace/"candidate.flag").read_bytes()==flag
        value["stage_status"]="verified"
    else:value["stage_status"]="candidate"
    (workspace/"candidate.flag").write_bytes(flag)
    (workspace/"candidate.flag").chmod(0o600)
    evidence=workspace/"proof.json"
    evidence.write_text(json.dumps({"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"decoded_sha256":hashlib.sha256(flag).hexdigest(),"matched":True}))
    solver=workspace/"solve.py"
    solver.write_text("import base64\nfrom pathlib import Path\nPath('candidate.flag').write_bytes(base64.b64decode(Path('input/payload.txt').read_bytes(),validate=True))\n")
    value["candidate_flag_ref"]="candidate.flag"
    value["reproduction_steps"]=["python3 solve.py"]
    value["evidence_delta"]=[{"claim":"Independent base64 decode matches candidate hash","evidence_path":"proof.json","repro_command":"python3 solve.py","confidence":1}]
    value["artifacts"]=[{"path":p.name,"kind":"solution" if p==solver else "evidence","sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in [solver,evidence]]
(workspace/"result.json").write_text(json.dumps(value))
print(json.dumps({"type":"thread.started","thread_id":"mock-session-"+task["task_id"]}))
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":0,"output_tokens":0}}))
