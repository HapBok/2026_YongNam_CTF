#!/usr/bin/env python3
"""Connect the same user's existing Windows Codex login to WSL without copying secrets."""
import argparse
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    args=parser.parse_args()
    if os.name!="posix":raise SystemExit("Run inside WSL")
    source=args.source.resolve(strict=True)
    target=Path.home()/".codex/auth.json"
    if target.exists() or target.is_symlink():
        if target.is_symlink() and target.resolve()==source:
            print("Existing local login link is already correct")
            return
        raise SystemExit("Existing Linux credentials preserved; no change made")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.symlink_to(source)
    print("Connected existing local Windows Codex login; no token printed or copied")


if __name__=="__main__":main()
