from pathlib import Path
import json
import shutil

from .common import atomic_json, contained, digest, read_json, settings
from .permissions import protect


def prepare(root,task):
    root=Path(root)
    dest=root/".runtime/attempts"/task["task_id"]
    dest.mkdir(parents=True,exist_ok=True)
    source=root/".local/inputs"/task["challenge_id"]
    inputs=dest/"input"
    inputs.mkdir(exist_ok=True)
    manifest=read_json(root/"challenges"/task["challenge_id"]/"input-manifest.json")
    for item in manifest:
        original=contained(source,item["path"])
        if digest(original)!=item["sha256"]:
            raise ValueError("ORIGINAL_HASH_MISMATCH")
        copy=contained(inputs,item["path"])
        copy.parent.mkdir(parents=True,exist_ok=True)
        if not copy.exists():
            shutil.copyfile(original,copy)
            copy.chmod(0o444)
        elif digest(copy)!=item["sha256"]:
            raise ValueError("INPUT_COPY_HASH_MISMATCH")
    for name in ("input-manifest.json","prescan.json"):
        shutil.copyfile(root/"challenges"/task["challenge_id"]/name,dest/name)
    # Only Supervisor-promoted content is copied forward.
    from .state import State
    state=State(root)
    rows=state.rows("SELECT a.path,a.sha256 FROM artifacts a JOIN tasks t ON t.task_id=a.task_id WHERE t.challenge_id=? AND t.status='SUCCEEDED'",(task["challenge_id"],))
    for item in rows:
        original=contained(root,item["path"])
        if digest(original)!=item["sha256"]:
            raise ValueError("PROMOTED_ARTIFACT_HASH_MISMATCH")
        parts=Path(item["path"]).parts
        target=contained(dest,(Path("previous")/Path(*parts[2:])).as_posix())
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original,target)
    return dest


def check(root,task,value):
    root=Path(root)
    workspace=root/".runtime/attempts"/task["task_id"]
    lim=settings(root); total=0; checked=[]
    manifest=read_json(root/"challenges"/task["challenge_id"]/"input-manifest.json")
    for item in manifest:
        original=contained(root/".local/inputs"/task["challenge_id"],item["path"])
        copy=contained(workspace/"input",item["path"])
        if digest(original)!=item["sha256"] or digest(copy)!=item["sha256"]:
            raise ValueError("INPUT_INTEGRITY_CHANGED")
    for item in value["artifacts"]:
        path=contained(workspace,item["path"])
        if not path.is_file() or path.stat().st_size>lim["artifact_bytes"]:
            raise ValueError("ARTIFACT_MISSING_OR_TOO_LARGE")
        total+=path.stat().st_size
        if total>lim["total_artifact_bytes"]:
            raise ValueError("ARTIFACT_TOTAL_BUDGET")
        if digest(path)!=item["sha256"]:
            raise ValueError("ARTIFACT_HASH_MISMATCH")
        if path.is_relative_to(workspace/"input") or path.name in {"candidate.flag","request.json","progress.json"} or path.suffix in {".flag",".db",".i64",".bndb",".core"}:
            raise ValueError("SENSITIVE_OR_RUNTIME_ARTIFACT")
        checked.append((item,path))
    for fact in value["verified_facts"]+value["evidence_delta"]:
        if fact["evidence_path"] and not contained(workspace,fact["evidence_path"]).is_file():
            raise ValueError("EVIDENCE_MISSING")
    ref=value["candidate_flag_ref"]
    if ref or (workspace/"candidate.flag").exists():
        if ref and ref!="candidate.flag":
            raise ValueError("INVALID_FLAG_REFERENCE")
        flag=contained(workspace,"candidate.flag")
        if not flag.is_file() or not 1<=flag.stat().st_size<=4096:
            raise ValueError("INVALID_FLAG_FILE")
        protect(flag)
        secret=flag.read_bytes().strip()
        if len(secret)>=6:
            if secret in json.dumps(value,ensure_ascii=False).encode():
                raise ValueError("FLAG_IN_HANDOFF")
            for _,path in checked:
                if secret in path.read_bytes():
                    raise ValueError("FLAG_IN_PUBLISHED_ARTIFACT")
    return checked


def promote(root,task,value,checked):
    root=Path(root)
    canonical=root/"challenges"/task["challenge_id"]
    result=[]
    for item,path in checked:
        dest=canonical/item["kind"]/task["task_id"]/item["path"]
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if digest(dest)!=item["sha256"]:
                raise ValueError("ARTIFACT_COLLISION")
        else:
            with dest.open("xb") as f, path.open("rb") as src:
                shutil.copyfileobj(src,f)
        result.append({**item,"canonical":dest.relative_to(root).as_posix()})
    atomic_json(canonical/"evidence"/task["task_id"]/"handoff.json",value)
    ref=None
    if value["candidate_flag_ref"]:
        dest=root/".local/secrets"/task["challenge_id"]/(task["task_id"]+".flag")
        dest.parent.mkdir(parents=True,exist_ok=True)
        source=root/".runtime/attempts"/task["task_id"]/"candidate.flag"
        if not dest.exists():
            with dest.open("xb") as f:
                f.write(source.read_bytes())
            protect(dest)
        ref=dest.relative_to(root).as_posix()
    return result,ref


def quarantine(root,task,reason):
    atomic_json(Path(root)/".runtime/quarantine"/(task["task_id"]+".json"),
                {"task_id":task["task_id"],"generation":task["generation"],"reason":reason})


def notes(root,task,value,state):
    canonical=Path(root)/"challenges"/task["challenge_id"]
    lines=["# "+task["challenge_id"],"",f"State: {state}",f"Category: {value['classification']['category']}",f"Last task: {task['task_id']}","","## Verified findings",""]
    lines.extend("- "+f["claim"] for f in value["verified_facts"])
    lines += ["","## Reproduction",""]
    lines.extend(f"{i}. {step}" for i,step in enumerate(value["reproduction_steps"],1))
    lines += ["","## Next action","",value["next_action"],"","Flag is kept separately in .local/secrets and must be submitted manually.",""]
    (canonical/"notes.md").write_text("\n".join(lines),encoding="utf-8")
    if state=="VERIFIED":
        (canonical/"writeup.md").write_text("# Write-up draft\n\n"+"\n".join(lines[2:]),encoding="utf-8")
