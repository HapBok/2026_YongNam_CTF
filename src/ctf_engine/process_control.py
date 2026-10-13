import asyncio
import os
from pathlib import Path
import signal
import time


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


def recover_metadata(state):
    """Fail closed on a live owner or unidentifiable orphan process group."""
    lease=state.meta('metadata_slot')
    if not lease:return
    if same_process(lease.get('owner_pid'),lease.get('owner_identity')):
        raise ValueError('METADATA_GENERATOR_STILL_RUNNING: stop it before recover')
    child=lease.get('child_pid')
    if child and group_alive(child):
        if not same_process(child,lease.get('child_identity')):
            raise ValueError('METADATA_ORPHAN_REVIEW_REQUIRED: process identity cannot be confirmed')
        os.killpg(child,signal.SIGKILL)
        deadline=time.monotonic()+7
        while group_alive(child) and time.monotonic()<deadline:time.sleep(.1)
        if group_alive(child):raise ValueError('METADATA_PROCESS_GROUP_STILL_ALIVE')
    state.metadata_release(lease['token'])


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
