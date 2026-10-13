from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {"ACCEPTED_SELF", "ACCEPTED_TEAM", "DROPPED", "FAILED_CLOSED"}
INACTIVE = TERMINAL | {"PAUSED_MANUAL", "DIRTY_PAUSED", "FROZEN", "VERIFIED", "QUOTA_WAIT", "MANUAL_DAYBREAK_REQUIRED"}
ACTIVE = ("LEASED", "STARTING", "RUNNING", "CANCELLING", "COMMITTING")


def now():
    return time.time()


def uid(prefix):
    return prefix + "-" + uuid.uuid4().hex[:16]


def safe_id(value):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise ValueError("ID must be ASCII lowercase kebab-case, max 64 characters")
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def contained(root, relative):
    root = Path(root).resolve()
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in str(relative) or ":" in str(relative):
        raise ValueError("Unsafe relative path")
    target = root / p
    for ancestor in [target, *target.parents]:
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError("Symlink not allowed")
    target = target.resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escaped root")
    return target


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def settings(root=ROOT):
    return tomllib.loads((Path(root) / "config/limits.toml").read_text(encoding="utf-8"))


def strict_json(data, limit=32768):
    if len(data) > limit:
        raise ValueError("HANDOFF_TOO_LARGE")
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError("Duplicate JSON key")
            obj[k] = v
        return obj
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
