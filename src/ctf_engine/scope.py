from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tomllib


def load(root,mock=False):
    path=Path(root)/"config/scope.toml"
    if mock:
        value={"version":1,"authorized":True,"allow_remote":False,"challenge_ids":["*"],"rules_reference":"offline mock fixtures"}
    elif path.exists():
        value=tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("SCOPE_MISSING: copy scope.example.toml and configure authorized CTF scope")
    raw=json.dumps(value,sort_keys=True,separators=(",",":"))
    return value,hashlib.sha256(raw.encode()).hexdigest()


def validate(scope,challenge_id):
    if scope.get("version")!=1 or scope.get("authorized") is not True or not scope.get("rules_reference") or scope["rules_reference"].startswith("FILL:"):
        raise ValueError("SCOPE_NOT_AUTHORIZED")
    if not isinstance(scope.get("challenge_ids"),list) or not all(isinstance(x,str) for x in scope["challenge_ids"]):
        raise ValueError("SCOPE_CHALLENGE_IDS_INVALID")
    if scope.get("allow_remote",False) not in (True,False) or not isinstance(scope.get("allow_remote",False),bool):
        raise ValueError("SCOPE_REMOTE_FLAG_INVALID")
    if challenge_id not in scope.get("challenge_ids",[]) and "*" not in scope.get("challenge_ids",[]):
        raise ValueError("CHALLENGE_OUT_OF_SCOPE")
    current=datetime.now(timezone.utc)
    for key,cmp in (("starts_at",lambda d:current<d),("ends_at",lambda d:current>d)):
        if scope.get(key):
            d=datetime.fromisoformat(scope[key])
            if d.tzinfo is None or cmp(d):
                raise ValueError("SCOPE_TIME_INVALID")
    if scope.get("allow_remote") and not scope.get("allowed_endpoints"):
        raise ValueError("REMOTE_SCOPE_EMPTY")
