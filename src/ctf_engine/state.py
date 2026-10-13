from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .common import ACTIVE, INACTIVE, TERMINAL, now, uid

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS challenges(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT DEFAULT 'unknown',
 description TEXT DEFAULT '', state TEXT DEFAULT 'NEW', generation INTEGER DEFAULT 0,
 created REAL NOT NULL, started REAL, evidence_at REAL, primitive INTEGER DEFAULT 0,
 extension INTEGER DEFAULT 0, rotation INTEGER DEFAULT 0, candidate_ref TEXT,
 scope_hash TEXT NOT NULL, last_error TEXT DEFAULT '', prior_state TEXT,
 solve_seconds REAL DEFAULT 0, classification_seconds REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks(
 task_id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL REFERENCES challenges(id),
 stage TEXT NOT NULL, profile_id TEXT NOT NULL, priority INTEGER NOT NULL,
 generation INTEGER NOT NULL, attempt INTEGER NOT NULL, parent_task_id TEXT,
 hypothesis_key TEXT DEFAULT 'main', session_id TEXT, status TEXT DEFAULT 'READY',
 worker_id TEXT, lease_id TEXT, lease_until REAL, pid INTEGER, process_token TEXT,
 created REAL NOT NULL, started REAL, finished REAL, result_path TEXT,
 error TEXT DEFAULT '', retries INTEGER DEFAULT 0, available_at REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(status,priority DESC,created,task_id);
CREATE TABLE IF NOT EXISTS workers(
 id TEXT PRIMARY KEY, token TEXT NOT NULL, heartbeat REAL NOT NULL, pid INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 event_seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
 event TEXT NOT NULL, challenge_id TEXT, task_id TEXT, generation INTEGER,
 worker_id TEXT, lease_id TEXT, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(
 task_id TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL,
 generation INTEGER NOT NULL, PRIMARY KEY(task_id,path));
CREATE TABLE IF NOT EXISTS evidence_seen(
 challenge_id TEXT NOT NULL, generation INTEGER NOT NULL, content_hash TEXT NOT NULL,
 PRIMARY KEY(challenge_id,generation,content_hash));
"""


class State:
    def __init__(self, root):
        self.root = Path(root).resolve()
        (self.root / ".runtime").mkdir(parents=True, exist_ok=True)
        self.path = self.root / ".runtime/state.db"
        with self.connect() as c:
            c.executescript(SCHEMA)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def rows(self, query, args=()):
        c = self.connect()
        try:
            return [dict(r) for r in c.execute(query, args)]
        finally:
            c.close()

    def one(self, query, args=()):
        rows = self.rows(query, args)
        return rows[0] if rows else None

    def meta(self, key, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def setmeta(self, key, value, c=None):
        if c is None:
            with self.tx() as c:
                self.setmeta(key, value, c)
            return
        c.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))

    def event(self, c, event, challenge_id=None, task=None, **details):
        task = task or {}
        c.execute("INSERT INTO events(timestamp,event,challenge_id,task_id,generation,worker_id,lease_id,details) VALUES(?,?,?,?,?,?,?,?)",
                  (now(), event, challenge_id or task.get("challenge_id"), task.get("task_id"),
                   task.get("generation"), task.get("worker_id"), task.get("lease_id"),
                   json.dumps(details, ensure_ascii=False)))

    def add(self, info, scope_hash):
        with self.tx() as c:
            c.execute("INSERT INTO challenges(id,title,category,description,created,scope_hash) VALUES(?,?,?,?,?,?)",
                      (info["id"], info["title"], info["category"], info["description"], now(), scope_hash))
            self.event(c, "IMPORTED", info["id"])

    def enqueue(self, challenge_id, profile, priority=50, parent=None, hypothesis="main", session=None, c=None, retries=0, delay=0):
        if c is None:
            with self.tx() as c:
                return self.enqueue(challenge_id, profile, priority, parent, hypothesis, session, c, retries, delay)
        ch = c.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if not ch or ch["state"] in INACTIVE:
            raise ValueError("Challenge is not runnable")
        count = c.execute("SELECT COUNT(*) FROM tasks WHERE challenge_id=? AND generation=?", (challenge_id,ch["generation"])).fetchone()[0]
        if count >= 20:
            c.execute("UPDATE challenges SET state='FROZEN', last_error='STAGE_BUDGET' WHERE id=?",(challenge_id,))
            return None
        task_id = uid("tsk-" + challenge_id)
        c.execute("INSERT INTO tasks(task_id,challenge_id,stage,profile_id,priority,generation,attempt,parent_task_id,hypothesis_key,session_id,created,retries,available_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (task_id,challenge_id,profile.stage,profile.id,priority,ch["generation"],count+1,parent,hypothesis,session,now(),retries,now()+delay))
        self.event(c, "QUEUED", challenge_id, profile=profile.id, task_id_created=task_id)
        return task_id

    def register(self, worker, token, pid, ttl):
        with self.tx() as c:
            old = c.execute("SELECT * FROM workers WHERE id=?",(worker,)).fetchone()
            if old and old["heartbeat"] > now()-ttl and old["token"] != token:
                raise ValueError("Worker ID already live")
            c.execute("INSERT INTO workers VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET token=excluded.token, heartbeat=excluded.heartbeat,pid=excluded.pid",(worker,token,now(),pid))

    def claim(self, worker, token, ttl, cap=8, depth=False):
        with self.tx() as c:
            live = c.execute("SELECT token FROM workers WHERE id=?",(worker,)).fetchone()
            if not live or live[0] != token:
                return None
            self.setmeta("peak_active", max(self.meta("peak_active",0),0),c)
            running = c.execute("SELECT * FROM tasks WHERE status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')").fetchall()
            if len(running) >= min(cap,8) or any(r["worker_id"] == worker for r in running):
                return None
            if self.meta("shutdown",False) or self.meta("dispatch_blocked") or now()-self.meta("supervisor_heartbeat",0) > ttl:
                return None
            candidates = c.execute("SELECT t.* FROM tasks t JOIN challenges ch ON ch.id=t.challenge_id WHERE t.status='READY' AND t.generation=ch.generation AND t.available_at<=? ORDER BY priority DESC,created,task_id",(now(),)).fetchall()
            for row in candidates:
                task = dict(row)
                ch = c.execute("SELECT state FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()
                if ch[0] in INACTIVE:
                    continue
                quota=self.meta("quota_remaining",100)
                if quota<=20 and not task["stage"].startswith("verify"):
                    candidate=c.execute("SELECT candidate_ref FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()[0]
                    if not candidate:
                        continue
                peers = [r for r in running if r["challenge_id"] == task["challenge_id"]]
                if len(peers) >= (2 if depth else 1) or any(r["hypothesis_key"] == task["hypothesis_key"] for r in peers):
                    continue
                lease = uid("lease")
                c.execute("UPDATE tasks SET status='LEASED',worker_id=?,lease_id=?,lease_until=?,started=? WHERE task_id=?",(worker,lease,now()+ttl,now(),task["task_id"]))
                c.execute("UPDATE challenges SET started=COALESCE(started,?),evidence_at=COALESCE(evidence_at,?) WHERE id=?",(now(),now(),task["challenge_id"]))
                task.update(status="LEASED",worker_id=worker,lease_id=lease,lease_until=now()+ttl,started=now())
                self.event(c,"CLAIMED",task=task)
                self.setmeta("peak_active",max(self.meta("peak_active",0),len(running)+1),c)
                return task
            return None

    def heartbeat(self, worker, token, task, ttl):
        with self.tx() as c:
            c.execute("UPDATE workers SET heartbeat=? WHERE id=? AND token=?",(now(),worker,token))
            if not task:
                return True
            r = c.execute("SELECT t.status,t.generation,t.lease_until,ch.generation AS current_generation FROM tasks t JOIN challenges ch ON ch.id=t.challenge_id WHERE task_id=? AND lease_id=?",(task["task_id"],task["lease_id"])).fetchone()
            if not r or r["generation"] != r["current_generation"] or r["status"] not in {"LEASED","STARTING","RUNNING"} or (r["lease_until"] or 0)<now():
                return False
            c.execute("UPDATE tasks SET lease_until=? WHERE task_id=?",(now()+ttl,task["task_id"]))
            return True

    def live(self,task):
        row=self.one("SELECT t.status,t.generation,t.lease_until,ch.generation current_generation FROM tasks t JOIN challenges ch ON ch.id=t.challenge_id WHERE task_id=? AND lease_id=?",(task["task_id"],task["lease_id"]))
        return bool(row and row["status"] in {"LEASED","STARTING","RUNNING"} and row["generation"]==row["current_generation"] and (row["lease_until"] or 0)>=now())

    def running(self, task, pid, token):
        with self.tx() as c:
            r = c.execute("SELECT generation FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()
            if not r or r[0] != task["generation"]:
                return False
            n = c.execute("UPDATE tasks SET status='RUNNING',pid=?,process_token=? WHERE task_id=? AND lease_id=? AND status='LEASED'",(pid,token,task["task_id"],task["lease_id"])).rowcount
            if n:
                self.event(c,"RUNNING",task=task,pid=pid)
            return bool(n)

    def ready_result(self, task, path, error=""):
        with self.tx() as c:
            r = c.execute("SELECT generation FROM challenges WHERE id=?",(task["challenge_id"],)).fetchone()
            if not r or r[0] != task["generation"]:
                self.event(c,"STALE_RESULT",task=task)
                return False
            n = c.execute("UPDATE tasks SET status='COMMITTING',result_path=?,error=? WHERE task_id=? AND lease_id=? AND lease_until>=? AND status IN ('RUNNING','LEASED')",(str(path),error,task["task_id"],task["lease_id"],now())).rowcount
            return bool(n)

    def control(self, challenge_id, target, reason="", hard=False):
        if target not in INACTIVE:
            raise ValueError("Invalid control target")
        with self.tx() as c:
            ch = c.execute("SELECT * FROM challenges WHERE id=?",(challenge_id,)).fetchone()
            if not ch:
                raise ValueError("Unknown challenge")
            if ch["state"] in TERMINAL:
                if ch["state"] == target:
                    return
                raise ValueError("Terminal challenge cannot be changed")
            c.execute("UPDATE challenges SET state=?,prior_state=?,generation=generation+1,last_error=? WHERE id=?",(target,ch["state"],reason,challenge_id))
            c.execute("UPDATE tasks SET status='CANCELLED',finished=? WHERE challenge_id=? AND status='READY'",(now(),challenge_id))
            c.execute("UPDATE tasks SET status='CANCELLING',error=?,available_at=? WHERE challenge_id=? AND status IN ('LEASED','STARTING','RUNNING','COMMITTING')",("HARD_STOP" if hard else reason,now(),challenge_id))
            self.event(c,"CONTROL",challenge_id,target=target,reason=reason,hard=hard,generation=ch["generation"]+1)

    def release(self, task_id, status, error=""):
        if status not in {"PAUSED","CANCELLED","FAILED","TIMED_OUT","INVALID_OUTPUT","SUCCEEDED"}:
            raise ValueError("Invalid terminal task status")
        with self.tx() as c:
            c.execute("UPDATE tasks SET status=?,finished=?,error=? WHERE task_id=? AND status IN ('LEASED','STARTING','RUNNING','CANCELLING','COMMITTING')",(status,now(),error,task_id))

    def backup(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        source, dest = self.connect(), sqlite3.connect(path)
        try:
            source.backup(dest)
        finally:
            source.close(); dest.close()
