from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Profile:
    id: str
    stage: str
    model: str
    effort: str
    timeout: int
    prompt: str
    daybreak: bool = False
    resumable: bool = False
    fallback: str = ""


def load(root):
    profiles = {}
    for path in sorted((Path(root) / "config/profiles").glob("*.toml")):
        p = Profile(**tomllib.loads(path.read_text(encoding="utf-8")))
        if p.effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Unsupported or nested-agent effort")
        if not (Path(root) / p.prompt).is_file():
            raise ValueError("Missing profile prompt")
        profiles[p.id] = p
    for p in profiles.values():
        if p.fallback and p.fallback not in profiles:
            raise ValueError("Missing fallback profile")
        if p.daybreak and p.fallback:
            raise ValueError("Daybreak may not fall back silently")
    return profiles
