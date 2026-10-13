from __future__ import annotations

import json
import re
from pathlib import Path


def build_command(binary,profile,workspace,schema,session=None,daybreak_args=None,network=False):
    # argv only: challenge text is passed on stdin, never interpolated into a shell.
    cmd=[str(binary),"-C",str(workspace),"-a","never","exec"]
    if session and profile.resumable:
        cmd += ["resume",session]
    cmd += ["--ignore-user-config","--skip-git-repo-check","--json",
            "-m",profile.model,"-c",f'model_reasoning_effort="{profile.effort}"',
            "-c",'service_tier="default"',"-c",'sandbox_mode="workspace-write"',
            "-c",f"sandbox_workspace_write.network_access={'true' if network else 'false'}",
            "-c","features.multi_agent=false",
            "--output-schema",str(schema),"-o",str(Path(workspace)/"result.json")]
    if profile.daybreak:
        if not daybreak_args:
            raise ValueError("MANUAL_DAYBREAK_REQUIRED")
        cmd += daybreak_args
    else:
        cmd += ["--cyber-access-program","standard"]
    cmd += ["-"]
    return cmd


def error_kind(text):
    lower=text.lower()
    if any(x in lower for x in ("429","rate limit","usage limit","quota exceeded")):
        m=re.search(r"retry[-_ ]after[:= ]+(\d+)",lower)
        return "QUOTA",int(m.group(1)) if m else 61
    if any(x in lower for x in ("404","model not found","model is not supported","unsupported model","not available for your account")):
        return "MODEL_NOT_FOUND",0
    if any(x in lower for x in ("401","not logged in","authentication","unauthorized")):
        return "AUTH_REQUIRED",0
    if any(x in lower for x in ("500","502","503","504","stream disconnected","connection","timed out")):
        return "TRANSIENT",5
    return "PROVIDER_ERROR",0


def redact(text):
    text=re.sub(r"(?i)(?:[a-z0-9_-]{1,32})\{[^\r\n}]{1,4096}\}","[FLAG_REDACTED]",text)
    text=re.sub(r"(?i)(bearer\s+|sk-)[A-Za-z0-9._-]+",r"\1[REDACTED]",text)
    return text


def prompt(root,profile,request,repair=None):
    root=Path(root)
    base=(root/"prompts/common/base.md").read_text(encoding="utf-8")
    role=(root/profile.prompt).read_text(encoding="utf-8")
    category=request["challenge"]["category"]
    playbook=root/"prompts/solve"/({"ai":"ai-misc","misc":"ai-misc"}.get(category,category))/"playbook.md"
    if playbook.is_file() and profile.stage not in {"intake","triage"}:
        role += "\n"+playbook.read_text(encoding="utf-8")
    text=base+"\n\n"+role+"\n\nRead request.json now. Stage identity:\n"+json.dumps({k:request["task"][k] for k in ("task_id","challenge_id","generation")})
    if repair:
        text+="\nThe prior final output failed validation: "+repair+". Repair the final JSON once. Do not repeat analysis or put raw flags in JSON."
    return text
