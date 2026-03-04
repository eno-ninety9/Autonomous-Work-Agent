import sqlite3
import json
import time


class AgentMemory:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def _connect(self):
        con = sqlite3.connect(self.db_path, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS runs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL,
                    title TEXT,
                    final_answer TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    ts REAL,
                    kind TEXT,
                    data TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    ts REAL,
                    role TEXT,
                    content TEXT
                )
            """)
            con.commit()

    # Runs
    def create_run(self, title: str = "New chat"):
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO runs(ts, title, final_answer) VALUES(?,?,?)",
                (time.time(), title, "")
            )
            con.commit()
            return cur.lastrowid

    def update_run_final(self, run_id: int, final_answer: str):
        with self._connect() as con:
            con.execute("UPDATE runs SET final_answer=? WHERE id=?", (final_answer, run_id))
            con.commit()

    def get_runs(self, limit=80):
        with self._connect() as con:
            return con.execute(
                "SELECT id, ts, title, final_answer FROM runs ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()

    def get_run(self, run_id: int):
        with self._connect() as con:
            return con.execute(
                "SELECT id, ts, title, final_answer FROM runs WHERE id=?",
                (run_id,)
            ).fetchone()

    # Messages
    def add_message(self, run_id: int, role: str, content: str):
        with self._connect() as con:
            con.execute(
                "INSERT INTO messages(run_id, ts, role, content) VALUES(?,?,?,?)",
                (run_id, time.time(), role, content)
            )
            con.commit()

    def get_messages(self, run_id: int, limit=400):
        with self._connect() as con:
            return con.execute(
                "SELECT ts, role, content FROM messages WHERE run_id=? ORDER BY id ASC LIMIT ?",
                (run_id, limit)
            ).fetchall()

    # Events (activity)
    def add_event(self, run_id: int, kind: str, data):
        with self._connect() as con:
            con.execute(
                "INSERT INTO events(run_id, ts, kind, data) VALUES(?,?,?,?)",
                (run_id, time.time(), kind, json.dumps(data, ensure_ascii=False))
            )
            con.commit()

    def get_events(self, run_id: int, limit=800):
        with self._connect() as con:
            rows = con.execute(
                "SELECT ts, kind, data FROM events WHERE run_id=? ORDER BY id ASC LIMIT ?",
                (run_id, limit)
            ).fetchall()
        out = []
        for ts, kind, data in rows:
            try:
                out.append((ts, kind, json.loads(data)))
            except Exception:
                out.append((ts, kind, {"raw": data}))
        return out
