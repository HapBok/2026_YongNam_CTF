import base64
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ctf_engine.common import atomic_json,now
from ctf_engine.prescan import import_problem
from ctf_engine.scope import load
from ctf_engine.state import State


def workspace():
    temp=tempfile.TemporaryDirectory(prefix="ctf-engine-test-")
    root=Path(temp.name)
    for name in ("config","prompts","schemas","src","tests"):
        shutil.copytree(ROOT/name,root/name,ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT/"ctfctl.py",root/"ctfctl.py")
    state=State(root)
    s,h=load(root,True)
    state.setmeta("scope_hash",h);state.setmeta("mock",True);state.setmeta("supervisor_heartbeat",now())
    return temp,root,state,h


def problem(root,state,h,id="c001",category="crypto",description=""):
    source=root/"test-inputs"/id
    source.mkdir(parents=True)
    (source/"payload.txt").write_bytes(base64.b64encode(("TEST{"+id+"}").encode()))
    import_problem(root,state,source,id,id,category,description,h)


def result(task):
    return {"schema_version":1,"challenge_id":task["challenge_id"],"task_id":task["task_id"],"generation":task["generation"],"stage_status":"partial","classification":{"category":"crypto","confidence":.95},"verified_facts":[],"hypotheses":[],"discarded_hypotheses":[],"evidence_delta":[],"artifacts":[],"reproduction_steps":[],"blockers":[],"next_action":"continue","recommended_next_profile":"quick-luna","candidate_flag_ref":None}
