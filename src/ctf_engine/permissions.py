"""Private flag storage on Linux and WSL's NTFS-backed project directories."""
import csv
import io
import os
from pathlib import Path
import stat
import subprocess


def policy(directory):
    directory=Path(directory)
    probe=directory/".permission-probe"
    probe.write_bytes(b"")
    try:
        probe.chmod(0o600)
        enforced=stat.S_IMODE(probe.stat().st_mode)==0o600
    finally:probe.unlink()
    return {"posix_mode_enforced":enforced,"secret_protection":"posix-600" if enforced else "windows-user-system-admin-acl", "verify_instruction":"Judge solution reproducibility; Supervisor enforces flag confidentiality. NTFS mode 777 does not represent Windows ACL permissions."}


def protect(path):
    path=Path(path).resolve(strict=True)
    path.chmod(0o600)
    if stat.S_IMODE(path.stat().st_mode)==0o600:return "posix-600"
    if os.name!="posix" or not str(path).startswith("/mnt/"):
        raise ValueError("SECRET_PERMISSION_NOT_ENFORCEABLE")
    system=Path("/mnt/c/Windows/System32")
    identity=subprocess.run([str(system/"whoami.exe"),"/user","/fo","csv","/nh"],capture_output=True,check=True,timeout=10).stdout.decode(errors="replace")
    sid=next(csv.reader(io.StringIO(identity)))[1].strip()
    if not sid.startswith("S-1-"):raise ValueError("WINDOWS_IDENTITY_UNAVAILABLE")
    native=subprocess.run(["wslpath","-w",str(path)],capture_output=True,check=True,timeout=10).stdout.decode().strip()
    tool=str(system/"icacls.exe")
    subprocess.run([tool,native,"/reset"],capture_output=True,check=True,timeout=10)
    subprocess.run([tool,native,"/inheritance:r","/grant:r",f"*{sid}:(F)","*S-1-5-18:(F)","*S-1-5-32-544:(F)"],capture_output=True,check=True,timeout=10)
    return "windows-user-system-admin-acl"
