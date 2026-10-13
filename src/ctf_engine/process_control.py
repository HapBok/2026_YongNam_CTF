import asyncio
import os
from pathlib import Path
import signal


def process_token(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return text[text.rfind(")")+2:].split()[19]
    except (OSError, IndexError):
        return ""


def same_process(pid, token):
    return bool(pid and token and process_token(pid) == token)


def group_alive(pid):
    if not pid:
        return False
    try:
        os.killpg(pid,0)
        return True
    except ProcessLookupError:
        return False


async def terminate(proc, grace=3):
    """Kill the whole Linux group even when its leader has already exited."""
    if os.name == "posix":
        try:
            os.killpg(proc.pid,signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(),timeout=grace)
        except asyncio.TimeoutError:
            pass
        if group_alive(proc.pid):
            try:
                os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        await proc.wait()
    else:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


class InstanceLock:
    def __init__(self,path):
        self.path=Path(path)
        self.file=None

    def __enter__(self):
        if os.name != "posix":
            raise RuntimeError("Supervisor requires Linux/WSL; offline tests are cross-platform")
        import fcntl
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open("a+")
        try:
            fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another Supervisor owns this workspace")
        return self

    def __exit__(self,*args):
        self.file.close()
