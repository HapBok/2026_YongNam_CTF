from __future__ import annotations

import os
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import time
import zipfile

from .common import atomic_json, digest, safe_id, settings


def archive_listing(path,max_entries=2000,max_bytes=1024*1024*1024):
    entries=[]
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                mode=i.external_attr>>16
                entries.append((i.filename,i.file_size,i.compress_size,stat.S_ISLNK(mode)))
    elif path.suffix.lower() in {".tar",".tgz",".gz",".bz2",".xz"}:
        try:
            with tarfile.open(path) as t:
                for i in t:
                    entries.append((i.name,i.size,max(1,path.stat().st_size),not(i.isfile() or i.isdir())))
                    if len(entries)>max_entries:
                        raise ValueError("ARCHIVE_ENTRY_LIMIT")
        except tarfile.ReadError:
            return None
    else:
        return None
    total=0
    result=[]
    if len(entries)>max_entries:
        raise ValueError("ARCHIVE_ENTRY_LIMIT")
    for name,size,compressed,link in entries:
        p=PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name or link:
            raise ValueError("ARCHIVE_UNSAFE_PATH_OR_LINK")
        total+=size
        if total>max_bytes or size/max(compressed,1)>1000:
            raise ValueError("ARCHIVE_BOMB_LIMIT")
        result.append({"name":name,"size":size})
    return result


def scan_file(path,deadline):
    record={"sha256":digest(path),"size":path.stat().st_size}
    with path.open("rb") as f:
        head=f.read(65536)
    record["magic_hex"]=head[:32].hex()
    record["strings"]=[]
    # Never put raw strings (possibly flags/credentials) in shared reports.
    record["printable_runs"]=len(re.findall(rb"[ -~]{6,}",head))
    if shutil.which("file") and time.monotonic()<deadline:
        try:
            r=subprocess.run(["file","-b","--",str(path)],capture_output=True,timeout=min(5,max(.1,deadline-time.monotonic())))
            record["file_type"]=r.stdout[:4096].decode(errors="replace").strip()
        except subprocess.TimeoutExpired:
            record["file_type"]="timeout"
    try:
        record["archive"]=archive_listing(path)
    except (ValueError,zipfile.BadZipFile,OSError) as e:
        record["archive_error"]=str(e)
    if shutil.which("exiftool") and time.monotonic()<deadline:
        try:
            r=subprocess.run(["exiftool","-json","-G1","-s",str(path)],capture_output=True,timeout=min(5,max(.1,deadline-time.monotonic())))
            if len(r.stdout)<=32768 and r.returncode==0:
                from .adapter import redact
                record["metadata"]=json.loads(redact(r.stdout.decode(errors="replace")))
        except (subprocess.TimeoutExpired,ValueError):
            record["metadata_status"]="timeout_or_invalid"
    return record


def import_problem(root,state,source,challenge_id,title,category="unknown",description="",scope_hash=""):
    root,source=Path(root).resolve(),Path(source).absolute()
    safe_id(challenge_id)
    if state.one("SELECT id FROM challenges WHERE id=?",(challenge_id,)):
        raise ValueError("Challenge already imported")
    if source.is_symlink() or not source.exists():
        raise ValueError("Source missing or symlink")
    if source.is_dir() and root.is_relative_to(source.resolve()):
        raise ValueError("Cannot import a workspace ancestor")
    lim=settings(root)
    originals=root/".local/inputs"/challenge_id
    canonical=root/"challenges"/challenge_id
    if originals.exists() or canonical.exists():
        raise ValueError("Import target exists; inspect previous incomplete import")
    originals.mkdir(parents=True)
    canonical.mkdir(parents=True)
    (canonical/"solution").mkdir(); (canonical/"evidence").mkdir()
    files=sorted(source.rglob("*")) if source.is_dir() else [source]
    manifest=[]; total=0
    deadline=time.monotonic()+lim["prescan_seconds"]
    for file in files:
        if file.is_symlink():
            raise ValueError("Input symlink rejected")
        if file.is_dir():
            continue
        if not file.is_file():
            raise ValueError("Non-regular input rejected")
        total+=file.stat().st_size
        if len(manifest)>=lim["import_max_files"] or total>lim["import_max_bytes"]:
            raise ValueError("INPUT_BUDGET_EXCEEDED")
        rel=file.relative_to(source) if source.is_dir() else Path(file.name)
        if ":" in str(rel) or "\\" in str(rel):
            raise ValueError("Unsafe input name")
        dest=originals/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(file,dest)
        dest.chmod(0o444)
        item={"path":rel.as_posix(),"sha256":digest(dest),"size":dest.stat().st_size}
        manifest.append(item)
    info={"id":challenge_id,"title":title,"category":category,"description":description,"source_url":""}
    (canonical/"challenge.toml").write_text("\n".join(f"{k} = {json.dumps(v,ensure_ascii=False)}" for k,v in info.items())+"\n",encoding="utf-8")
    atomic_json(canonical/"input-manifest.json",manifest)
    scan=[]
    for item in manifest:
        if time.monotonic()>deadline:
            scan.append({"path":item["path"],"status":"PRESCAN_BUDGET_EXCEEDED"})
            continue
        scan.append({"path":item["path"],**scan_file(originals/item["path"],deadline)})
    atomic_json(canonical/"prescan.json",scan)
    (canonical/"notes.md").write_text("# "+title+"\n\nImported; no findings yet.\n",encoding="utf-8")
    state.add(info,scope_hash)
    with state.tx() as c:
        c.execute("UPDATE challenges SET state='PRESCANNED' WHERE id=?",(challenge_id,))
    return info
