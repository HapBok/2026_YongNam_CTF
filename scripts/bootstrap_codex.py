#!/usr/bin/env python3
"""Install the pinned official Linux package only under this project."""
import hashlib
import json
from pathlib import Path
import platform
import tarfile
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
VERSION="0.162.1"


def main():
    if platform.system() != "Linux":
        raise SystemExit("Run this script in WSL Ubuntu")
    target={"x86_64":"x86_64-unknown-linux-musl","aarch64":"aarch64-unknown-linux-musl"}[platform.machine()]
    base=f"https://releases.openai.com/codex/releases/{VERSION}/"
    try:
        with urllib.request.urlopen(base+"release.json",timeout=30) as r:
            release=json.load(r)
    except urllib.error.HTTPError:
        url=f"https://api.github.com/repos/openai/codex/releases/tags/rust-v{VERSION}"
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"ctf-engine-bootstrap"}),timeout=30) as r:
            release=json.load(r)
        base=f"https://github.com/openai/codex/releases/download/rust-v{VERSION}/"
    assets={a["name"]:a for a in release["assets"]}
    package=f"codex-package-{target}.tar.gz"
    if package not in assets:
        package=f"codex-npm-linux-{'x64' if platform.machine()=='x86_64' else 'arm64'}-{VERSION}.tgz"
    if package not in assets:
        raise SystemExit("No official Linux package in release metadata")
    dest=ROOT/".local/toolchains/codex"
    marker=dest/"install-receipt.json"
    if marker.exists():
        print("Already installed:",marker)
        return
    dest.mkdir(parents=True,exist_ok=True)
    archive=dest/package
    h=hashlib.sha256()
    with urllib.request.urlopen(base+package,timeout=60) as r, archive.open("xb") as f:
        while chunk:=r.read(1024*1024):
            h.update(chunk); f.write(chunk)
    expected=assets[package]["digest"].removeprefix("sha256:")
    if h.hexdigest()!=expected:
        raise SystemExit("Checksum mismatch; nothing executed")
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            p=Path(member.name)
            if p.is_absolute() or ".." in p.parts or member.isdev() or member.issym() or member.islnk():
                raise SystemExit("Unexpected unsafe package member")
        tf.extractall(dest,filter="data")
    binary=dest/"bin/codex"
    if not binary.exists():
        binary=next(dest.glob("package/vendor/*/codex/codex"))
        (dest/"bin").mkdir(exist_ok=True)
        import shutil
        shutil.copy2(binary,dest/"bin/codex")
        binary=dest/"bin/codex"
    for p in dest.rglob("*"):
        if p.is_file() and (p.name in {"codex","rg","bwrap","codex-code-mode-host"}):
            p.chmod(0o755)
    marker.write_text(json.dumps({"version":VERSION,"source":base+package,"sha256":expected},indent=2))
    print("Installed:",binary)


if __name__=="__main__":
    main()
