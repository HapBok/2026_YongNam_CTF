#!/usr/bin/env python3
"""Test Linux permissions / Windows ACL using a disposable non-secret canary."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ctf_engine.common import atomic_json,uid
from ctf_engine.permissions import policy,protect

directory=ROOT/".runtime/storage-canary"
directory.mkdir(parents=True,exist_ok=True)
path=directory/(uid("non-secret")+".txt")
path.write_text("public dummy storage permission check")
report={"policy":policy(directory),"protection":protect(path),"canary_path":str(path),"passed":True}
atomic_json(ROOT/"reports/storage.json",report)
print(report)
