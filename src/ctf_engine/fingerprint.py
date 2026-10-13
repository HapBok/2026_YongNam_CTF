import hashlib
from pathlib import Path


def calculate(root):
    root=Path(root)
    h=hashlib.sha256()
    for directory in ("src","config/profiles","prompts","schemas","scripts","tests"):
        for file in sorted((root/directory).rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts and not file.suffix==".pyc":
                h.update(file.relative_to(root).as_posix().encode());h.update(file.read_bytes())
    for name in ("ctfctl.py","config/limits.toml","config/routing.toml"):
        h.update(name.encode());h.update((root/name).read_bytes())
    return h.hexdigest()
